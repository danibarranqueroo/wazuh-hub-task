# Wazuh Hub — Software Engineer technical task

This repository holds my work for the Wazuh Hub team's technical task. The task has three phases:

| Phase | Topic | Where it lives |
|---|---|---|
| 1 | Get to know Wazuh: install a 4.x lab and explore it, without AI | [`PHASE1.md`](PHASE1.md), [`screenshots/`](screenshots/) |
| 2 | Build a small piece of a SaaS service on top of Wazuh, with AI | [`app/`](app/), [`docs/`](docs/), [`PHASE2.md`](PHASE2.md) |
| 3 | Present the work | Live conversation |

## Repository map

```
.
├── PHASE1.md                # Phase 1 write-up (written by hand, no AI)
├── PHASE2.md                # Phase 2 answers
├── CLAUDE.md                # Conventions and hard rules for AI agents working in this repo
├── .claude/agents/          # Subagents: reviewer, docs-keeper
├── .github/workflows/ci.yml # Lint and tests for app/ on every push and PR
├── screenshots/             # Screenshots of my lab, captioned in PHASE1.md
├── lab/                     # Notes for the local Wazuh lab
├── app/                     # Phase 2 service: Agent Hardening Brief
│   ├── .env.example         # Every setting, with placeholders
│   ├── src/wazuh_brief/     # config, wazuh_client, posture, llm, models, main, templates/
│   └── tests/               # pytest + respx; fixtures/ has its own README
└── docs/
    ├── plan.md              # Work plan and the decisions behind it
    ├── agent-log.md         # How I directed AI agents, dated
    ├── adr/                 # Architecture decision records
    └── diagrams/            # Architecture and workflow diagrams
```

## Lab at a glance

- **Wazuh version:** 4.14.9, the latest stable 4.x release when the task started.
- **Server, indexer and dashboard:** the official [`wazuh-docker`](https://github.com/wazuh/wazuh-docker) single-node deployment, on Docker Desktop on an Apple Silicon Mac.
- **Agent:** an Ubuntu VM in OrbStack, enrolled with the Wazuh manager running in Docker.

The work plan is in [`docs/plan.md`](docs/plan.md). The commit history shows how the work progressed.

## Phase 2: Agent Hardening Brief

> "I have hundreds of failed CIS checks. What do I fix first?"

A small FastAPI service that reads one agent's current posture through the **Wazuh server API** and returns a short, prioritized brief: the top five fixes, why each matters, the concrete remediation, the evidence, and a coverage note that says what the brief could not see. Claude writes the brief when `ANTHROPIC_API_KEY` is set. Otherwise, or if the model call fails, a deterministic rule-based summarizer produces the same response shape. Every response says which one ran.

### Quickstart

Requirements: Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and a reachable Wazuh 4.x server API (port 55000).

```bash
cd app
cp .env.example .env      # then set WAZUH_API_PASSWORD (and ANTHROPIC_API_KEY if you have one)
uv sync
uv run uvicorn wazuh_brief.main:app --port 8000
```

Open <http://localhost:8000/>, pick an agent, read the brief. The OpenAPI docs are at <http://localhost:8000/docs>.

Tests and lint need neither the lab nor an API key:

```bash
cd app
uv run pytest
uv run ruff check
```

### Configuration

All settings come from environment variables or `app/.env` (gitignored). [`app/.env.example`](app/.env.example) lists them.

| Variable | Default | Meaning |
|---|---|---|
| `WAZUH_API_URL` | `https://localhost:55000` | Wazuh server API base URL |
| `WAZUH_API_USER` | `wazuh-wui` | API user. Read-only permissions are enough. |
| `WAZUH_API_PASSWORD` | empty | API password |
| `WAZUH_VERIFY_TLS` | `true` | Verify the API certificate. The `wazuh-docker` lab uses a self-signed one, so the example sets `false`. |
| `WAZUH_TIMEOUT_SECONDS` | `10` | Per-request timeout |
| `WAZUH_MAX_RETRIES` | `2` | Extra attempts on connection errors, timeouts, 429 and 5xx, with exponential backoff (0.5 s, 1 s, ...) |
| `ANTHROPIC_API_KEY` | empty | Empty means mock summarizer only |
| `LLM_MODEL` | `claude-sonnet-5-5` | Claude model ID |
| `LLM_TIMEOUT_SECONDS` | `45` | Model call timeout; on expiry the mock is used |
| `LLM_MAX_TOKENS` | `6000` | Output token cap for the model call |

### Endpoints

| Method and path | Returns |
|---|---|
| `GET /` | The single HTML page: agent list on the left, brief on the right |
| `GET /agents` | Agents known to the manager. Agent `000` (the manager itself) is hidden; add `?include_manager=true` to see it. |
| `GET /agents/{id}/brief` | The brief for one agent (`id` is the 3-5 digit Wazuh agent ID) |
| `GET /healthz` | `{"status": "ok"}` if the process is up. Does not call Wazuh. |
| `GET /readyz` | `{"status": "ready", "wazuh": "ok"}` if an authenticated Wazuh call succeeds, else 503 |

Errors are JSON with an `error` code and a human-readable `detail`:

| Status | `error` | When |
|---|---|---|
| 404 | `agent_not_found` | Wazuh does not know the agent ID |
| 422 | (FastAPI validation) | The agent ID is not 3-5 digits |
| 502 | `wazuh_auth_failed` | Wazuh rejected `WAZUH_API_USER` / `WAZUH_API_PASSWORD` |
| 502 | `wazuh_api_error` | Wazuh returned another error |
| 503 | `wazuh_unavailable` | Wazuh is unreachable after retries **and** no brief for that agent is cached |

If Wazuh is unreachable but this process built a brief for the agent earlier, `GET /agents/{id}/brief` returns that brief with `"stale": true` and a `stale_reason`, instead of a 503. The cache is in memory and per process.

### The brief

Trimmed example for the lab agent, which has no SCA results (see below):

```json
{
  "agent": {"id": "001", "name": "ubuntu-lab", "status": "active", "os": "Ubuntu 26.04.1 LTS", "...": "..."},
  "source": "mock",
  "model": null,
  "fallback_reason": "ANTHROPIC_API_KEY is not set",
  "stale": false,
  "summary": "ubuntu-lab (Ubuntu 26.04.1 LTS) has no SCA results, so CIS hardening is not assessed ...",
  "fixes": [
    {"rank": 1, "title": "Restore configuration assessment (SCA) for Ubuntu 26.04.1 LTS", "category": "coverage",
     "why": "...", "remediation": "...", "evidence": ["GET /sca returned 0 policies", "Configured SCA policies: cis_ubuntu22-04"], "references": ["..."]},
    {"rank": 2, "title": "Harden the SSH service that listens on all interfaces", "category": "exposure", "...": "..."}
  ],
  "coverage": {
    "confidence": "low",
    "note": "No SCA policy applies to Ubuntu 26.04.1 LTS. ...",
    "sca_policies": 0, "sca_failed_checks_total": 0, "sca_failed_checks_considered": 0,
    "fim_entries_considered": 20, "listening_ports_considered": 2,
    "gaps": ["No SCA policy applies to Ubuntu 26.04.1 LTS. ...", "File integrity data is a baseline only: ...", "Alerts and vulnerability detection are not included: ..."]
  }
}
```

| Field | Meaning |
|---|---|
| `source` | `claude` or `mock`: which summarizer wrote `summary`, `fixes` and `coverage.note` |
| `model` | Claude model ID when `source` is `claude`, else `null` |
| `fallback_reason` | Why the mock ran (no key, timeout, API error, refusal, bad output), else `null` |
| `fixes[].category` | `sca` (failed CIS check), `fim` (file integrity), `exposure` (listening port), `coverage` (missing data) |
| `coverage.confidence` | `high`: SCA results and agent active. `medium`: SCA results but agent not active. `low`: no SCA results. |
| `coverage.gaps` | Computed by rule, not by the model, so they are always present and always the same for the same data |

### What it reads from Wazuh

Read-only calls only. The single non-GET request is the login.

| Call | Used for |
|---|---|
| `POST /security/user/authenticate?raw=true` | JWT login (basic auth). Cached until shortly before `exp`, refreshed once on a 401. |
| `GET /agents?agents_list={id}` | Agent name, status, OS, version |
| `GET /sca/{id}` | SCA policies with pass/fail counts and score |
| `GET /sca/{id}/checks/{policy}?result=failed` | Failed checks: title, rationale, remediation, CIS and MITRE mappings (up to 500 per policy) |
| `GET /agents/{id}/config/wmodules/wmodules` | Which SCA policy files the agent is configured with, to explain an empty SCA result |
| `GET /syscheck/{id}?sort=-mtime&limit=20` | The 20 most recently modified FIM entries |
| `GET /syscollector/{id}/ports?state=listening` | Listening sockets |
| `GET /manager/info` | `/readyz` only |

### How a brief is built

1. **Collect** the calls above (`posture.collect_posture`).
2. **Compute coverage by rule** (`posture.coverage_gaps`): missing SCA, truncated check lists, baseline-only FIM, inactive agent, and the fact that alerts and vulnerabilities are out of scope.
3. **Rank and trim** (`posture.build_input`): failed checks are weighted by keywords (SSH, authentication, firewall, privileges, audit), MITRE mappings and whether SSH is exposed. The top 60 go into a small `BriefInput`. It holds no raw logs, hashes, agent IPs or credentials.
4. **Summarize** (`llm.summarize`): Claude with a JSON-schema output when configured, else or on any failure the rule-based `MockSummarizer`, which reads the same `BriefInput`.

### Agents without SCA results

The lab agent runs Ubuntu 26.04. Wazuh 4.14.9 ships no CIS policy for it. The agent is configured with `cis_ubuntu22-04.yml` and skips it because the policy's OS requirement fails, so `GET /sca/001` is empty. The brief does not present that as a clean result: confidence is `low`, the first gap names the configured policy and the OS mismatch, and the first fix is to restore SCA coverage. The SCA code path is tested with fixtures synthesized from the Wazuh API reference ([`app/tests/fixtures/README.md`](app/tests/fixtures/README.md)). The decision is recorded in [`docs/agent-log.md`](docs/agent-log.md).

### Phase 2 documents

| Document | What it covers |
|---|---|
| [`docs/adr/0001-phase2-stack-and-shape.md`](docs/adr/0001-phase2-stack-and-shape.md) | Why FastAPI, server-API-only data, and Claude with a mock fallback |
| [`docs/agent-log.md`](docs/agent-log.md) | How AI agents were directed, including the full prompts |
| [`CLAUDE.md`](CLAUDE.md) | Conventions and hard rules every agent follows |
| [`app/tests/fixtures/README.md`](app/tests/fixtures/README.md) | Which fixtures are live captures and which are synthesized |
