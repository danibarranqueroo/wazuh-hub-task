"""Shared test helpers. Nothing here talks to a real Wazuh or to the Anthropic API."""

import base64
import json
from pathlib import Path
from typing import Any

import pytest
import respx

from wazuh_brief.wazuh_client import WazuhClient

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://wazuh.test:55000"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def fake_jwt(exp: float) -> str:
    """An unsigned JWT-shaped string with the given `exp`. Never a real token."""

    def b64(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{b64({'alg': 'none'})}.{b64({'exp': exp, 'sub': 'test'})}.sig"


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def wazuh_mock(clock: FakeClock):
    """respx router with a working login route. Tests add the data routes they need."""
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        router.post("/security/user/authenticate").respond(200, text=fake_jwt(clock.now + 900))
        yield router


@pytest.fixture
async def client(clock: FakeClock, wazuh_mock):
    c = WazuhClient(BASE_URL, "user", "pass", max_retries=2, backoff_base=0, clock=clock)
    yield c
    await c.aclose()


def route_lab_agent_001(router: respx.MockRouter) -> None:
    """Routes for the real lab agent 001 (Ubuntu 26.04, no SCA results)."""
    router.get("/agents", params={"agents_list": "001"}).respond(
        200, json=load("live_agent_001.json")
    )
    router.get("/sca/001").respond(200, json=load("live_sca_001_empty.json"))
    router.get("/agents/001/config/wmodules/wmodules").respond(
        200, json=load("live_wmodules_001.json")
    )
    router.get("/syscheck/001").respond(200, json=load("live_syscheck_001.json"))
    router.get("/syscollector/001/ports").respond(200, json=load("live_ports_001.json"))


def route_docs_agent_002(router: respx.MockRouter) -> None:
    """Routes for the synthetic agent 002 (Ubuntu 24.04, with SCA results from the API docs)."""
    router.get("/agents", params={"agents_list": "002"}).respond(
        200, json=load("docs_agent_002.json")
    )
    router.get("/sca/002").respond(200, json=load("docs_sca_002.json"))
    router.get("/sca/002/checks/cis_ubuntu24-04").respond(
        200, json=load("docs_sca_checks_002_failed.json")
    )
    router.get("/agents/002/config/wmodules/wmodules").respond(
        200, json=load("docs_wmodules_002.json")
    )
    router.get("/syscheck/002").respond(200, json=load("docs_syscheck_002.json"))
    router.get("/syscollector/002/ports").respond(200, json=load("docs_ports_002.json"))
