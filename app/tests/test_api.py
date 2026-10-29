"""Endpoint tests: FastAPI TestClient, Wazuh mocked with respx, no API key."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import BASE_URL, load, route_docs_agent_002, route_lab_agent_001
from tests.test_llm import GOOD_OUTPUT, FakeMessages, claude_with, fake_response
from wazuh_brief.config import Settings
from wazuh_brief.main import create_app
from wazuh_brief.wazuh_client import WazuhClient


def make_client(clock, claude=None) -> TestClient:
    settings = Settings(_env_file=None, wazuh_api_url=BASE_URL, anthropic_api_key=None)
    wazuh = WazuhClient(BASE_URL, "user", "pass", max_retries=1, backoff_base=0, clock=clock)
    return TestClient(create_app(settings=settings, wazuh=wazuh, claude=claude))


@pytest.fixture
def api(clock, wazuh_mock):
    with make_client(clock) as client:
        yield client


def test_healthz_does_not_call_wazuh(api, wazuh_mock):
    assert api.get("/healthz").json() == {"status": "ok"}
    assert wazuh_mock.calls.call_count == 0


def test_readyz_ok(api, wazuh_mock):
    wazuh_mock.get("/manager/info").respond(200, json=load("live_manager_info.json"))

    assert api.get("/readyz").json() == {"status": "ready", "wazuh": "ok"}


def test_readyz_503_when_wazuh_down(api, wazuh_mock):
    wazuh_mock.get("/manager/info").mock(side_effect=httpx.ConnectError("refused"))

    response = api.get("/readyz")

    assert response.status_code == 503
    assert response.json()["error"] == "wazuh_unavailable"


def test_agents_hides_the_manager(api, wazuh_mock):
    wazuh_mock.get("/agents").respond(200, json=load("live_agents.json"))

    assert [a["id"] for a in api.get("/agents").json()] == ["001"]
    assert [a["id"] for a in api.get("/agents?include_manager=true").json()] == ["000", "001"]


def test_brief_with_sca_data(api, wazuh_mock):
    route_docs_agent_002(wazuh_mock)

    body = api.get("/agents/002/brief").json()

    assert body["source"] == "mock"
    assert body["fallback_reason"] == "ANTHROPIC_API_KEY is not set"
    assert body["stale"] is False
    assert [f["rank"] for f in body["fixes"]] == [1, 2, 3, 4, 5]
    assert body["fixes"][0]["title"].endswith("/etc/sudoers.d/90-lab")
    cov = body["coverage"]
    assert cov["confidence"] == "high"
    assert (cov["sca_policies"], cov["sca_failed_checks_total"]) == (1, 87)
    assert cov["sca_failed_checks_considered"] == 9


def test_brief_without_sca_explains_the_gap(api, wazuh_mock):
    route_lab_agent_001(wazuh_mock)

    body = api.get("/agents/001/brief").json()

    assert body["agent"]["os"] == "Ubuntu 26.04.1 LTS"
    assert body["source"] == "mock"
    assert body["coverage"]["confidence"] == "low"
    assert body["coverage"]["sca_policies"] == 0
    assert "No SCA policy applies to Ubuntu 26.04.1 LTS" in body["coverage"]["gaps"][0]
    assert "No SCA policy applies" in body["coverage"]["note"]
    assert body["fixes"][0]["category"] == "coverage"


def test_brief_503_when_wazuh_down_and_nothing_cached(api, wazuh_mock):
    wazuh_mock.get("/agents").mock(side_effect=httpx.ConnectError("refused"))

    response = api.get("/agents/001/brief")

    assert response.status_code == 503
    assert response.json() == {
        "error": "wazuh_unavailable",
        "detail": "The Wazuh server API is unreachable: Wazuh API unreachable after 2 attempts "
        "(ConnectError: refused)",
    }


def test_brief_served_stale_from_cache_when_wazuh_down(api, wazuh_mock):
    route_lab_agent_001(wazuh_mock)
    first = api.get("/agents/001/brief").json()

    wazuh_mock.get("/agents", params={"agents_list": "001"}).mock(
        side_effect=httpx.ConnectError("refused")
    )
    response = api.get("/agents/001/brief")

    body = response.json()
    assert response.status_code == 200
    assert body["stale"] is True
    assert "unreachable" in body["stale_reason"]
    assert body["fixes"] == first["fixes"]
    assert body["generated_at"] == first["generated_at"]


def test_brief_404_for_unknown_agent(api, wazuh_mock):
    wazuh_mock.get("/agents").respond(200, json=load("live_agent_999_not_found.json"))

    response = api.get("/agents/999/brief")

    assert response.status_code == 404
    assert response.json()["error"] == "agent_not_found"


def test_brief_rejects_malformed_agent_id(api):
    assert api.get("/agents/..%2Fmanager/brief").status_code in (404, 422)
    assert api.get("/agents/abc/brief").status_code == 422


def test_brief_502_on_bad_wazuh_credentials(api, wazuh_mock):
    wazuh_mock.post("/security/user/authenticate").respond(401)

    response = api.get("/agents/001/brief")

    assert response.status_code == 502
    assert response.json()["error"] == "wazuh_auth_failed"


def test_brief_from_claude(clock, wazuh_mock):
    route_docs_agent_002(wazuh_mock)
    claude = claude_with(FakeMessages(result=fake_response(json.dumps(GOOD_OUTPUT))))

    with make_client(clock, claude=claude) as api:
        body = api.get("/agents/002/brief").json()

    assert body["source"] == "claude"
    assert body["model"] == "claude-sonnet-5-5"
    assert body["fixes"][0]["title"] == "Disable SSH root login"
    assert body["coverage"]["note"] == "Based on 9 of 87 failed checks."


def test_index_page(api):
    response = api.get("/")

    assert response.status_code == 200
    assert "Agent Hardening Brief" in response.text
