"""Pydantic models.

Two groups:

- **Wazuh data**: the subset of each Wazuh server API item that the service uses. Unknown fields are
  ignored, so the models survive additive API changes.
- **Brief**: the JSON returned by `GET /agents/{id}/brief`, the public contract of the service.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _WazuhItem(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# --- Wazuh data ---------------------------------------------------------------------------------


class AgentOS(_WazuhItem):
    name: str | None = None
    version: str | None = None
    platform: str | None = None
    major: str | None = None
    minor: str | None = None
    arch: str | None = None


class Agent(_WazuhItem):
    """One item of `GET /agents`."""

    id: str
    name: str
    status: str
    ip: str | None = None
    version: str | None = None
    os: AgentOS | None = None
    last_keep_alive: str | None = Field(default=None, alias="lastKeepAlive")

    @property
    def is_manager(self) -> bool:
        """Agent 000 is the Wazuh manager itself, not a monitored endpoint."""
        return self.id == "000"

    @property
    def os_label(self) -> str:
        if self.os is None or not self.os.name:
            return "unknown OS"
        return f"{self.os.name} {self.os.version or ''}".strip()


class SCAPolicy(_WazuhItem):
    """One item of `GET /sca/{agent_id}`."""

    policy_id: str
    name: str
    description: str | None = None
    passed: int = Field(default=0, alias="pass")
    failed: int = Field(default=0, alias="fail")
    invalid: int = 0
    total_checks: int | None = None
    score: int | None = None
    end_scan: str | None = None


class SCACompliance(_WazuhItem):
    key: str
    value: str


class SCACheck(_WazuhItem):
    """One item of `GET /sca/{agent_id}/checks/{policy_id}`."""

    id: int
    policy_id: str
    title: str
    result: str | None = None
    description: str | None = None
    rationale: str | None = None
    remediation: str | None = None
    compliance: list[SCACompliance] = []

    def compliance_values(self, key: str) -> list[str]:
        return [c.value for c in self.compliance if c.key == key]


class FIMEntry(_WazuhItem):
    """One item of `GET /syscheck/{agent_id}`."""

    file: str
    type: str | None = None
    perm: str | None = None
    uname: str | None = None
    gname: str | None = None
    size: int | None = None
    mtime: str | None = None
    date: str | None = None
    changes: int = 0
    sha256: str | None = None


class PortEndpoint(_WazuhItem):
    ip: str | None = None
    port: int | None = None


class Port(_WazuhItem):
    """One item of `GET /syscollector/{agent_id}/ports`."""

    protocol: str
    local: PortEndpoint
    state: str | None = None
    process: str | None = None


# --- What the service collects for one agent ----------------------------------------------------


class AgentPosture(BaseModel):
    """Everything collected from Wazuh for one brief. Built by `collect_posture`."""

    agent: Agent
    sca_policies: list[SCAPolicy] = []
    sca_failed_checks: list[SCACheck] = []
    sca_failed_total: int = 0
    sca_configured_policies: list[str] | None = None  # None means the config could not be read
    fim_entries: list[FIMEntry] = []
    fim_total: int = 0
    listening_ports: list[Port] = []


# --- Brief (public response) --------------------------------------------------------------------

Category = Literal["sca", "fim", "exposure", "coverage"]
Confidence = Literal["high", "medium", "low"]


class Fix(BaseModel):
    rank: int = Field(ge=1)
    title: str
    category: Category
    why: str
    remediation: str
    evidence: list[str] = []
    references: list[str] = []


class Coverage(BaseModel):
    """What the brief is based on, and what it could not see."""

    confidence: Confidence
    note: str
    sca_policies: int
    sca_failed_checks_total: int
    sca_failed_checks_considered: int
    fim_entries_considered: int
    listening_ports_considered: int
    gaps: list[str] = []


class AgentInfo(BaseModel):
    id: str
    name: str
    status: str
    os: str
    ip: str | None = None
    wazuh_version: str | None = None


class Brief(BaseModel):
    agent: AgentInfo
    generated_at: datetime
    source: Literal["claude", "claude-code", "mock"]
    model: str | None = None
    fallback_reason: str | None = None
    stale: bool = False
    summary: str
    fixes: list[Fix]
    coverage: Coverage


class StaleBrief(Brief):
    """A cached brief served because Wazuh is unreachable."""

    stale: bool = True
    stale_reason: str


# --- What the summarizer sees -------------------------------------------------------------------
# This is everything a summarizer (Claude or the mock) receives. It is deliberately small: no raw
# logs, no hashes, no IP addresses, no credentials.


class InputAgent(BaseModel):
    name: str
    os: str
    status: str
    wazuh_version: str | None = None


class InputPolicy(BaseModel):
    policy_id: str
    name: str
    score: int | None
    passed: int
    failed: int


class InputCheck(BaseModel):
    id: int
    policy_id: str
    title: str
    rationale: str
    remediation: str
    cis: list[str] = []
    mitre_techniques: list[str] = []


class InputFile(BaseModel):
    file: str
    perm: str | None
    owner: str | None
    changes: int
    mtime: str | None
    # Wazuh reports symlinks as perm 'rwxrwxrwx' with type 'file'; such entries are not
    # world-writable files.
    likely_symlink: bool = False


class InputPort(BaseModel):
    protocol: str
    address: str
    port: int
    process: str | None


class BriefInput(BaseModel):
    agent: InputAgent
    sca_applicable: bool
    sca_policies: list[InputPolicy]
    sca_configured_policies: list[str] | None
    sca_failed_checks_total: int
    sca_failed_checks: list[InputCheck]
    fim_entries_total: int
    fim_recent: list[InputFile]
    listening_ports: list[InputPort]
    coverage_gaps: list[str]


class DraftFix(BaseModel):
    title: str
    category: Category
    why: str
    remediation: str
    evidence: list[str] = []
    references: list[str] = []


class Draft(BaseModel):
    """What a summarizer returns. The service adds ranks, coverage counts and metadata."""

    summary: str
    fixes: list[DraftFix]
    coverage_note: str


class AgentListItem(BaseModel):
    id: str
    name: str
    status: str
    os: str
    ip: str | None = None


class ErrorBody(BaseModel):
    error: str
    detail: str
