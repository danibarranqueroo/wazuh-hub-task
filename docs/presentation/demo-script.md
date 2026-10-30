# Live demo script

About 6 minutes. Run it after slide 16 (failure handling), or wherever the conversation asks for it. Every command runs from the repository root unless it says `cd app`.

On Dani's machine `uv` comes from mise, so in a fresh terminal run this first:

```bash
export PATH="$HOME/.local/share/mise/shims:$HOME/.docker/bin:$PATH"
```

## Before the meeting (not on screen)

1. The lab is up: Docker Desktop with the three containers, and the OrbStack VM with the agent.

   ```bash
   docker ps --format '{{.Names}}  {{.Status}}' | grep wazuh
   ```

2. `app/.env` exists with the real `WAZUH_API_PASSWORD`. If it doesn't, copy it from `.env.example` once. The password is `API_PASSWORD` under `wazuh.manager` in `lab/wazuh-docker/single-node/docker-compose.yml`.
3. Start the service in terminal 1 and leave it running. The demo uses the mock, because it answers in under a second and needs no login:

   ```bash
   cd app
   LLM_PROVIDER=mock uv run uvicorn wazuh_brief.main:app --port 8000
   ```

4. Check that it can reach Wazuh, so there are no surprises:

   ```bash
   curl -s localhost:8000/readyz        # {"status":"ready","wazuh":"ok"}
   ```

5. Open <http://localhost:8000/> in a browser tab, and open [`docs/examples/brief-000-claude-code.json`](../examples/brief-000-claude-code.json) in the editor.

## The demo

### 1. Is it up, and can it see Wazuh? (30 s)

```bash
curl -s localhost:8000/healthz
curl -s localhost:8000/readyz
```

Say: `/healthz` is the process, `/readyz` makes an authenticated Wazuh call. Together they tell "we are down" apart from "Wazuh is down".

### 2. The page, for agent 001 (1 min)

In the browser tab: pick `ubuntu-lab` on the left.

Point at: confidence `low`, fix 1 "Restore configuration assessment (SCA)", and the gap that names `cis_ubuntu22-04` and the OS mismatch. Say: Ubuntu 26.04 has no CIS policy in 4.14.9, so the brief says "not checked" instead of looking clean.

### 3. The same brief as JSON (1 min)

```bash
curl -s localhost:8000/agents | jq
curl -s localhost:8000/agents/001/brief | jq '{source, model, fallback_reason, confidence: .coverage.confidence, gaps: .coverage.gaps}'
```

Point at `source: "mock"` and `fallback_reason: "LLM_PROVIDER is mock"`. Every brief says who wrote it.

### 4. The full SCA path: agent 000 (1 min 30 s)

The manager is agent `000`. The page hides it, the API serves it. It is the only agent with real CIS results.

```bash
curl -s localhost:8000/agents/000/brief | jq '{source, total: .coverage.sca_failed_checks_total, fixes: [.fixes[] | "\(.rank). [\(.category)] \(.title)"]}'
```

Then the saved model brief for the same agent:

```bash
jq '{source, model, fixes: [.fixes[] | "\(.rank). [\(.category)] \(.title)"]}' docs/examples/brief-000-claude-code.json
```

Say: same input. The mock takes one check per fix. The model groups checks and ranks the open Wazuh ports first. Fix 3 is the `/usr/bin/sh` symlink mistake, fixed later in `04463ee`.

### 5. Failure modes, without touching the lab (1 min 30 s)

Start a second instance in terminal 2 that points at a port where nothing listens:

```bash
cd app
WAZUH_API_URL=https://localhost:55999 LLM_PROVIDER=mock uv run uvicorn wazuh_brief.main:app --port 8001
```

In terminal 3:

```bash
curl -s localhost:8001/healthz                          # ok: the process is up
curl -s -w '  HTTP %{http_code}\n' localhost:8001/readyz            # 503 wazuh_unavailable
curl -s -w '  HTTP %{http_code}\n' localhost:8001/agents/001/brief  # 503: nothing cached in this process
```

Stop it with `Ctrl+C`. Say: in the instance on port 8000, a brief built earlier would be served with `"stale": true` instead of the 503. The tests cover that path.

Model fallback, on a third port, with no key:

```bash
cd app
LLM_PROVIDER=anthropic ANTHROPIC_API_KEY= uv run uvicorn wazuh_brief.main:app --port 8002
```

```bash
curl -s localhost:8002/agents/001/brief | jq '{source, fallback_reason}'
# "mock", "LLM_PROVIDER is anthropic but ANTHROPIC_API_KEY is not set"
```

Stop it with `Ctrl+C`.

### 6. Tests need nothing (30 s)

```bash
cd app
uv run pytest -q          # 83 passed
```

Say: no lab, no key, no Claude Code login. HTTP is mocked with respx and the model clients are fakes.

## Optional: the real model path (dev only)

Only if there is time and the conversation asks for it. It starts a Claude Code process per brief, so one brief can take a minute or more.

```bash
cd app
uv sync --extra claude-code
claude auth status
LLM_PROVIDER=claude-code uv run uvicorn wazuh_brief.main:app --port 8003
curl -s localhost:8003/agents/000/brief | jq '{source, model, fallback_reason, titles: [.fixes[].title]}'
```

If it is slow, do not wait: switch to the saved example in step 4.

## If something breaks live

| Problem | Fallback |
|---|---|
| The lab is down, or `/readyz` returns 503 or 502 | Do not debug on screen. Show the saved real responses instead: `jq '{source, coverage: .coverage.confidence, fixes: [.fixes[].title]}' docs/examples/brief-000-mock.json` and the same for `brief-000-claude-code.json`. Then step 6 (tests) and slide 16. |
| `uv` not found | Run the `export PATH=...` line at the top. |
| Port 8000 is in use | `lsof -i :8000`, or start on another port and change the URLs. |
| The service does not start | Read the uvicorn error: an invalid `LLM_PROVIDER` value fails at start. Otherwise fall back to the saved examples. |
| The page does not load | Use the `curl` steps; the JSON shows the same brief. |
| The Claude Code path is slow or falls back | That is the designed behaviour: `fallback_reason` starts with `claude-code:`. Show it, then use the saved example. |

The saved examples are real responses from the lab, captured on 2026-10-29 and described in [`docs/examples/README.md`](../examples/README.md).
