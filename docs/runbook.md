# Runbook

Symptoms, checks and actions for the brief service. The commands assume the service on `localhost:8000`, run from `app/`. Two endpoints and one response field are the starting point for almost everything:

| Signal | Meaning |
|---|---|
| `GET /healthz` returns `{"status": "ok"}` | The process is up. It does not call Wazuh. |
| `GET /readyz` returns `{"status": "ready", "wazuh": "ok"}` | An authenticated Wazuh call works. A 503 or 502 means Wazuh is the problem, not the service. |
| `fallback_reason` in a brief | Why the mock wrote the brief instead of the configured model. `null` means the model worked. |

## Wazuh API down

**Symptoms:** `/readyz` returns 503 `wazuh_unavailable`. Briefs return 503, or come back with `"stale": true` and a `stale_reason` for agents that were briefed earlier by this process.

**Checks:**

```bash
curl -s localhost:8000/readyz
curl -sk -o /dev/null -w "%{http_code}\n" https://<wazuh-host>:55000/   # 401 means the API is up
docker ps --filter name=wazuh.manager                                 # lab only
```

**Actions:**
- If the manager container or host is down, that is a Wazuh incident: hand it to whoever runs Wazuh. Stale briefs keep serving meanwhile.
- If Wazuh is up but unreachable from the service, check `WAZUH_API_URL`, DNS, the firewall and the TLS setting (`WAZUH_VERIFY_TLS`).
- Nothing in the service needs a restart. It retries on every request and recovers on its own.

## Wazuh authentication failing

**Symptoms:** `/readyz` and briefs return 502 `wazuh_auth_failed`. The stale cache is not used for this case, on purpose.

**Checks:**

```bash
curl -sk -u "$WAZUH_API_USER:$WAZUH_API_PASSWORD" -X POST "https://<wazuh-host>:55000/security/user/authenticate?raw=true" -o /dev/null -w "%{http_code}\n"
```

`200` means the credentials work from this shell. `401` means they are wrong or the user is locked.

**Actions:**
- Fix `WAZUH_API_USER` / `WAZUH_API_PASSWORD` in `app/.env` (or the secret store), then restart the service; settings are read at start-up.
- If the password was rotated on the Wazuh side, update it here in the same change.
- Never paste the password or a JWT into a ticket or chat.

## Model down or slow (fallback engaged)

**Symptoms:** briefs still return 200, but with `"source": "mock"` and a `fallback_reason` such as `claude: model call timed out`, `claude: model rate limited (429)` or `claude: could not reach the model API`.

**Checks:**

```bash
curl -s localhost:8000/agents/001/brief | python3 -c 'import json,sys; b=json.load(sys.stdin); print(b["source"], b["model"], b["fallback_reason"])'
```

Also check the provider's status page, and the service log for `summarizer failed, using mock`.

**Actions:**
- No urgent action: the mock brief is deterministic and still ranked. Users see which one wrote it.
- `ANTHROPIC_API_KEY was rejected (401)`: rotate the key.
- Repeated timeouts: raise `LLM_TIMEOUT_SECONDS` only if latency is the problem, or keep the mock until the provider recovers.
- To force the mock deliberately, set `LLM_PROVIDER=mock` and restart.

## Bad model output

**Symptoms:** the brief is wrong rather than missing. For example it ranks a symlink as a world-writable file, invents a change, or contradicts its own coverage note. A schema problem shows up as a fallback instead (`model output did not match the schema`).

**Checks:**
- Look at `source` and `model`.
- Compare with the mock for the same agent (`LLM_PROVIDER=mock`), which reads the same input. [`examples/`](examples/) has a pair.
- Check the facts in the evidence fields against Wazuh directly (`GET /syscheck/{id}`, `GET /sca/{id}/checks/{policy}`).

**Actions:**
- Short term: switch to `LLM_PROVIDER=mock` if the output is misleading.
- Fix the input or the prompt, not the output: the `/usr/bin/sh` symlink case was fixed by marking links in the input (`likely_symlink`) and adding one prompt rule (commit `04463ee`).
- Record the case so it becomes a test, and later an eval case ([saas-target.md](saas-target.md#prompt-quality)).

## The service itself is down

**Symptoms:** `/healthz` does not answer, or the page does not load.

**Checks:**

```bash
curl -s -m 3 localhost:8000/healthz
lsof -i :8000
```

Then read the uvicorn output for a start-up error. A settings error such as an invalid `LLM_PROVIDER` value fails at start.

**Actions:**
- Fix the configuration error and start it again: `uv run uvicorn wazuh_brief.main:app --port 8000`.
- If it started after a change and fails since, roll back to the previous commit and redeploy.
- Restarting empties the in-memory cache, so stale briefs are not available until new ones are built.
