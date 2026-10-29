"""Dev-only Claude Code summarizer, tested with a fake Agent SDK. No login, no CLI, no key."""

import asyncio
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from tests.conftest import route_docs_agent_002
from tests.test_llm import GOOD_OUTPUT
from wazuh_brief.llm import OUTPUT_SCHEMA, SYSTEM_PROMPT, MockSummarizer, summarize
from wazuh_brief.llm_claude_code import ClaudeCodeSummarizer, parse_draft
from wazuh_brief.posture import build_input, collect_posture

pytestmark = pytest.mark.anyio


class ClaudeSDKError(Exception):
    pass


class CLIConnectionError(ClaudeSDKError):
    pass


class CLINotFoundError(CLIConnectionError):
    pass


class ProcessError(ClaudeSDKError):
    def __init__(self, message: str, exit_code: int | None = None, stderr: str | None = None):
        super().__init__(message)
        self.exit_code, self.stderr = exit_code, stderr


@dataclass
class ClaudeAgentOptions:
    system_prompt: Any = None
    model: str | None = None
    tools: Any = None
    allowed_tools: list = field(default_factory=list)
    max_turns: int | None = None
    setting_sources: Any = None
    cwd: Any = None
    extra_args: dict = field(default_factory=dict)


@dataclass
class AssistantMessage:
    content: list
    model: str


@dataclass
class ResultMessage:
    subtype: str
    is_error: bool
    result: str | None = None
    errors: list | None = None


def fake_sdk(messages=None, exc=None, delay=0.0):
    calls: list[dict] = []

    async def query(*, prompt, options=None, transport=None):
        calls.append({"prompt": prompt, "options": options})
        if delay:
            await asyncio.sleep(delay)
        if exc:
            raise exc
        for m in messages or []:
            yield m

    return SimpleNamespace(
        query=query,
        calls=calls,
        ClaudeAgentOptions=ClaudeAgentOptions,
        AssistantMessage=AssistantMessage,
        ResultMessage=ResultMessage,
        ClaudeSDKError=ClaudeSDKError,
        CLINotFoundError=CLINotFoundError,
        ProcessError=ProcessError,
    )


def ok_messages(text: str) -> list:
    return [
        AssistantMessage(content=[], model="claude-sonnet-5-5"),
        ResultMessage(subtype="success", is_error=False, result=text),
    ]


@pytest.fixture
async def payload(client, wazuh_mock):
    route_docs_agent_002(wazuh_mock)
    return build_input(await collect_posture(client, "002"))


async def test_happy_path_is_reported_as_claude_code(payload):
    sdk = fake_sdk(ok_messages(json.dumps(GOOD_OUTPUT)))
    summarizer = ClaudeCodeSummarizer("claude-sonnet-5-5", sdk=sdk)

    result = await summarize(payload, summarizer, MockSummarizer())

    assert (result.source, result.model, result.fallback_reason) == (
        "claude-code",
        "claude-sonnet-5-5",
        None,
    )
    assert result.draft.fixes[0].title == "Disable SSH root login"


async def test_run_is_isolated_single_turn_and_tool_free(payload):
    sdk = fake_sdk(ok_messages(json.dumps(GOOD_OUTPUT)))

    await ClaudeCodeSummarizer("claude-sonnet-5-5", sdk=sdk).summarize(payload)

    options = sdk.calls[0]["options"]
    assert options.tools == []
    assert options.allowed_tools == []
    assert options.max_turns == 1
    assert options.setting_sources == []
    assert "strict-mcp-config" in options.extra_args
    assert "no-session-persistence" in options.extra_args
    assert options.system_prompt.startswith(SYSTEM_PROMPT)
    assert json.dumps(OUTPUT_SCHEMA, indent=1) in options.system_prompt
    assert sdk.calls[0]["prompt"] == "Agent posture:\n" + payload.model_dump_json(indent=1)


def test_parse_draft_accepts_a_code_fence():
    fenced = "```json\n" + json.dumps(GOOD_OUTPUT) + "\n```"
    assert parse_draft(fenced).summary == "Fix SSH first."


@pytest.mark.parametrize(
    ("sdk", "reason"),
    [
        (fake_sdk(ok_messages("Here is your brief: not JSON")), "not JSON"),
        (fake_sdk(ok_messages('{"summary": "x"}')), "did not match the schema"),
        (fake_sdk(ok_messages(json.dumps({**GOOD_OUTPUT, "fixes": []}))), "no fixes"),
        (
            fake_sdk([ResultMessage(subtype="success", is_error=True, result="Not logged in")]),
            "Not logged in",
        ),
        (fake_sdk([]), "without a result"),
        (fake_sdk(exc=CLINotFoundError("Claude Code not found")), "CLI not found"),
        (fake_sdk(exc=ProcessError("boom", exit_code=1)), "exit code 1"),
        (fake_sdk(exc=ClaudeSDKError("odd")), "Claude Agent SDK error"),
        (fake_sdk(exc=RuntimeError("boom")), "unexpected error"),
    ],
)
async def test_failures_fall_back_to_mock(payload, sdk, reason):
    result = await summarize(
        payload, ClaudeCodeSummarizer("claude-sonnet-5-5", sdk=sdk), MockSummarizer()
    )

    assert result.source == "mock"
    assert result.fallback_reason.startswith("claude-code: ")
    assert reason in result.fallback_reason
    assert result.draft == MockSummarizer().build(payload)


async def test_timeout_falls_back_to_mock(payload):
    sdk = fake_sdk(ok_messages(json.dumps(GOOD_OUTPUT)), delay=1.0)
    summarizer = ClaudeCodeSummarizer("claude-sonnet-5-5", sdk=sdk, timeout=0.05)

    result = await summarize(payload, summarizer, MockSummarizer())

    assert result.source == "mock"
    assert "timed out" in result.fallback_reason


async def test_sdk_not_installed_falls_back_to_mock(payload, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_sdk(name, *args, **kwargs):
        if name == "claude_agent_sdk":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sdk)

    result = await summarize(payload, ClaudeCodeSummarizer("m"), MockSummarizer())

    assert result.source == "mock"
    assert "uv sync --extra claude-code" in result.fallback_reason
