import httpx
import pytest

from tests.conftest import fake_jwt, load
from wazuh_brief.wazuh_client import (
    WazuhAPIError,
    WazuhAuthError,
    WazuhNotFound,
    WazuhUnavailable,
)

pytestmark = pytest.mark.anyio


async def test_list_agents_parses_live_fixture(client, wazuh_mock):
    wazuh_mock.get("/agents").respond(200, json=load("live_agents.json"))

    agents = await client.list_agents()

    assert [a.id for a in agents] == ["000", "001"]
    assert agents[0].is_manager
    assert agents[1].name == "ubuntu-lab"
    assert agents[1].os_label == "Ubuntu 26.04.1 LTS"


async def test_login_sends_basic_auth_and_token_is_reused(client, wazuh_mock):
    wazuh_mock.get("/agents").respond(200, json=load("live_agents.json"))

    await client.list_agents()
    await client.list_agents()

    login = wazuh_mock.routes[0]
    assert login.call_count == 1
    assert login.calls[0].request.headers["Authorization"].startswith("Basic ")
    data_call = wazuh_mock.calls[-1].request
    assert data_call.headers["Authorization"].startswith("Bearer ")


async def test_token_is_refreshed_when_it_expires(client, wazuh_mock, clock):
    wazuh_mock.get("/agents").respond(200, json=load("live_agents.json"))

    await client.list_agents()
    clock.now += 900  # past exp
    await client.list_agents()

    assert wazuh_mock.routes[0].call_count == 2


async def test_401_triggers_one_relogin_then_succeeds(client, wazuh_mock):
    wazuh_mock.get("/agents").mock(
        side_effect=[
            httpx.Response(401, json={"title": "Unauthorized", "detail": "Invalid token"}),
            httpx.Response(200, json=load("live_agents.json")),
        ]
    )

    agents = await client.list_agents()

    assert len(agents) == 2
    assert wazuh_mock.routes[0].call_count == 2


async def test_persistent_401_raises_auth_error(client, wazuh_mock):
    wazuh_mock.get("/agents").respond(401, json={"title": "Unauthorized"})

    with pytest.raises(WazuhAuthError):
        await client.list_agents()


async def test_bad_credentials_raise_auth_error(client, wazuh_mock):
    wazuh_mock.post("/security/user/authenticate").respond(401, json={"title": "Unauthorized"})

    with pytest.raises(WazuhAuthError):
        await client.list_agents()


async def test_unknown_agent_is_not_found(client, wazuh_mock):
    wazuh_mock.get("/agents").respond(200, json=load("live_agent_999_not_found.json"))

    with pytest.raises(WazuhNotFound):
        await client.get_agent("999")


async def test_5xx_is_retried_then_succeeds(client, wazuh_mock):
    route = wazuh_mock.get("/agents").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=load("live_agents.json"))]
    )

    await client.list_agents()

    assert route.call_count == 2


async def test_connection_errors_exhaust_retries(client, wazuh_mock):
    route = wazuh_mock.get("/agents").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(WazuhUnavailable, match="3 attempts"):
        await client.list_agents()

    assert route.call_count == 3


async def test_login_unreachable_is_unavailable(client, wazuh_mock):
    wazuh_mock.post("/security/user/authenticate").mock(side_effect=httpx.ConnectTimeout("slow"))

    with pytest.raises(WazuhUnavailable):
        await client.ping()


async def test_400_is_api_error(client, wazuh_mock):
    wazuh_mock.get("/agents").respond(400, json={"title": "Bad Request", "detail": "bad select"})

    with pytest.raises(WazuhAPIError, match="bad select"):
        await client.list_agents()


async def test_sca_empty_for_lab_agent(client, wazuh_mock):
    wazuh_mock.get("/sca/001").respond(200, json=load("live_sca_001_empty.json"))

    assert await client.sca_policies("001") == []


async def test_sca_policies_and_failed_checks(client, wazuh_mock):
    wazuh_mock.get("/sca/002").respond(200, json=load("docs_sca_002.json"))
    checks_route = wazuh_mock.get("/sca/002/checks/cis_ubuntu24-04").respond(
        200, json=load("docs_sca_checks_002_failed.json")
    )

    policies = await client.sca_policies("002")
    checks, total = await client.sca_failed_checks("002", "cis_ubuntu24-04")

    assert policies[0].policy_id == "cis_ubuntu24-04"
    assert (policies[0].passed, policies[0].failed, policies[0].score) == (56, 87, 39)
    assert total == 87
    assert len(checks) == 9
    assert all(c.result == "failed" for c in checks)
    assert checks_route.calls[0].request.url.params["result"] == "failed"
    root_login = next(c for c in checks if c.id == 35080)
    assert root_login.compliance_values("cis") == ["5.1.20"]


async def test_sca_configured_policies(client, wazuh_mock):
    wazuh_mock.get("/agents/001/config/wmodules/wmodules").respond(
        200, json=load("live_wmodules_001.json")
    )

    assert await client.sca_configured_policies("001") == [
        "/var/ossec/ruleset/sca/cis_ubuntu22-04.yml"
    ]


async def test_sca_configured_policies_unknown_when_agent_unreachable(client, wazuh_mock):
    wazuh_mock.get("/agents/001/config/wmodules/wmodules").respond(
        400, json={"title": "Bad Request", "detail": "Agent is not active"}
    )

    assert await client.sca_configured_policies("001") is None


async def test_syscheck_sorted_by_mtime(client, wazuh_mock):
    route = wazuh_mock.get("/syscheck/001").respond(200, json=load("live_syscheck_001.json"))

    entries, total = await client.syscheck("001", limit=8)

    assert route.calls[0].request.url.params["sort"] == "-mtime"
    assert len(entries) == 8
    assert total == 1475
    assert entries[0].file.startswith("/")


async def test_listening_ports(client, wazuh_mock):
    wazuh_mock.get("/syscollector/001/ports").respond(200, json=load("live_ports_001.json"))

    ports = await client.listening_ports("001")

    assert {(p.protocol, p.local.port) for p in ports} == {("tcp", 22), ("tcp6", 22)}


def test_fake_jwt_is_not_a_real_token():
    assert fake_jwt(1).endswith(".sig")
