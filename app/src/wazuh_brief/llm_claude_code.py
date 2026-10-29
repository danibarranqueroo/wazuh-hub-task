"""DEV ONLY: run the brief prompt through the Claude Agent SDK on the developer's Claude Code login.

Why this exists: it lets a developer without an API budget see real model output while working on
the prompt and the UI. It is never selected automatically (`LLM_PROVIDER=claude-code` only) and is
not part of the production design. The Agent SDK docs say: "Unless previously approved, Anthropic
does not allow third party developers to offer claude.ai login or rate limits for their products,
including agents built on the Claude Agent SDK." Production uses `ClaudeSummarizer` with an API
key. See docs/adr/0002-dev-only-agent-sdk-summarizer.md.

Install with `uv sync --extra claude-code`. The SDK bundles the Claude Code CLI (about 260 MB),
which is why it is an optional extra.

Isolation. The run gets:

- the same system prompt, input payload and output schema as `ClaudeSummarizer`;
- no tools at all (`tools=[]`, which the SDK passes as `--tools ""`) and one turn (`max_turns=1`);
- no user, project or local settings (`setting_sources=[]`), no MCP servers
  (`--strict-mcp-config` without `--mcp-config`), no skills or slash commands, no saved session;
- an empty temporary working directory, so no project `CLAUDE.md` or files are in reach.

The SDK's own `output_format` is not used: it works through an extra `StructuredOutput` tool call
and a second turn. Instead the schema is part of the prompt, and the reply is validated with the
same pydantic model (`Draft`) as the API path. Invalid output falls back to the mock.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from types import ModuleType
from typing import Any, Literal

from pydantic import ValidationError

from .llm import MAX_FIXES, OUTPUT_SCHEMA, SYSTEM_PROMPT, SummarizerError
from .models import BriefInput, Draft

log = logging.getLogger(__name__)

MIN_TIMEOUT = 120.0  # CLI start-up plus a full model reply; the API path's 45 s is too tight

JSON_INSTRUCTIONS = (
    "\n\nOutput format: reply with exactly one JSON object and nothing else (no prose, no "
    "Markdown code fences). It must validate against this JSON Schema:\n"
    + json.dumps(OUTPUT_SCHEMA, indent=1)
)

ISOLATION_FLAGS: dict[str, str | None] = {
    "strict-mcp-config": None,
    "disable-slash-commands": None,
    "no-session-persistence": None,
}


def _import_sdk() -> ModuleType:
    try:
        import claude_agent_sdk
    except ImportError as exc:
        raise SummarizerError(
            "claude-agent-sdk is not installed (run: uv sync --extra claude-code)"
        ) from exc
    return claude_agent_sdk


def parse_draft(text: str | None) -> Draft:
    """Validate the model's reply as a `Draft`. Tolerates a Markdown code fence around the JSON."""
    if not text or not text.strip():
        raise SummarizerError("Claude Code returned no text")
    body = text.strip()
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        raise SummarizerError("Claude Code reply is not JSON")
    try:
        draft = Draft.model_validate(json.loads(body[start : end + 1]))
    except (ValueError, ValidationError) as exc:
        raise SummarizerError("Claude Code reply did not match the schema") from exc
    if not draft.fixes:
        raise SummarizerError("Claude Code returned no fixes")
    draft.fixes = draft.fixes[:MAX_FIXES]
    return draft


class ClaudeCodeSummarizer:
    name: Literal["claude-code"] = "claude-code"

    def __init__(self, model: str, *, timeout: float = MIN_TIMEOUT, sdk: Any | None = None) -> None:
        self.model = model
        self._timeout = max(timeout, MIN_TIMEOUT) if sdk is None else timeout
        self._sdk = sdk  # tests inject a fake with the same names as claude_agent_sdk

    def options(self, sdk: Any, cwd: str) -> Any:
        return sdk.ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT + JSON_INSTRUCTIONS,
            model=self.model,
            tools=[],
            allowed_tools=[],
            max_turns=1,
            setting_sources=[],
            cwd=cwd,
            extra_args=dict(ISOLATION_FLAGS),
        )

    async def summarize(self, payload: BriefInput) -> Draft:
        sdk = self._sdk or _import_sdk()
        prompt = "Agent posture:\n" + payload.model_dump_json(indent=1)
        with tempfile.TemporaryDirectory(prefix="wazuh-brief-") as cwd:
            options = self.options(sdk, cwd)
            try:
                text = await asyncio.wait_for(self._run(sdk, prompt, options), self._timeout)
            except TimeoutError as exc:
                raise SummarizerError(
                    f"Claude Code call timed out after {self._timeout:.0f}s"
                ) from exc
            except sdk.CLINotFoundError as exc:
                raise SummarizerError("Claude Code CLI not found") from exc
            except sdk.ProcessError as exc:  # includes ResultError
                detail = getattr(exc, "subtype", None) or f"exit code {exc.exit_code}"
                raise SummarizerError(f"Claude Code process failed ({detail}): {exc}") from exc
            except sdk.ClaudeSDKError as exc:
                raise SummarizerError(f"Claude Agent SDK error: {exc}") from exc
        return parse_draft(text)

    async def _run(self, sdk: Any, prompt: str, options: Any) -> str | None:
        result: Any = None
        async for message in sdk.query(prompt=prompt, options=options):
            if isinstance(message, sdk.AssistantMessage) and message.model:
                self.model = message.model  # report the model that actually answered
            elif isinstance(message, sdk.ResultMessage):
                result = message
        if result is None:
            raise SummarizerError("Claude Code ended without a result")
        if result.is_error:
            reason = (result.result or ", ".join(result.errors or []) or result.subtype)[:200]
            raise SummarizerError(f"Claude Code returned an error ({result.subtype}): {reason}")
        return result.result
