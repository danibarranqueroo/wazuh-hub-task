# CLAUDE.md

Guidance for Claude Code and any other agent working in this repository.

## What this repo is

My work for the Wazuh Hub team's technical task.

| Phase | What | Where |
|---|---|---|
| 1 | Wazuh 4.14.9 lab, explored by hand, **without AI** | `PHASE1.md`, `screenshots/`, `lab/` |
| 2 | Agent Hardening Brief: a small service that reads real data from the lab through the Wazuh server API and asks Claude for a prioritized brief | `app/`, `docs/` |

## Stack (Phase 2)

- Python >= 3.12, managed with `uv` (project in `app/`).
- FastAPI + uvicorn, httpx for the Wazuh API, pydantic and pydantic-settings, Jinja2 for the single HTML page.
- Anthropic Python SDK for the model call, with a deterministic mock fallback.
- pytest + respx for tests, ruff for lint and format.

## Commands

All Phase 2 commands run from `app/`.

| Task | Command |
|---|---|
| Install | `cd app && uv sync` |
| Tests | `cd app && uv run pytest` |
| Lint | `cd app && uv run ruff check` |
| Format | `cd app && uv run ruff format` |
| Run the server | `cd app && cp .env.example .env` (once, then fill it in), then `uv run uvicorn wazuh_brief.main:app --port 8000` |

On Dani's machine `uv` comes from mise and is missing from non-interactive shells. Prefix commands with
`PATH="$HOME/.local/share/mise/shims:$HOME/.docker/bin:$PATH"`.

## Conventions

- Code lives in `app/src/wazuh_brief/`, tests in `app/tests/`, fixtures in `app/tests/fixtures/`.

  | Module | Job |
  |---|---|
  | `config.py` | Settings from env / `app/.env` |
  | `wazuh_client.py` | Read-only Wazuh server API client, auth, retries, typed errors |
  | `posture.py` | Collects one agent's data, computes coverage gaps, builds the summarizer input |
  | `llm.py` | `Summarizer` protocol, `ClaudeSummarizer`, `MockSummarizer`, fallback |
  | `models.py` | Pydantic models: Wazuh items, summarizer input, the public `Brief` |
  | `main.py` | FastAPI routes and error mapping |
- Fixtures prefixed `live_` are captured from the lab; `docs_` are synthesized from the Wazuh API reference. Keep that split and update `app/tests/fixtures/README.md` when adding one.
- Type hints everywhere. Pydantic models for anything that crosses an HTTP boundary.
- Errors from the Wazuh API are mapped to typed exceptions (`WazuhUnavailable`, `WazuhNotFound`, ...) in `wazuh_client.py`. Endpoints translate them to HTTP status codes; nothing else catches bare `Exception`, except the summarizer fallback.
- Tests never need the live lab or an API key. HTTP is mocked with respx; the model is replaced with a fake.
- Commits are small and conventional: `feat:`, `fix:`, `test:`, `docs:`, `chore:`, `ci:`. One logical change per commit.
- **Docs are updated in the same change as the code.** If a commit changes behaviour, config or commands, the README, `CLAUDE.md` or `docs/` change in that commit too.
- Notable decisions get a short dated entry in `docs/agent-log.md`; architectural ones get an ADR in `docs/adr/`.
- All deliverables are in English. Style: plain and factual, tables where they help.

## Hard rules

- **Never create, open, edit or commit `PHASE1.md`, anything in `screenshots/`, or anything in `lab/`.** Phase 1 must stay AI-free.
- **Never commit secrets.** Credentials go in `app/.env`, which is gitignored. `app/.env.example` holds placeholders only.
- Never write a Wazuh JWT or API key to a file that could be committed. Strip tokens from fixtures.
- Against the lab, make **read-only GET calls only** (plus the login `POST /security/user/authenticate`). Do not change Wazuh config. Do not restart containers.
- Never send raw logs or credentials to the model. Send only the fields the brief needs.
- Git signing stays on (`commit.gpgsign=true`).
- Agents do not push and do not open pull requests. Dani reviews and pushes.
