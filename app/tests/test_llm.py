"""Summarizer tests. The Anthropic client is replaced with a fake; no API key is needed."""

import asyncio
import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from tests.conftest import route_docs_agent_002, route_lab_agent_001
from wazuh_brief.llm import (
    FALLBACK_BETA,
    ClaudeSummarizer,
    MockSummarizer,
    summarize,
)
from wazuh_brief.posture import build_input, collect_posture

pytestmark = pytest.mark.anyio

GOOD_OUTPUT = {
    "summary": "Fix SSH first.",
    "fixes": [
        {
            "title": "Disable SSH root login",
            "category": "sca",
            "why": "Root brute force.",
            "remediation": "PermitRootLogin no",
            "evidence": ["SCA check 35080 failed"],
            "references": ["CIS 5.1.20"],
        }
    ],
    "coverage_note": "Based on 9 of 87 failed checks.",
}


class FakeMessages:
    def __init__(self, result=None, exc=None, delay=0.0):
        self.result, self.exc, self.delay = result, exc, delay
        self.requests: list[dict] = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.result


def fake_response(text: str | None, stop_reason: str = "end_turn"):
    content = [SimpleNamespace(type="thinking", thinking="")]
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(stop_reason=stop_reason, content=content)


def claude_with(messages: FakeMessages, timeout: float = 5.0) -> ClaudeSummarizer:
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return ClaudeSummarizer("test-key", "claude-sonnet-5-5", timeout=timeout, client=client)


@pytest.fixture
async def payload_002(client, wazuh_mock):
    route_docs_agent_002(wazuh_mock)
    return build_input(await collect_posture(client, "002"))


@pytest.fixture
async def payload_001(client, wazuh_mock):
    route_lab_agent_001(wazuh_mock)
    return build_input(await collect_posture(client, "001"))


# --- mock ---------------------------------------------------------------------------------------


async def test_mock_with_sca_ranks_exposed_ssh_and_writable_sudoers_first(payload_002):
    draft = MockSummarizer().build(payload_002)

    titles = [f.title for f in draft.fixes]
    assert len(titles) == 5
    assert titles[0] == "Remove world-write permission from /etc/sudoers.d/90-lab"
    assert any("PasswordAuthentication" in t or "PermitRootLogin" in t for t in titles[:3])
    # SSH is covered by SCA checks, so the generic SSH exposure item is dropped.
    assert not any(f.category == "exposure" and "SSH" in f.title for f in draft.fixes)
    assert "87 SCA checks" in draft.summary
    assert all(f.remediation for f in draft.fixes)


async def test_mock_without_sca_leads_with_the_coverage_gap(payload_001):
    draft = MockSummarizer().build(payload_001)

    assert draft.fixes[0].category == "coverage"
    assert "Ubuntu 26.04.1 LTS" in draft.fixes[0].title
    assert "cis_ubuntu22-04" in " ".join(draft.fixes[0].evidence)
    assert draft.fixes[1].title.startswith("Harden the SSH service")
    assert "no SCA results" in draft.summary
    assert "No SCA policy applies" in draft.coverage_note


async def test_mock_is_deterministic(payload_002):
    assert MockSummarizer().build(payload_002) == MockSummarizer().build(payload_002)


# --- Claude request shape -----------------------------------------------------------------------


async def test_claude_request_is_bounded_and_structured(payload_002):
    messages = FakeMessages(result=fake_response(json.dumps(GOOD_OUTPUT)))

    draft = await claude_with(messages).summarize(payload_002)

    request = messages.requests[0]
    assert draft.fixes[0].title == "Disable SSH root login"
    assert request["model"] == "claude-sonnet-5-5"
    assert request["max_tokens"] <= 16000
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["betas"] == [FALLBACK_BETA]
    assert request["fallbacks"] == "default"
    sent = request["messages"][0]["content"]
    assert "sha256" not in sent and "test-key" not in sent


# --- fallback paths -----------------------------------------------------------------------------


async def test_no_api_key_uses_mock(payload_001):
    result = await summarize(payload_001, None, MockSummarizer())

    assert result.source == "mock"
    assert result.fallback_reason == "ANTHROPIC_API_KEY is not set"


async def test_claude_success_is_reported_as_claude(payload_002):
    messages = FakeMessages(result=fake_response(json.dumps(GOOD_OUTPUT)))

    result = await summarize(payload_002, claude_with(messages), MockSummarizer())

    assert (result.source, result.model, result.fallback_reason) == (
        "claude",
        "claude-sonnet-5-5",
        None,
    )


REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    ("messages", "reason"),
    [
        (FakeMessages(exc=anthropic.APITimeoutError(request=REQUEST)), "timed out"),
        (FakeMessages(exc=anthropic.APIConnectionError(request=REQUEST)), "could not reach"),
        (
            FakeMessages(
                exc=anthropic.AuthenticationError(
                    "bad key", response=httpx2.Response(401, request=REQUEST), body=None
                )
            ),
            "rejected",
        ),
        (FakeMessages(result=fake_response(None, "refusal")), "declined"),
        (FakeMessages(result=fake_response("{}", "max_tokens")), "max_tokens"),
        (FakeMessages(result=fake_response("not json")), "schema"),
        (FakeMessages(result=fake_response(json.dumps({**GOOD_OUTPUT, "fixes": []}))), "no fixes"),
        (FakeMessages(exc=RuntimeError("boom")), "unexpected error"),
    ],
)
async def test_model_failures_fall_back_to_mock(payload_002, messages, reason):
    result = await summarize(payload_002, claude_with(messages), MockSummarizer())

    assert result.source == "mock"
    assert reason in result.fallback_reason
    assert result.draft == MockSummarizer().build(payload_002)


async def test_hung_model_call_times_out_to_mock(payload_002, monkeypatch):
    messages = FakeMessages(result=fake_response(json.dumps(GOOD_OUTPUT)), delay=1.0)
    summarizer = claude_with(messages, timeout=0.01)
    summarizer._timeout = -4.9  # wait_for bound = timeout + 5 = 0.1s

    result = await summarize(payload_002, summarizer, MockSummarizer())

    assert result.source == "mock"
    assert "timed out" in result.fallback_reason
