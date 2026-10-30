"""Async client for the Wazuh server API (port 55000).

Read-only by design: the only non-GET request is the login, `POST /security/user/authenticate`.

Behaviour:

- **Auth.** Basic auth to `/security/user/authenticate?raw=true` returns a plain-text JWT. The token
  is cached until shortly before its `exp` claim and refreshed once on a 401.
- **Retries.** Connection errors, timeouts, 429 and 5xx are retried with exponential backoff, up to
  `max_retries` extra attempts. Then `WazuhUnavailable` is raised.
- **Errors.** Every failure is a `WazuhError` subclass, so callers never see httpx exceptions.

Wazuh quirk: an unknown agent ID does not return 404. It returns HTTP 200 with `"error": 1` and a
`failed_items` entry with code 1701. `_check_failed_items` turns that into `WazuhNotFound`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from .models import Agent, FIMEntry, Port, SCACheck, SCAPolicy

log = logging.getLogger(__name__)

AGENT_NOT_FOUND_CODE = 1701
DEFAULT_TOKEN_TTL = 900.0  # Wazuh default auth_token_exp_timeout
TOKEN_REFRESH_MARGIN = 30.0


class WazuhError(Exception):
    """Base class for every error raised by this module."""


class WazuhUnavailable(WazuhError):
    """The API could not be reached, timed out, or kept returning 5xx/429."""


class WazuhAuthError(WazuhError):
    """The API rejected the configured credentials."""


class WazuhNotFound(WazuhError):
    """The requested agent does not exist."""


class WazuhAPIError(WazuhError):
    """Any other error response (4xx, or `"error": 1` in the body)."""

    def __init__(self, message: str, status_code: int | None = None, code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _jwt_expiry(token: str) -> float | None:
    """Return the `exp` claim (epoch seconds) without verifying the signature, or None."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except (IndexError, KeyError, ValueError, TypeError):
        return None


def _check_failed_items(body: dict[str, Any], what: str) -> None:
    """Raise if a 200 response reports failed items (Wazuh's way of saying 'not found')."""
    data = body.get("data") or {}
    for item in data.get("failed_items") or []:
        error = item.get("error") or {}
        code = error.get("code")
        message = error.get("message", "unknown error")
        if code == AGENT_NOT_FOUND_CODE:
            raise WazuhNotFound(f"{what}: {message}")
        raise WazuhAPIError(f"{what}: {message}", code=code)


class WazuhClient:
    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        *,
        verify_tls: bool = True,
        timeout: float = 10.0,
        max_retries: int = 2,
        backoff_base: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._user = user
        self._password = password
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            verify=verify_tls,
            timeout=httpx.Timeout(timeout),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- transport ------------------------------------------------------------------------------

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send one request with retry and backoff on transient failures."""
        attempts = self._max_retries + 1
        last_reason = ""
        for attempt in range(attempts):
            if attempt:
                await asyncio.sleep(self._backoff_base * 2 ** (attempt - 1))
            try:
                response = await self._http.request(method, path, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_reason = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "Wazuh %s %s failed (%s), attempt %d", method, path, last_reason, attempt + 1
                )
                continue
            if response.status_code >= 500 or response.status_code == 429:
                last_reason = f"HTTP {response.status_code}"
                log.warning(
                    "Wazuh %s %s returned %s, attempt %d", method, path, last_reason, attempt + 1
                )
                continue
            return response
        raise WazuhUnavailable(f"Wazuh API unreachable after {attempts} attempts ({last_reason})")

    async def _login(self) -> None:
        response = await self._send(
            "POST",
            "/security/user/authenticate",
            params={"raw": "true"},
            auth=(self._user, self._password),
        )
        if response.status_code == 401:
            raise WazuhAuthError("Wazuh API rejected the configured user or password")
        if response.status_code != 200:
            raise WazuhAPIError(
                f"Login failed with HTTP {response.status_code}", status_code=response.status_code
            )
        token = response.text.strip()
        expires_at = _jwt_expiry(token) or (self._clock() + DEFAULT_TOKEN_TTL)
        self._token = token
        self._token_expires_at = expires_at

    async def _bearer(self) -> str:
        async with self._token_lock:
            expiring = self._clock() >= self._token_expires_at - TOKEN_REFRESH_MARGIN
            if self._token is None or expiring:
                await self._login()
            assert self._token is not None
            return self._token

    def _invalidate_token(self) -> None:
        self._token = None
        self._token_expires_at = 0.0

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET a JSON endpoint, refreshing the token once on a 401."""
        for refreshed in (False, True):
            token = await self._bearer()
            response = await self._send(
                "GET", path, params=params, headers={"Authorization": f"Bearer {token}"}
            )
            if response.status_code == 401 and not refreshed:
                log.info("Wazuh token rejected; logging in again")
                self._invalidate_token()
                continue
            break
        if response.status_code == 401:
            raise WazuhAuthError("Wazuh API rejected a freshly issued token")
        if response.status_code == 404:
            raise WazuhNotFound(f"{path}: not found")
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise WazuhAPIError(
                f"{path}: HTTP {response.status_code}: {detail}", status_code=response.status_code
            )
        try:
            return response.json()
        except ValueError as exc:
            raise WazuhAPIError(f"{path}: response is not JSON") from exc

    @staticmethod
    def _items(body: dict[str, Any]) -> list[dict[str, Any]]:
        return (body.get("data") or {}).get("affected_items") or []

    @staticmethod
    def _total(body: dict[str, Any]) -> int:
        return int((body.get("data") or {}).get("total_affected_items") or 0)

    # --- calls ----------------------------------------------------------------------------------

    async def ping(self) -> None:
        """Cheapest authenticated call; raises a WazuhError if the API is not usable."""
        await self._get("/manager/info")

    async def list_agents(self, limit: int = 500) -> list[Agent]:
        body = await self._get("/agents", {"limit": limit, "sort": "+id"})
        return [Agent.model_validate(item) for item in self._items(body)]

    async def get_agent(self, agent_id: str) -> Agent:
        body = await self._get("/agents", {"agents_list": agent_id})
        _check_failed_items(body, f"agent {agent_id}")
        items = self._items(body)
        if not items:
            raise WazuhNotFound(f"agent {agent_id}: not found")
        return Agent.model_validate(items[0])

    async def sca_policies(self, agent_id: str) -> list[SCAPolicy]:
        body = await self._get(f"/sca/{agent_id}")
        _check_failed_items(body, f"SCA for agent {agent_id}")
        return [SCAPolicy.model_validate(item) for item in self._items(body)]

    async def sca_failed_checks(
        self, agent_id: str, policy_id: str, limit: int = 500
    ) -> tuple[list[SCACheck], int]:
        """Failed checks of one policy, plus the total number of failed checks."""
        body = await self._get(
            f"/sca/{agent_id}/checks/{policy_id}",
            {"result": "failed", "limit": limit, "sort": "+id"},
        )
        _check_failed_items(body, f"SCA checks for agent {agent_id}")
        checks = [SCACheck.model_validate(item) for item in self._items(body)]
        return checks, self._total(body)

    async def sca_configured_policies(self, agent_id: str) -> list[str] | None:
        """Policy files in the agent's active SCA configuration, or None if unreadable.

        Needs the agent to be connected; for a disconnected agent Wazuh returns an error, which is
        treated as "unknown" rather than a failure of the brief.
        """
        try:
            body = await self._get(f"/agents/{agent_id}/config/wmodules/wmodules")
        except WazuhAPIError:
            return None
        modules = (body.get("data") or {}).get("wmodules") or []
        for module in modules:
            if "sca" in module:
                return list(module["sca"].get("policies") or [])
        return []

    async def syscheck(self, agent_id: str, limit: int = 20) -> tuple[list[FIMEntry], int]:
        """Most recently modified FIM entries, plus the total number of entries."""
        body = await self._get(f"/syscheck/{agent_id}", {"limit": limit, "sort": "-mtime"})
        _check_failed_items(body, f"FIM for agent {agent_id}")
        return [FIMEntry.model_validate(item) for item in self._items(body)], self._total(body)

    async def listening_ports(self, agent_id: str, limit: int = 100) -> list[Port]:
        body = await self._get(
            f"/syscollector/{agent_id}/ports", {"state": "listening", "limit": limit}
        )
        _check_failed_items(body, f"ports for agent {agent_id}")
        return [Port.model_validate(item) for item in self._items(body)]
