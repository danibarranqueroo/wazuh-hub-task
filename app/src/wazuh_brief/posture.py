"""Collect one agent's posture from Wazuh and turn it into summarizer input.

Three jobs:

1. `collect_posture`: the Wazuh calls for one brief.
2. `coverage_gaps` and `confidence`: what the data can and cannot tell, computed by rule so that the
   coverage note does not depend on the model.
3. `build_input`: the small, ranked payload a summarizer sees. Failed SCA checks are pre-ranked by
   `check_weight` so that, on a host with hundreds of failures, the most relevant ones are sent.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re

from .models import (
    AgentPosture,
    BriefInput,
    Confidence,
    FIMEntry,
    InputAgent,
    InputCheck,
    InputFile,
    InputPolicy,
    InputPort,
    Port,
    SCACheck,
)
from .wazuh_client import WazuhClient

FIM_LIMIT = 20
CHECKS_PER_POLICY = 500
CHECKS_SENT = 60
TEXT_LIMIT = 500

SENSITIVE_PATHS = (
    "/etc/ssh/",
    "/etc/sudoers",
    "/etc/passwd",
    "/etc/shadow",
    "/etc/group",
    "/etc/gshadow",
    "/etc/pam.d/",
    "/etc/cron",
    "/etc/crontab",
    "/etc/systemd/system/",
    "/etc/ld.so.preload",
    "/root/.ssh/",
)

# Keyword weights for ranking failed SCA checks. Higher means "fix sooner". Matched against the
# lower-cased title. The idea: remote access, authentication and network exposure first, then
# privilege and audit, then local filesystem tweaks.
CHECK_KEYWORDS: tuple[tuple[str, int], ...] = (
    ("ssh", 30),
    ("root", 10),
    ("password", 20),
    ("authentication", 15),
    ("firewall", 25),
    ("ufw", 25),
    ("nftables", 25),
    ("iptables", 25),
    ("shadow", 20),
    ("/etc/passwd", 15),
    ("sudo", 15),
    ("auditd", 15),
    ("audit", 10),
    ("aide", 10),
    ("update", 15),
    ("gpg", 15),
    ("permissions", 5),
    ("filesystem", 2),
)


# --- collection ---------------------------------------------------------------------------------


async def collect_posture(client: WazuhClient, agent_id: str) -> AgentPosture:
    """Read everything the brief needs. Raises WazuhError subclasses unchanged."""
    agent = await client.get_agent(agent_id)
    policies, configured, (fim, fim_total), ports = await asyncio.gather(
        client.sca_policies(agent_id),
        client.sca_configured_policies(agent_id),
        client.syscheck(agent_id, limit=FIM_LIMIT),
        client.listening_ports(agent_id),
    )
    failed: list[SCACheck] = []
    failed_total = 0
    for policy in policies:
        if policy.failed <= 0:
            continue
        checks, total = await client.sca_failed_checks(
            agent_id, policy.policy_id, limit=CHECKS_PER_POLICY
        )
        failed.extend(checks)
        failed_total += total
    return AgentPosture(
        agent=agent,
        sca_policies=policies,
        sca_failed_checks=failed,
        sca_failed_total=failed_total,
        sca_configured_policies=configured,
        fim_entries=fim,
        fim_total=fim_total,
        listening_ports=ports,
    )


# --- rules shared by the input builder and the mock summarizer -----------------------------------


def check_weight(check: SCACheck | InputCheck, exposed_ssh: bool = False) -> int:
    title = check.title.lower()
    weight = sum(w for keyword, w in CHECK_KEYWORDS if keyword in title)
    mitre = (
        check.mitre_techniques
        if isinstance(check, InputCheck)
        else check.compliance_values("mitre_techniques")
    )
    if mitre:
        weight += 10
    if exposed_ssh and "ssh" in title:
        weight += 15
    return weight


def is_sensitive(path: str) -> bool:
    return path.startswith(SENSITIVE_PATHS)


def is_world_writable(perm: str | None) -> bool:
    """True for symbolic perms like 'rw-rw-rw-'.

    Wazuh reports symlinks as 'rwxrwxrwx' (seen in the lab for systemd unit links), so that exact
    value is treated as a link, not a finding.
    """
    if not perm or len(perm) != 9 or perm == "rwxrwxrwx":
        return False
    return perm[7] == "w"


def is_exposed(port: Port | InputPort) -> bool:
    address = port.address if isinstance(port, InputPort) else (port.local.ip or "")
    try:
        return not ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def exposes_ssh(ports: list[InputPort]) -> bool:
    return any(p.port == 22 and is_exposed(p) for p in ports)


def expected_policy_id(posture: AgentPosture) -> str | None:
    """CIS policy ID Wazuh would use for this OS, e.g. 'cis_ubuntu26-04'. None if unknown."""
    os = posture.agent.os
    if os is None or not os.platform or not os.major:
        return None
    suffix = f"{os.major}-{os.minor}" if os.minor else os.major
    return f"cis_{os.platform}{suffix}"


def _policy_stem(path: str) -> str:
    return re.sub(r"\.ya?ml$", "", path.rsplit("/", 1)[-1])


# --- coverage -----------------------------------------------------------------------------------


def coverage_gaps(posture: AgentPosture) -> list[str]:
    agent = posture.agent
    gaps: list[str] = []

    if not posture.sca_policies:
        configured = posture.sca_configured_policies
        expected = expected_policy_id(posture)
        if configured:
            stems = ", ".join(_policy_stem(p) for p in configured)
            mismatch = expected is not None and all(_policy_stem(p) != expected for p in configured)
            if mismatch:
                gaps.append(
                    f"No SCA policy applies to {agent.os_label}. The agent is configured with "
                    f"{stems}, which targets another OS version, so the agent skips it and "
                    f"reports no results. No {expected} policy is configured, which usually means "
                    "this Wazuh release ships none for this OS version. "
                    "Configuration hardening (CIS) is not assessed on this agent at all: a clean "
                    "brief here means 'not checked', not 'compliant'."
                )
            else:
                gaps.append(
                    f"SCA is configured ({stems}) but has returned no results yet. The first scan "
                    "may still be pending, or the policy requirements do not match this host."
                )
        elif configured == []:
            gaps.append("SCA is not enabled on this agent, so CIS hardening is not assessed.")
        else:
            gaps.append(
                "SCA returned no results and the agent's SCA configuration could not be read "
                "(the agent may be disconnected). CIS hardening is not assessed."
            )

    considered = min(len(posture.sca_failed_checks), CHECKS_SENT)
    if posture.sca_failed_total > considered:
        gaps.append(
            f"{posture.sca_failed_total} SCA checks failed; the {considered} highest-weighted "
            "were considered for ranking."
        )

    if posture.fim_entries and all(e.changes <= 1 for e in posture.fim_entries):
        gaps.append(
            "File integrity data is a baseline only: none of the most recently modified files "
            "has changed since FIM first indexed it."
        )
    elif not posture.fim_entries:
        gaps.append("FIM returned no entries for this agent.")

    if agent.status != "active":
        gaps.append(f"The agent is {agent.status}; the data is from its last report.")

    gaps.append(
        "Alerts and vulnerability detection are not included: the service reads the server API "
        "only, not the indexer."
    )
    return gaps


def confidence(posture: AgentPosture) -> Confidence:
    if not posture.sca_policies:
        return "low"
    if posture.agent.status != "active":
        return "medium"
    return "high"


# --- summarizer input ---------------------------------------------------------------------------


def _trim(text: str | None, limit: int = TEXT_LIMIT) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _input_file(entry: FIMEntry) -> InputFile:
    return InputFile(
        file=entry.file,
        perm=entry.perm,
        owner=entry.uname,
        changes=entry.changes,
        mtime=entry.mtime,
    )


def build_input(posture: AgentPosture) -> BriefInput:
    agent = posture.agent
    ports = [
        InputPort(
            protocol=p.protocol,
            address=p.local.ip or "",
            port=p.local.port or 0,
            process=p.process,
        )
        for p in posture.listening_ports
    ]
    exposed_ssh = exposes_ssh(ports)
    ranked = sorted(
        posture.sca_failed_checks,
        key=lambda c: (-check_weight(c, exposed_ssh), c.id),
    )[:CHECKS_SENT]
    return BriefInput(
        agent=InputAgent(
            name=agent.name,
            os=agent.os_label,
            status=agent.status,
            wazuh_version=agent.version,
        ),
        sca_applicable=bool(posture.sca_policies),
        sca_policies=[
            InputPolicy(
                policy_id=p.policy_id, name=p.name, score=p.score, passed=p.passed, failed=p.failed
            )
            for p in posture.sca_policies
        ],
        sca_configured_policies=(
            [_policy_stem(p) for p in posture.sca_configured_policies]
            if posture.sca_configured_policies is not None
            else None
        ),
        sca_failed_checks_total=posture.sca_failed_total,
        sca_failed_checks=[
            InputCheck(
                id=c.id,
                policy_id=c.policy_id,
                title=c.title,
                rationale=_trim(c.rationale),
                remediation=_trim(c.remediation),
                cis=c.compliance_values("cis"),
                mitre_techniques=[
                    t for v in c.compliance_values("mitre_techniques") for t in v.split(",")
                ],
            )
            for c in ranked
        ],
        fim_entries_total=posture.fim_total,
        fim_recent=[_input_file(e) for e in posture.fim_entries],
        listening_ports=ports,
        coverage_gaps=coverage_gaps(posture),
    )
