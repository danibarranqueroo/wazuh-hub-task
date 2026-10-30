# Architecture

Three views: the lab the service reads from, the service itself, and what happens on one `GET /agents/{id}/brief` request. Everything here is either in the code under [`app/`](../app/) or was checked against the running lab on 2026-10-29 (container ports, running Wazuh daemons, the Filebeat output host and the dashboard's upstream hosts). Wazuh internals are drawn only at that level.

## 1. The lab

```mermaid
flowchart LR
    subgraph orb["OrbStack VM: ubuntu-lab, Ubuntu 26.04 (agent 001)"]
        agent["wazuh-agent<br/>FIM, SCA, Syscollector, log collection"]
    end

    subgraph docker["Docker Desktop: wazuh-docker single-node 4.14.9"]
        subgraph mgr["wazuh.manager (also agent 000)"]
            remoted["wazuh-remoted<br/>:1514 events"]
            authd["wazuh-authd<br/>:1515 enrollment"]
            analysisd["wazuh-analysisd<br/>decoders and rules"]
            wdb[("wazuh-db<br/>per-agent state:<br/>SCA, FIM, inventory")]
            apid["wazuh-apid<br/>server API :55000"]
            filebeat["Filebeat"]
        end
        indexer[("wazuh.indexer<br/>:9200")]
        dashboard["wazuh.dashboard<br/>:443"]
    end

    agent -- "enroll" --> authd
    agent -- "events" --> remoted
    remoted --> analysisd
    remoted & analysisd -. "agent state" .-> wdb
    analysisd -- "alerts" --> filebeat
    filebeat --> indexer
    apid --> wdb
    dashboard -- "alerts and events" --> indexer
    dashboard -- "management views" --> apid
```

| Component | Role | Port on the host |
|---|---|---|
| `wazuh-agent` on `ubuntu-lab` | Collects FIM, SCA, inventory and logs, sends them to the manager | — |
| `wazuh-authd` | Agent enrollment | 1515/tcp |
| `wazuh-remoted` | Receives agent events | 1514/tcp (514/udp is also published, for syslog) |
| `wazuh-analysisd` | Runs decoders and rules, raises alerts | — |
| `wazuh-db` | Current per-agent state that the server API reads | — |
| Filebeat | Ships alerts from the manager to the indexer (`https://wazuh.indexer:9200`) | — |
| `wazuh-apid` | Wazuh server API, the only thing this service talks to | 55000/tcp |
| `wazuh.indexer` | Stores alerts and events | 9200/tcp |
| `wazuh.dashboard` | UI; reads the indexer and calls the server API | 443/tcp |

The dotted edge into `wazuh-db` is deliberately vague: the daemons were checked as running, but which daemon writes which state was not verified, so it is not drawn in detail.

Agent `000` is the manager itself (`wazuh.manager`, Amazon Linux 2023). It runs its own SCA scan, which is why it is the only agent in the lab with SCA results. The service hides it from the agent list but serves its brief.

The service does **not** read the indexer, so alerts and vulnerability detection are out of scope ([ADR 0001](adr/0001-phase2-stack-and-shape.md)). Every brief says so in its coverage gaps.

## 2. The service

```mermaid
flowchart TB
    browser["Browser<br/>GET / (single page)"]
    curl["API client<br/>curl, scripts"]

    subgraph svc["wazuh-brief (FastAPI, one process)"]
        direction LR
        cache[("in-memory cache<br/>last brief per agent")]
        routes["main.py<br/>routes, error mapping"]
        posture["posture.py<br/>collect, coverage gaps,<br/>BriefInput"]
        client["wazuh_client.py<br/>JWT cache, retries,<br/>typed errors"]
        select{"select_summarizer<br/>LLM_PROVIDER"}
    end

    api["Wazuh server API<br/>:55000"]

    claude["Claude API<br/>ClaudeSummarizer"]
    mock["MockSummarizer<br/>rules, no network"]
    cc["Claude Code login<br/>ClaudeCodeSummarizer<br/>(dev only)"]

    browser --> routes
    curl --> routes
    routes <--> cache
    routes --> posture --> client -- "GET only (+ login)" --> api
    routes --> select
    select -- "auto + key,<br/>or anthropic" --> claude
    select -- "mock,<br/>or no key" --> mock
    select -- "claude-code<br/>(opt-in)" --> cc
    claude -. "any failure" .-> mock
    cc -. "any failure" .-> mock
```

| `LLM_PROVIDER` | Primary | Falls back to the mock when |
|---|---|---|
| `auto` (default) | Claude API if `ANTHROPIC_API_KEY` is set | No key; timeout, API error, refusal, `max_tokens`, output that fails the schema |
| `anthropic` | Claude API | Same, and when the key is missing |
| `claude-code` | Agent SDK on the developer's own login, dev only ([ADR 0002](adr/0002-dev-only-agent-sdk-summarizer.md)) | SDK not installed, CLI not found, not logged in, process error, timeout, invalid JSON |
| `mock` | — | Always the mock |

Every brief records `source` (`claude`, `claude-code` or `mock`), `model` and, when the mock ran instead, `fallback_reason`.

## 3. One request: `GET /agents/{id}/brief`

```mermaid
sequenceDiagram
    autonumber
    participant U as Browser or client
    participant R as main.py
    participant P as posture.py
    participant W as wazuh_client.py
    participant A as Wazuh API :55000
    participant S as Summarizer
    participant M as MockSummarizer

    U->>R: GET /agents/001/brief
    R->>P: collect_posture("001")
    P->>W: get_agent
    opt no cached JWT, or it expires within 30 s
        W->>A: POST /security/user/authenticate?raw=true
        A-->>W: JWT
    end
    W->>A: GET /agents?agents_list=001
    Note over W,A: Connection error, timeout, 429 or 5xx:<br/>retry with backoff, then WazuhUnavailable.<br/>A 401 triggers one fresh login.
    par concurrent reads
        W->>A: GET /sca/001
        W->>A: GET /agents/001/config/wmodules/wmodules
        W->>A: GET /syscheck/001?sort=-mtime&limit=20
        W->>A: GET /syscollector/001/ports?state=listening
    end
    loop each SCA policy with failed checks
        W->>A: GET /sca/001/checks/{policy}?result=failed
    end

    alt Wazuh unreachable (WazuhUnavailable)
        alt a brief for 001 is in the cache
            R-->>U: 200, cached brief, stale: true, stale_reason
        else nothing cached
            R-->>U: 503 {"error": "wazuh_unavailable", ...}
        end
    else data collected
        P-->>R: AgentPosture
        R->>P: build_input (rank checks, coverage gaps)
        R->>S: summarize(BriefInput)
        alt summarizer succeeds
            S-->>R: Draft (source claude or claude-code)
        else no summarizer configured, or it fails
            R->>M: build(BriefInput)
            M-->>R: Draft (source mock, fallback_reason)
        end
        R->>R: store in cache
        R-->>U: 200 Brief
    end
```

Other outcomes from the same endpoint, all JSON with `error` and `detail`:

| Status | `error` | Cause |
|---|---|---|
| 404 | `agent_not_found` | Wazuh answers HTTP 200 with failed item code 1701, mapped to `WazuhNotFound` |
| 422 | — | Agent ID is not 3 to 5 digits |
| 502 | `wazuh_auth_failed` | Wazuh rejects the configured user or password. The stale cache is not used here: a credentials problem should be visible, not hidden. |
| 502 | `wazuh_api_error` | Any other Wazuh error response |
