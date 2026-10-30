# Test fixtures

JSON bodies of Wazuh server API responses, used by the tests through respx. No test talks to a real Wazuh.

Two kinds of fixture, told apart by the file prefix.

## `live_*`: captured from the lab

Captured on 2026-10-29 from the Wazuh 4.14.9 lab (`wazuh-docker` single-node, agent `001` on Ubuntu 26.04.1 LTS) with read-only GET requests.

| File | Request |
|---|---|
| `live_agents.json` | `GET /agents?limit=500&sort=+id` |
| `live_agent_001.json` | `GET /agents?agents_list=001` |
| `live_agent_999_not_found.json` | `GET /agents?agents_list=999` (HTTP 200, `failed_items` code 1701) |
| `live_sca_001_empty.json` | `GET /sca/001` (no policy results: see below) |
| `live_syscheck_001.json` | `GET /syscheck/001?limit=8&sort=-mtime` |
| `live_ports_001.json` | `GET /syscollector/001/ports?state=listening&limit=100` |
| `live_wmodules_001.json` | `GET /agents/001/config/wmodules/wmodules`, trimmed to the `sca` module |
| `live_manager_info.json` | `GET /manager/info` |

Edits: pretty-printed; `live_wmodules_001.json` keeps only the `sca` module. Nothing else was changed. The responses contain no tokens or credentials (the JWT travels in a request header, not in a body). IP addresses are private lab addresses.

`GET /sca/001` is empty because the only SCA policy on the agent is `cis_ubuntu22-04.yml`, and the agent skips it: its "Check Ubuntu version" requirement fails on 26.04. Wazuh 4.14.9 ships no CIS policy for Ubuntu 26.04.

## `docs_*`: synthesized from the Wazuh API reference

Because the lab agent has no SCA results, the SCA path is tested with fixtures **synthesized from the Wazuh 4.14 API reference**, not captured. They describe a made-up agent `002` (`ubuntu-2404`, Ubuntu 24.04.1 LTS).

Source: the OpenAPI spec that renders the [Wazuh 4.14 server API reference](https://documentation.wazuh.com/4.14/user-manual/api/reference.html), `api/api/spec/spec.yaml` at tag `v4.14.9` of `wazuh/wazuh`, specifically the examples and schemas for:

- `GET /sca/{agent_id}` (schema `SCADatabase`; example policy `cis_ubuntu20-04` with `fail`, `pass`, `invalid`, `score`, `total_checks`, `hash_file`)
- `GET /sca/{agent_id}/checks/{policy_id}` (schema `SCAChecks`; example check with `id`, `title`, `rationale`, `remediation`, `compliance`, `rules`, `result`, `condition`)

The field names and nesting follow the spec. The field set was also checked against real failed checks of the manager's own policy (`GET /sca/000/checks/cis_amazon_linux_2023?result=failed`), which match. The values (policy ID `cis_ubuntu24-04`, check IDs, titles, remediations, counts) are written by hand to look like a CIS Ubuntu 24.04 run, and are **not** real scan output. Agent, FIM, ports and wmodules fixtures for `002` reuse the shape of the live captures with invented values. `docs_syscheck_002.json` includes a modified `sshd_config` (`changes: 3`) and a world-writable sudoers drop-in, so the FIM rules have something to find.

| File | Shape of |
|---|---|
| `docs_agent_002.json` | `GET /agents?agents_list=002` |
| `docs_sca_002.json` | `GET /sca/002` |
| `docs_sca_checks_002_failed.json` | `GET /sca/002/checks/cis_ubuntu24-04?result=failed` (9 items, `total_affected_items: 87`) |
| `docs_syscheck_002.json` | `GET /syscheck/002?sort=-mtime` |
| `docs_ports_002.json` | `GET /syscollector/002/ports?state=listening` |
| `docs_wmodules_002.json` | `GET /agents/002/config/wmodules/wmodules`, `sca` module only |

## Refreshing the live fixtures

Log in, then repeat the requests above with `curl -k -H "Authorization: Bearer $TOKEN" ...`, and pipe through `python3 -m json.tool`. Keep the token in a shell variable only. Before committing, run `grep -l 'eyJ\|Bearer' app/tests/fixtures/*.json`; it must print nothing.
