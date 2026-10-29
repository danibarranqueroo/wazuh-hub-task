# Agent log

A dated record of how I directed AI agents during Phase 2: what I asked for, what happened, and what I changed as a result. Newest entries are at the bottom.

The agent setup itself is in the repository: [`CLAUDE.md`](../CLAUDE.md) holds the conventions and hard rules, and [`.claude/agents/`](../.claude/agents/) holds the `reviewer` and `docs-keeper` subagents.

---

## 2026-10-29 — Entry 1: first delegation lands in the wrong repository

I asked the main Claude Code session to delegate the Phase 2 groundwork to a background subagent while I did Phase 1 by hand.

The first launch used automatic worktree isolation. The session's working directory was inside the upstream `wazuh-docker` clone under `lab/`, so the isolated worktree was created from that repository instead of `wazuh-hub-task`. The subagent noticed it was in the wrong place and stopped without writing anything.

The main session then:

1. removed the stray worktree from the `wazuh-docker` clone;
2. created a proper worktree for the branch `phase2/hardening-brief`, next to the repo at `../wazuh-hub-task-phase2`, from `main` at `2c41da7`;
3. relaunched the subagent with an explicit working directory and a branch check before the first commit.

**Lesson:** always check which repository an isolated worktree belongs to. Isolation follows the session's current directory, not the project you have in mind.

---

## 2026-10-29 — Entry 2: the relaunch prompt

The relaunched subagent works only in the `phase2/hardening-brief` worktree, commits as it goes and does not push. This is the full prompt it received, unchanged.

<details>
<summary>Full prompt for the Phase 2 groundwork subagent</summary>

````text
You are building Phase 2 of a job technical task for Dani. This is a relaunch: a previous attempt got an isolated worktree inside the wrong repository and stopped without writing anything.

## Where to work
- Work ONLY in `/Users/dani/Desktop/projects/wazuh-hub-task-phase2`. It is a git worktree of the repo `danibarranqueroo/wazuh-hub-task`, already on branch `phase2/hardening-brief`, created from `main` at `2c41da7`.
- Run every command with an absolute `cd /Users/dani/Desktop/projects/wazuh-hub-task-phase2 && ...`.
- Do not touch `/Users/dani/Desktop/projects/wazuh-hub-task`. That's the `main` checkout, where Dani is committing Phase 1 right now.
- Check with `git -C /Users/dani/Desktop/projects/wazuh-hub-task-phase2 branch --show-current` before your first commit.

## The task (from Wazuh's brief)
Phase 2: "Build a small piece of a SaaS service on top of Wazuh. It must read real data from your lab through the Wazuh API and use AI on it. One screen, one endpoint or one script is enough. Make your workflow visible in the repository: your plan, your commits and everything you used to direct your agents."
- The model call may be stubbed with mock responses.
- All deliverables are in English.
- Documentation quality is judged explicitly. Write docs a teammate can rely on.

## Hard rules
- NEVER create, open, edit or commit `PHASE1.md`, anything in `screenshots/`, or anything in `lab/`. Phase 1 must be AI-free.
- Never commit secrets. Credentials go in `.env`, which is gitignored. `.env.example` is committed.
- Commits are small and conventional (`feat:`, `test:`, `docs:`, `chore:`, `ci:`), made as you go, never one big commit.
- Git signing is configured globally (`commit.gpgsign=true`). Keep it on.
- End every commit message with a blank line, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Do NOT push, and do not create PRs. Dani reviews and pushes.
- Tooling: `uv` comes from mise and is missing from non-interactive shells. Prefix commands with `PATH="$HOME/.local/share/mise/shims:$HOME/.docker/bin:$PATH"`.
- Homebrew `python3` is 3.14. Target Python >=3.12.

## The lab (running now; read-only for you)
- Wazuh 4.14.9 single-node in Docker Desktop.
- Wazuh server API: `https://localhost:55000`, self-signed TLS.
- API user `wazuh-wui`, password `<redacted: wazuh-docker default>`. That's the wazuh-docker default; Dani changed only the indexer `admin` password.
- To log in: `POST /security/user/authenticate?raw=true` with basic auth. It returns a plain-text JWT.
- Only make read-only GET calls. Do not change Wazuh config. Do not restart containers.
- Never write a token to a file that could be committed. Strip tokens from fixtures.

Facts already verified against the live API:
- `GET /agents` returns agent `000` (the manager itself, `wazuh.manager`, Amazon Linux 2023) and agent `001` (`ubuntu-lab`, Ubuntu 26.04.1 LTS, active). Hide `000` from the agent picker; the manager is not a monitored endpoint.
- `GET /syscheck/001?limit=20&sort=-mtime` works. Entries have `file`, `perm`, `uname`, `size`, `mtime`, `date`, hashes and `changes`.
- **`GET /sca/001` returns no items.** That's not a timing issue. The agent log shows the only SCA policy installed is `cis_ubuntu22-04.yml`, and the agent skips it because of the "Check Ubuntu version" requirement: Ubuntu 26.04 has no CIS policy in Wazuh 4.14.9. Dani may add a second agent on Ubuntu 24.04 later to get real SCA data. Build accordingly:
  - The SCA code path must be fully implemented and tested.
  - Build SCA fixtures from the response shape in the Wazuh 4.14 API reference for `GET /sca/{agent_id}` and `GET /sca/{agent_id}/checks/{policy_id}`. Fetch it with WebFetch from documentation.wazuh.com, and note in the fixture README that it was synthesized from the docs.
  - The brief must degrade gracefully when an agent has no SCA results. Use FIM changes, agent info and any other server-API data that helps. The brief should then say clearly that no SCA policy applies to this OS version, and why that matters (a coverage gap).
  - Read-only Syscollector endpoints (`/syscollector/{id}/os`, `/packages`, `/ports`) are available. You may include a small slice of them if it makes the 26.04 brief useful, for example listening ports. Keep the scope small.

## What to build: "Agent Hardening Brief"
`GET /agents/{id}/brief` reads one agent's real data through the Wazuh server API: agent info, failed SCA checks, and recent FIM changes. It asks Claude for a short prioritized brief:
- the top 5 or so fixes that matter most
- why each one matters
- the concrete remediation
- a confidence or coverage note

`GET /` is one small HTML screen: list the agents, click one, show the brief. The pitch: "I have hundreds of failed CIS checks — what do I fix first?"

### Layout under `app/`
- `pyproject.toml`: uv project. Dependencies: fastapi, uvicorn, httpx, pydantic, pydantic-settings, jinja2, anthropic. Dev dependencies: pytest, respx, ruff.
- `src/wazuh_brief/config.py`: settings from env (`WAZUH_API_URL`, `WAZUH_API_USER`, `WAZUH_API_PASSWORD`, `WAZUH_VERIFY_TLS`, `ANTHROPIC_API_KEY`, `LLM_MODEL`).
- `src/wazuh_brief/wazuh_client.py`:
  - JWT auth, with the token cached until it expires and refreshed on a 401.
  - Calls: agents, SCA policies, failed SCA checks, syscheck.
  - Timeouts, plus a small retry with backoff on connection errors and 5xx.
  - TLS verification configurable.
  - Typed errors, such as `WazuhUnavailable`.
- `src/wazuh_brief/llm.py`:
  - A `Summarizer` protocol.
  - `ClaudeSummarizer`: Anthropic SDK, structured JSON output, bounded tokens.
  - `MockSummarizer`: deterministic and rule-based, so its output is still useful.
  - Fall back to the mock if there's no API key, or if the model call fails or times out. The response includes `"source": "claude" | "mock"`.
  - Send the model only the fields it needs. Never send raw logs or credentials.
  - BEFORE writing `llm.py`, invoke the `claude-api` skill with the Skill tool, to get current model IDs and SDK usage. The default model comes from that skill (a current Sonnet-class model), overridable with `LLM_MODEL`.
- `src/wazuh_brief/models.py`: pydantic response models.
- `src/wazuh_brief/main.py`: FastAPI with `/healthz`, `/readyz` (checks the Wazuh API), `/agents`, `/agents/{id}/brief` and `/`. If Wazuh is unreachable, return a 503 with a clear JSON message. If a brief for that agent is cached in memory, serve it instead, flagged as stale.
- `src/wazuh_brief/templates/index.html`: one clean, minimal page, with no build step.
- `tests/`:
  - the client against fixtures, with respx
  - the summarizer fallback paths
  - the endpoint's 503 path
  - the happy path with SCA data and the no-SCA path
  
  Tests must not need the live lab or an API key.
- `app/.env.example`.

### Agent setup (commit this FIRST, before any code, so the history shows it)
- `CLAUDE.md` at the repo root:
  - what the repo is, and the stack
  - commands: `cd app && uv run pytest`, `uv run ruff check`, how to run the server
  - conventions
  - the hard rules above
  - docs updated in the same change as the code
- `.claude/agents/reviewer.md`: reviews a diff against the CLAUDE.md conventions.
- `.claude/agents/docs-keeper.md`: checks that README and docs match the code.
- Both agent files need proper Claude Code subagent frontmatter (name, description, tools).
- `docs/agent-log.md`: a dated log of how agents were directed.
  - **Entry 1, 2026-10-29.** Dani asked the main Claude Code session to delegate the Phase 2 groundwork to a background subagent while he did Phase 1 by hand. The first launch used automatic worktree isolation. It landed in the upstream `wazuh-docker` clone under `lab/`, because the session's working directory was there. The subagent stopped without writing anything. The main session then removed the stray worktree, created a proper worktree for `phase2/hardening-brief` next to the repo, and relaunched. Lesson: always check which repository an isolated worktree belongs to.
  - **Entry 2:** this relaunch. Paste this full prompt verbatim in a collapsible `<details>` block.
  - Add short entries as you make notable decisions. One of them should be the SCA/Ubuntu 26.04 finding and how the design handles it.
- `docs/adr/0001-phase2-stack-and-shape.md`: a short ADR (context, decision, consequences) for FastAPI, server-API-only data, and Claude with a mock fallback.

### Also
- `.github/workflows/ci.yml`: on push and PR, set up uv and run ruff and pytest in `app/`.
- Update `README.md` (the repo map, plus a Phase 2 quickstart: copy `.env.example`, `uv sync`, run the server, open `/`). Update `docs/plan.md` only where Phase 2 facts change.
- Keep the existing style: plain and factual, with tables where useful.
- Do NOT write `PHASE2.md` or the architecture/workflow diagrams yet. Those come later.

## Verify before finishing
- `cd app && uv run ruff check && uv run pytest` passes.
- Run the server against the live lab: `uv run uvicorn wazuh_brief.main:app --port 8000` from `app/`, with a local `.env` you create and do not commit.
  - Hit `/agents` and `/agents/001/brief` with curl.
  - Confirm that real lab data comes back with `source: mock`, and that the no-SCA coverage note appears for `001`. Use the model only if `ANTHROPIC_API_KEY` is already set in the environment.
  - Stop the server afterwards.
- `git status` is clean, and `git log --oneline main..HEAD` shows a sequence of small commits.

## Report back
Keep it short:
- the commit list
- what was verified, with the key curl output, trimmed
- anything you could not verify
- API quirks you found
- open questions for Dani
````

</details>

The only edit to the prompt above is the redacted API password. It is the public wazuh-docker default, but a password in a tracked file is still a password in a tracked file, and `CLAUDE.md` forbids it.

---

## 2026-10-29 — Entry 3: decisions made by the subagent during the build

Short notes on choices the subagent made on its own, so Dani can review them.

### Order of work

Agent setup first (`CLAUDE.md`, the two subagents), then this log and ADR 0001, then code, one module per commit with its tests in the next commit. Docs that describe behaviour (README endpoints and settings) went into the same commit as the code they describe.

### The prompt in Entry 2 is redacted in one place

The prompt contained the Wazuh API password. It is the public `wazuh-docker` default, but `CLAUDE.md` forbids secrets in tracked files, so the log shows `<redacted: wazuh-docker default>` instead. Everything else is verbatim.

### SCA is empty on the lab agent: design for the gap, do not hide it

**Finding.** `GET /sca/001` returns zero policies. The agent runs Ubuntu 26.04.1 LTS. Wazuh 4.14.9 ships no CIS policy for 26.04, so the agent is configured with `cis_ubuntu22-04.yml` and skips it, because the policy's "Check Ubuntu version" requirement fails. Waiting will not change this.

**What the subagent found on top of that.** The server API can show the cause without reading the agent's log. `GET /agents/001/config/wmodules/wmodules` returns the agent's live SCA configuration, which lists `/var/ossec/ruleset/sca/cis_ubuntu22-04.yml`. The service compares that file name with the policy ID it would expect for the agent's OS (`cis_ubuntu26-04`) and states the mismatch in the brief.

**How the design handles it.**

| Concern | Handling |
|---|---|
| A brief with no SCA findings looks like a clean host | The coverage gap is computed by rule, not by the model, and says "a clean brief here means 'not checked', not 'compliant'". Confidence is `low`. The first fix is to restore SCA coverage. |
| The brief still has to be useful | Two more sources, both read-only server API: recent FIM entries (`/syscheck`) and listening ports (`/syscollector/{id}/ports`). On the lab this produces an SSH exposure fix, because port 22 listens on all interfaces. |
| The SCA path must still work | Fully implemented and tested with fixtures synthesized from the Wazuh 4.14 API reference for a made-up Ubuntu 24.04 agent `002`. `app/tests/fixtures/README.md` says which fixtures are synthesized. |
| Is the synthesized shape right? | The manager (agent `000`, Amazon Linux 2023) does have real SCA results in the lab. Its failed checks have the same fields as the spec examples, and a live `GET /agents/000/brief` ran the whole SCA path on real data (46 failed checks, confidence `high`). The UI still hides `000`; the API accepts it. |

When Dani adds an Ubuntu 24.04 agent, it should get real SCA results with no code change.

### Model choice and call shape

The `claude-api` skill was loaded before `llm.py` was written. The prompt asked for a current Sonnet-class model, so the default is `claude-sonnet-5-5`, overridable with `LLM_MODEL`. Per the skill:

- JSON output through `output_config.format` with a JSON schema; the result is validated again with pydantic.
- `effort: medium`, `max_tokens` 6000 (thinking counts against it), no `temperature` (rejected on current models).
- `fallbacks: "default"` with beta `server-side-fallback-2026-07-01`, so a safety-classifier refusal is retried server-side on another model. Sent only for models that accept it.
- SDK retries are off (`max_retries=0`) and the call is wrapped in a hard timeout. A slow or failing model call falls back to the mock instead of making the page wait.

None of this was exercised against the real API: no `ANTHROPIC_API_KEY` was set in the subagent's environment. The request shape is covered by a unit test with a fake client.

### The mock is a real ranking, not a placeholder

`MockSummarizer` scores candidates on one documented scale (in `llm._Candidate`): missing SCA coverage, then world-writable sensitive files, then failed SCA checks weighted by keyword (SSH, authentication, firewall, privileges, audit), MITRE mapping and SSH exposure, then changed sensitive files, then exposed ports. The same weights pre-rank failed checks before the top 60 go to Claude, so on a host with hundreds of failures the model sees the relevant ones.

### FIM quirk: symlinks look world-writable

The lab FIM data reports `/etc/systemd/system/multi-user.target.wants/wazuh-agent.service` with `perm: rwxrwxrwx`. It is a symlink (43 bytes, empty-file hashes) reported with `type: file`. The world-writable rule ignores the exact value `rwxrwxrwx` to avoid flagging every systemd link.

## 2026-10-29 — Entry 4: follow-up, a dev-only path to real model output

After the first report, Dani answered the open questions and asked for one more piece of work, through the main session. The answers: keep the password redacted in this log; keep `/agents/000/brief` and `include_manager`; keep `claude-sonnet-5-5` as the API default; keep the stale cache for "unreachable" only, with a 502 on auth errors.

The new work: Dani has no API budget, so every brief so far came from the mock. The follow-up adds a summarizer that runs the same prompt through the Claude Agent SDK on his own Claude Code login, for development only. This is the message the subagent received, unchanged:

<details>
<summary>Follow-up prompt for the subagent</summary>

````text
Follow-up from the main session. Dani approved this; same worktree (/Users/dani/Desktop/projects/wazuh-hub-task-phase2), same branch, same hard rules, commit conventions (signed, small, Co-Authored-By line), no push.

Decisions on your open questions: (1) keep the password redacted in the agent log; (2) keep /agents/000/brief and include_manager as they are; (3) claude-sonnet-5-5 stays as the API default; (4) stale cache only on unreachable, 502 on auth: keep.

New work: Dani has no API budget. Add a DEV-ONLY summarizer that runs the same prompt through the Claude Agent SDK using his local Claude Code login (no API key).
- Package: `claude-agent-sdk` (Python). Read its current docs first (https://code.claude.com/docs/en/agent-sdk/python and the quickstart) for the exact API; do not guess signatures.
- `ClaudeCodeSummarizer` in llm.py (or a sibling module): same system prompt, same input payload and same output schema as `ClaudeSummarizer`; no tools allowed (empty allowed tools / tools disabled), single turn, no access to the filesystem or project settings beyond what the SDK requires; parse and validate the JSON result with the existing pydantic models. Response `source: "claude-code"`.
- Selection: new setting `LLM_PROVIDER` = `auto` (default) | `anthropic` | `claude-code` | `mock`. `auto` keeps today's behaviour (API key -> anthropic, else mock). `claude-code` is opt-in only, never chosen automatically. Any failure (SDK not installed, CLI not found, not logged in, timeout, invalid JSON) falls back to the mock with a clear `fallback_reason`. Put the SDK in an optional dependency group/extra if that keeps the default install light; your call, document it.
- Tests with a fake SDK client: happy path, invalid JSON -> mock, SDK error -> mock, provider selection matrix. CI must not need a login or key.
- Docs: `.env.example`, README quickstart (how to try the dev path), CLAUDE.md module map, a new ADR `0002-dev-only-agent-sdk-summarizer.md` (context: no API budget; decision: dev-only adapter on the developer's own login; consequences: never shipped, production uses API key; quote the Agent SDK docs note: "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK."), and an agent-log entry with this message verbatim in a <details> block.
- Live check: run the server with `LLM_PROVIDER=claude-code` against the lab and call `/agents/001/brief` and `/agents/000/brief` once each. Save one real response (trimmed, no tokens/secrets) as `docs/examples/brief-000-claude-code.json` and the mock version of the same agent as `docs/examples/brief-000-mock.json` so reviewers can compare. Keep live calls to those two plus at most one retry. If the Claude Code CLI is not reachable from your shell (PATH: try `which claude`, and `$HOME/.local/bin`, mise shims), report it instead of working around auth.
- Then: ruff check, ruff format --check, pytest all green, git status clean.

Report back briefly: commits, test count, live result (source + first two fixes for 000), and anything unverified.
````

</details>

Decisions the subagent made while doing it:

| Question | Decision | Why |
|---|---|---|
| Where the code goes | A sibling module, `llm_claude_code.py`, imported only when `LLM_PROVIDER=claude-code` | Keeps `llm.py` free of the SDK, and an install without the extra never imports it |
| Packaging | Optional extra `claude-code` | The SDK wheel bundles the Claude Code CLI, about 260 MB. CI and the default install skip it. |
| "No tools" | `tools=[]`, which the SDK turns into `--tools ""` (checked in the SDK source), plus `allowed_tools=[]` | Removes every built-in tool from the model's context, not only from auto-approval |
| "No settings" | `setting_sources=[]`, `--strict-mcp-config`, `--disable-slash-commands`, `--no-session-persistence`, and an empty temporary `cwd` | No `CLAUDE.md`, no user MCP servers, no skills, and nothing written to the session history |
| Structured output | Schema in the system prompt and pydantic validation, not the SDK's `output_format` | The docs say `output_format` adds a `StructuredOutput` tool call. That needs a tool and a second turn, and the brief asked for neither. |
| Timeout | At least 120 s on this path | It starts a CLI process per call, so the API path's 45 s is too tight |
| Fallback reason | Prefixed with the summarizer that failed (`claude-code: ...`, `claude: ...`) | With two model paths, the reason has to say which one failed |
