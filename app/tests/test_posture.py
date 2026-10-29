import pytest

from tests.conftest import route_docs_agent_002, route_lab_agent_001
from wazuh_brief.models import InputPort
from wazuh_brief.posture import (
    build_input,
    collect_posture,
    confidence,
    coverage_gaps,
    expected_policy_id,
    is_world_writable,
)

pytestmark = pytest.mark.anyio


async def test_lab_agent_without_sca_reports_the_coverage_gap(client, wazuh_mock):
    route_lab_agent_001(wazuh_mock)

    posture = await collect_posture(client, "001")
    gaps = coverage_gaps(posture)

    assert posture.sca_policies == []
    assert expected_policy_id(posture) == "cis_ubuntu26-04"
    assert confidence(posture) == "low"
    assert "No SCA policy applies to Ubuntu 26.04.1 LTS" in gaps[0]
    assert "cis_ubuntu22-04" in gaps[0]
    assert "not 'compliant'" in gaps[0]
    assert any("baseline only" in g for g in gaps)


async def test_agent_with_sca_collects_failed_checks(client, wazuh_mock):
    route_docs_agent_002(wazuh_mock)

    posture = await collect_posture(client, "002")
    payload = build_input(posture)

    assert confidence(posture) == "high"
    assert payload.sca_applicable
    assert payload.sca_failed_checks_total == 87
    assert len(payload.sca_failed_checks) == 9
    # SSH checks rank first because port 22 is exposed.
    assert "sshd" in payload.sca_failed_checks[0].title
    assert payload.sca_failed_checks[-1].title.startswith("Ensure mounting of cramfs")
    assert any("87 SCA checks failed" in g for g in payload.coverage_gaps)


async def test_model_input_has_no_hashes_ips_or_raw_fields(client, wazuh_mock):
    route_docs_agent_002(wazuh_mock)

    payload = build_input(await collect_posture(client, "002")).model_dump_json()

    assert "sha256" not in payload
    assert "192.168.139.40" not in payload  # agent IP
    assert "rules" not in payload
    assert "Bearer" not in payload


def test_unconfigured_sca_gap():
    from wazuh_brief.models import Agent, AgentPosture

    posture = AgentPosture(
        agent=Agent(id="003", name="x", status="disconnected"), sca_configured_policies=None
    )
    gaps = coverage_gaps(posture)
    assert "could not be read" in gaps[0]
    assert any("disconnected" in g for g in gaps)


@pytest.mark.parametrize(
    ("perm", "expected"),
    [
        ("rw-rw-rw-", True),
        ("rw-r--r--", False),
        ("rwxrwxrwx", False),
        (None, False),
        ("100644", False),
    ],
)
def test_world_writable(perm, expected):
    assert is_world_writable(perm) is expected


def test_loopback_is_not_exposed():
    from wazuh_brief.posture import is_exposed

    assert not is_exposed(InputPort(protocol="tcp", address="127.0.0.1", port=5432, process=None))
    assert is_exposed(InputPort(protocol="tcp6", address="::", port=22, process=None))
