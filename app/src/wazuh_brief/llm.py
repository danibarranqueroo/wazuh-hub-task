"""Summarizers: turn a `BriefInput` into a `Draft` brief.

- `ClaudeSummarizer` calls the Anthropic Messages API and asks for JSON that matches a schema.
- `MockSummarizer` ranks findings by fixed rules. It is deterministic and needs no network.
- `summarize` tries Claude when it is configured and falls back to the mock on any failure, and
  reports which one produced the result.

Both summarizers see exactly the same `BriefInput`, which holds no raw logs, hashes, IPs or
credentials (see `models.BriefInput`).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import anthropic
from pydantic import ValidationError

from .models import BriefInput, Draft, DraftFix, InputCheck
from .posture import check_weight, exposes_ssh, is_exposed, is_sensitive, is_world_writable

log = logging.getLogger(__name__)

MAX_FIXES = 5

# Models that accept server-side refusal fallbacks in the "default" form (claude-api skill,
# 2026-10). For other models the parameter is left out.
FALLBACK_CAPABLE_MODELS = {
    "claude-sonnet-5-5",
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-fable-5-1",
}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class Summarizer(Protocol):
    name: Literal["claude", "mock"]

    async def summarize(self, payload: BriefInput) -> Draft: ...


class SummarizerError(Exception):
    """The model call failed or returned something unusable."""


# --- mock ---------------------------------------------------------------------------------------


@dataclass
class _Candidate:
    """A possible fix and its rule score. Scale, highest first:

    150 SCA coverage missing | 120 world-writable sensitive file | ~50-110 failed SCA check (20 +
    keyword weights) | 70 changed sensitive file | 60 other world-writable file | 45 exposed SSH
    without SCA (25 with SCA) | 20 other exposed port.
    """

    score: int
    fix: DraftFix


def _sca_candidate(check: InputCheck, exposed_ssh: bool) -> _Candidate:
    references = [f"CIS {v}" for v in check.cis] + [f"MITRE {t}" for t in check.mitre_techniques]
    return _Candidate(
        score=20 + check_weight(check, exposed_ssh),
        fix=DraftFix(
            title=check.title.rstrip("."),
            category="sca",
            why=check.rationale or "Failed CIS check.",
            remediation=check.remediation or "See the CIS benchmark for this check.",
            evidence=[f"SCA check {check.id} failed in policy {check.policy_id}"],
            references=references,
        ),
    )


def _coverage_candidate(payload: BriefInput) -> _Candidate:
    configured = ", ".join(payload.sca_configured_policies or []) or "none"
    return _Candidate(
        score=150,
        fix=DraftFix(
            title=f"Restore configuration assessment (SCA) for {payload.agent.os}",
            category="coverage",
            why=(
                "Wazuh reports no SCA results for this agent, so no CIS hardening check runs on "
                "it. Every other item in this brief is drawn from file integrity and inventory "
                "data. Missing coverage looks the same as a clean host, which is the risk."
            ),
            remediation=(
                "Pick one: (1) run the workload on an OS release that has a bundled CIS policy "
                "(check /var/ossec/ruleset/sca/ on the agent); (2) copy the closest bundled "
                "policy, adjust its requirements block to this OS version, review the checks, and "
                "deploy it to the agent group through centralized configuration (agent.conf); "
                "(3) track Wazuh releases for a policy for this version. Then confirm with "
                "GET /sca/{agent_id} that results appear."
            ),
            evidence=[
                "GET /sca returned 0 policies",
                f"Configured SCA policies: {configured}",
            ],
            references=["Wazuh SCA documentation"],
        ),
    )


def _fim_candidates(payload: BriefInput) -> list[_Candidate]:
    out: list[_Candidate] = []
    for entry in payload.fim_recent:
        sensitive = is_sensitive(entry.file)
        if is_world_writable(entry.perm):
            out.append(
                _Candidate(
                    score=120 if sensitive else 60,
                    fix=DraftFix(
                        title=f"Remove world-write permission from {entry.file}",
                        category="fim",
                        why=(
                            "Any local user can modify this file."
                            + (
                                " It controls authentication or privileges, so this is a direct "
                                "path to root."
                                if sensitive
                                else ""
                            )
                        ),
                        remediation=(
                            f"Run: chmod o-w {entry.file}. Then find out how the permission "
                            "changed (package scripts, config management, a person) and fix that "
                            "source too."
                        ),
                        evidence=[f"FIM: {entry.file} perm {entry.perm}, owner {entry.owner}"],
                    ),
                )
            )
        elif sensitive and entry.changes > 1:
            out.append(
                _Candidate(
                    score=70,
                    fix=DraftFix(
                        title=f"Review recent changes to {entry.file}",
                        category="fim",
                        why=(
                            f"This file controls authentication, privileges or startup, and it has "
                            f"changed {entry.changes - 1} time(s) since FIM first indexed it. An "
                            "unreviewed change here can grant access or persistence."
                        ),
                        remediation=(
                            "Confirm each change was authorized (change ticket, config management "
                            "commit). Compare with the packaged version (dpkg --verify, or diff "
                            "against a known-good copy) and revert anything unexplained. Turn on "
                            "report_changes for this path in the FIM configuration to keep diffs."
                        ),
                        evidence=[
                            f"FIM: {entry.file} changes={entry.changes}, last mtime {entry.mtime}"
                        ],
                    ),
                )
            )
    return out


def _exposure_candidates(payload: BriefInput) -> list[_Candidate]:
    by_port: dict[int, list[str]] = {}
    process: dict[int, str | None] = {}
    for port in payload.listening_ports:
        if not is_exposed(port):
            continue
        by_port.setdefault(port.port, []).append(f"{port.protocol} {port.address}:{port.port}")
        process[port.port] = process.get(port.port) or port.process
    out: list[_Candidate] = []
    for number, sockets in sorted(by_port.items()):
        evidence = [f"Listening: {s} ({process[number] or 'unknown process'})" for s in sockets]
        if number == 22:
            out.append(
                _Candidate(
                    score=45 if not payload.sca_applicable else 25,
                    fix=DraftFix(
                        title="Harden the SSH service that listens on all interfaces",
                        category="exposure",
                        why=(
                            "SSH is the main remote entry point and the usual target of brute "
                            "force. It listens on every address, so anything that can route to the "
                            "host can try to log in."
                        ),
                        remediation=(
                            "In /etc/ssh/sshd_config set PermitRootLogin no, "
                            "PasswordAuthentication no (after every admin has a key) and "
                            "MaxAuthTries 4, then run systemctl reload ssh. Limit who can connect: "
                            "ufw allow from <admin-network> to any port 22 proto tcp, then "
                            "ufw enable."
                        ),
                        evidence=evidence,
                        references=["CIS Ubuntu 5.1 (SSH Server)"],
                    ),
                )
            )
        else:
            name = process[number] or "the service"
            out.append(
                _Candidate(
                    score=20,
                    fix=DraftFix(
                        title=f"Confirm {name} on port {number} must be reachable from the network",
                        category="exposure",
                        why="Every service reachable from the network adds attack surface.",
                        remediation=(
                            f"If {name} only serves local clients, bind it to 127.0.0.1. "
                            f"Otherwise restrict port {number} to the networks that need it with "
                            "a host firewall."
                        ),
                        evidence=evidence,
                    ),
                )
            )
    return out


class MockSummarizer:
    """Rule-based ranking. Deterministic: the same input always gives the same brief."""

    name: Literal["mock"] = "mock"

    async def summarize(self, payload: BriefInput) -> Draft:
        return self.build(payload)

    def build(self, payload: BriefInput) -> Draft:
        exposed_ssh = exposes_ssh(payload.listening_ports)
        candidates: list[_Candidate] = []
        if not payload.sca_applicable:
            candidates.append(_coverage_candidate(payload))
        candidates += [_sca_candidate(c, exposed_ssh) for c in payload.sca_failed_checks]
        candidates += _fim_candidates(payload)
        candidates += _exposure_candidates(payload)

        # Stable sort: equal scores keep insertion order (coverage, SCA, FIM, exposure).
        ranked = sorted(candidates, key=lambda c: -c.score)
        chosen: list[DraftFix] = []
        for candidate in ranked:
            if len(chosen) == MAX_FIXES:
                break
            fix = candidate.fix
            ssh_covered = any(f.category == "sca" and "ssh" in f.title.lower() for f in chosen)
            if fix.category == "exposure" and "SSH" in fix.title and ssh_covered:
                continue
            chosen.append(fix)

        return Draft(
            summary=self._summary(payload, chosen),
            fixes=chosen,
            coverage_note=" ".join(payload.coverage_gaps[:2]),
        )

    @staticmethod
    def _summary(payload: BriefInput, fixes: list[DraftFix]) -> str:
        agent = payload.agent
        head = fixes[0].title if fixes else "nothing stands out"
        if payload.sca_applicable:
            policies = ", ".join(
                f"{p.policy_id} (score {p.score}%)" if p.score is not None else p.policy_id
                for p in payload.sca_policies
            )
            return (
                f"{agent.name} ({agent.os}) fails {payload.sca_failed_checks_total} SCA checks in "
                f"{policies}. These {len(fixes)} fixes come first, ranked by remote exposure, "
                f"authentication and privilege impact. Start with: {head}."
            )
        return (
            f"{agent.name} ({agent.os}) has no SCA results, so CIS hardening is not assessed on "
            f"this host. This brief is built from file integrity and listening-port data only. "
            f"Start with: {head}."
        )


# --- Claude -------------------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a host-hardening advisor inside a Wazuh-based security service. You receive one agent's \
current posture as JSON: failed SCA (CIS benchmark) checks, recent file integrity (FIM) entries, \
listening ports, and coverage gaps computed by the service.

Write a short, prioritized hardening brief for the operator of this host. The question you answer \
is: "I have many failed checks; what do I fix first?"

Rules:
- Return at most 5 fixes, most important first. Rank by real-world risk: remote exposure and \
authentication weaknesses first, then privilege escalation and loss of audit trail, then local \
hygiene. Group closely related checks into one fix when one change resolves them.
- Use only facts from the input. Every fix must cite its evidence (check IDs, file paths, ports).
- "remediation" must be concrete: the file to edit, the setting, or the command.
- If sca_applicable is false, say plainly that CIS hardening is not assessed on this host, \
explain that this is a coverage gap rather than a clean result, and make restoring coverage one \
of the fixes.
- "coverage_note" states what the brief is based on and what it could not see, using the \
coverage_gaps input.
- Plain, factual English. No marketing tone.
"""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "fixes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "category": {"type": "string", "enum": ["sca", "fim", "exposure", "coverage"]},
                    "why": {"type": "string"},
                    "remediation": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "references": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "category", "why", "remediation", "evidence", "references"],
                "additionalProperties": False,
            },
        },
        "coverage_note": {"type": "string"},
    },
    "required": ["summary", "fixes", "coverage_note"],
    "additionalProperties": False,
}


class ClaudeSummarizer:
    name: Literal["claude"] = "claude"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        max_tokens: int = 6000,
        timeout: float = 45.0,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self._max_tokens = max_tokens
        self._timeout = timeout
        # max_retries=0: the caller falls back to the mock instead of waiting on retries.
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout, max_retries=0
        )

    def _request(self, payload: BriefInput) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": "Agent posture:\n" + payload.model_dump_json(indent=1),
                }
            ],
            "output_config": {
                "effort": "medium",
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
        }
        if self.model in FALLBACK_CAPABLE_MODELS:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        return request

    async def summarize(self, payload: BriefInput) -> Draft:
        request = self._request(payload)
        try:
            response = await asyncio.wait_for(
                self._client.beta.messages.create(**request), timeout=self._timeout + 5
            )
        except TimeoutError as exc:
            raise SummarizerError("model call timed out") from exc
        except anthropic.APITimeoutError as exc:
            raise SummarizerError("model call timed out") from exc
        except anthropic.RateLimitError as exc:
            raise SummarizerError("model rate limited (429)") from exc
        except anthropic.AuthenticationError as exc:
            raise SummarizerError("ANTHROPIC_API_KEY was rejected (401)") from exc
        except anthropic.BadRequestError as exc:
            raise SummarizerError(f"model rejected the request (400): {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise SummarizerError(f"model API error ({exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise SummarizerError("could not reach the model API") from exc

        if response.stop_reason == "refusal":
            raise SummarizerError("model declined the request")
        if response.stop_reason == "max_tokens":
            raise SummarizerError("model output hit max_tokens")
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), None)
        if not text:
            raise SummarizerError("model returned no text")
        try:
            draft = Draft.model_validate(json.loads(text))
        except (ValueError, ValidationError) as exc:
            raise SummarizerError("model output did not match the schema") from exc
        if not draft.fixes:
            raise SummarizerError("model returned no fixes")
        draft.fixes = draft.fixes[:MAX_FIXES]
        return draft


# --- fallback -----------------------------------------------------------------------------------


@dataclass
class SummaryResult:
    draft: Draft
    source: Literal["claude", "mock"]
    model: str | None
    fallback_reason: str | None


async def summarize(
    payload: BriefInput, primary: ClaudeSummarizer | None, mock: MockSummarizer
) -> SummaryResult:
    """Claude if configured and working, otherwise the mock. Never raises for model failures."""
    if primary is None:
        return SummaryResult(mock.build(payload), "mock", None, "ANTHROPIC_API_KEY is not set")
    try:
        draft = await primary.summarize(payload)
    except SummarizerError as exc:
        log.warning("Claude summarizer failed, using mock: %s", exc)
        return SummaryResult(mock.build(payload), "mock", None, str(exc))
    except Exception as exc:  # noqa: BLE001 - the fallback must hold whatever the SDK raises
        log.exception("Unexpected summarizer error, using mock")
        return SummaryResult(mock.build(payload), "mock", None, f"unexpected error: {exc!r}")
    return SummaryResult(draft, "claude", primary.model, None)
