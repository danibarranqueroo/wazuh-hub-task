"""FastAPI app: one JSON endpoint for the brief, one HTML page, and health checks.

Run from `app/`:  uv run uvicorn wazuh_brief.main:app --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Request
from fastapi import Path as PathParam
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .config import Settings, get_settings
from .llm import ClaudeSummarizer, MockSummarizer, summarize
from .models import AgentInfo, AgentListItem, Brief, Coverage, ErrorBody, Fix, StaleBrief
from .posture import CHECKS_SENT, build_input, collect_posture, confidence
from .wazuh_client import (
    WazuhAPIError,
    WazuhAuthError,
    WazuhClient,
    WazuhNotFound,
    WazuhUnavailable,
)

log = logging.getLogger("wazuh_brief")
TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")

AgentId = Annotated[str, PathParam(pattern=r"^\d{3,5}$", description="Wazuh agent ID, e.g. 001")]


def _error(status: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content=ErrorBody(error=error, detail=detail).model_dump()
    )


def create_app(
    settings: Settings | None = None,
    wazuh: WazuhClient | None = None,
    claude: ClaudeSummarizer | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own client and summarizer; production reads settings."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = wazuh or WazuhClient(
            settings.wazuh_api_url,
            settings.wazuh_api_user,
            settings.wazuh_api_password.get_secret_value(),
            verify_tls=settings.wazuh_verify_tls,
            timeout=settings.wazuh_timeout_seconds,
            max_retries=settings.wazuh_max_retries,
        )
        primary = claude
        if primary is None and settings.anthropic_api_key is not None:
            key = settings.anthropic_api_key.get_secret_value()
            if key:
                primary = ClaudeSummarizer(
                    key,
                    settings.llm_model,
                    max_tokens=settings.llm_max_tokens,
                    timeout=settings.llm_timeout_seconds,
                )
        app.state.wazuh = client
        app.state.claude = primary
        app.state.mock = MockSummarizer()
        app.state.cache = {}  # agent_id -> last good Brief, per process
        log.info("Summarizer: %s", f"claude ({primary.model})" if primary else "mock only")
        try:
            yield
        finally:
            await client.aclose()

    app = FastAPI(
        title="Wazuh Agent Hardening Brief",
        version="0.1.0",
        description="What to fix first on one Wazuh agent, from live Wazuh server API data.",
        lifespan=lifespan,
    )

    @app.exception_handler(WazuhUnavailable)
    async def _unavailable(_: Request, exc: WazuhUnavailable) -> JSONResponse:
        return _error(503, "wazuh_unavailable", f"The Wazuh server API is unreachable: {exc}")

    @app.exception_handler(WazuhAuthError)
    async def _auth(_: Request, exc: WazuhAuthError) -> JSONResponse:
        return _error(
            502, "wazuh_auth_failed", f"{exc}. Check WAZUH_API_USER and WAZUH_API_PASSWORD."
        )

    @app.exception_handler(WazuhNotFound)
    async def _not_found(_: Request, exc: WazuhNotFound) -> JSONResponse:
        return _error(404, "agent_not_found", str(exc))

    @app.exception_handler(WazuhAPIError)
    async def _api_error(_: Request, exc: WazuhAPIError) -> JSONResponse:
        return _error(502, "wazuh_api_error", str(exc))

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        """Liveness: the process is up. Does not call Wazuh."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"], responses={503: {"model": ErrorBody}})
    async def readyz(request: Request) -> dict[str, str]:
        """Readiness: the Wazuh server API answers an authenticated request."""
        await request.app.state.wazuh.ping()
        return {"status": "ready", "wazuh": "ok"}

    @app.get("/agents", tags=["agents"], responses={503: {"model": ErrorBody}})
    async def list_agents(request: Request, include_manager: bool = False) -> list[AgentListItem]:
        """Agents known to the manager. Agent 000 (the manager itself) is hidden by default."""
        agents = await request.app.state.wazuh.list_agents()
        return [
            AgentListItem(id=a.id, name=a.name, status=a.status, os=a.os_label, ip=a.ip)
            for a in agents
            if include_manager or not a.is_manager
        ]

    @app.get(
        "/agents/{agent_id}/brief",
        tags=["agents"],
        response_model=Brief | StaleBrief,
        responses={404: {"model": ErrorBody}, 503: {"model": ErrorBody}},
    )
    async def agent_brief(request: Request, agent_id: AgentId) -> Brief | StaleBrief:
        """Prioritized hardening brief for one agent.

        If Wazuh is unreachable and a brief for this agent was built earlier by this process, that
        brief is returned with `stale: true` instead of a 503.
        """
        state = request.app.state
        try:
            posture = await collect_posture(state.wazuh, agent_id)
        except WazuhUnavailable as exc:
            cached: Brief | None = state.cache.get(agent_id)
            if cached is None:
                raise
            log.warning("Wazuh unavailable; serving cached brief for agent %s", agent_id)
            return StaleBrief(**cached.model_dump(exclude={"stale"}), stale_reason=str(exc))

        payload = build_input(posture)
        result = await summarize(payload, state.claude, state.mock)
        agent = posture.agent
        brief = Brief(
            agent=AgentInfo(
                id=agent.id,
                name=agent.name,
                status=agent.status,
                os=agent.os_label,
                ip=agent.ip,
                wazuh_version=agent.version,
            ),
            generated_at=datetime.now(UTC),
            source=result.source,
            model=result.model,
            fallback_reason=result.fallback_reason,
            summary=result.draft.summary,
            fixes=[Fix(rank=i, **f.model_dump()) for i, f in enumerate(result.draft.fixes, 1)],
            coverage=Coverage(
                confidence=confidence(posture),
                note=result.draft.coverage_note,
                sca_policies=len(posture.sca_policies),
                sca_failed_checks_total=posture.sca_failed_total,
                sca_failed_checks_considered=min(len(posture.sca_failed_checks), CHECKS_SENT),
                fim_entries_considered=len(posture.fim_entries),
                listening_ports_considered=len(posture.listening_ports),
                gaps=payload.coverage_gaps,
            ),
        )
        state.cache[agent_id] = brief
        return brief

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(request, "index.html")

    return app


app = create_app()
