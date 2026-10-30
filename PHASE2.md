# Phase 2: Agent Hardening Brief

> "I have hundreds of failed CIS checks. What do I fix first?"

A small service on top of my Wazuh lab. `GET /agents/{id}/brief` reads one agent's current posture through the Wazuh server API (agent info, failed SCA checks, recent FIM entries, listening ports) and returns the top five fixes: why each matters, the concrete remediation, the evidence, and a coverage note that says what the brief could not see. A single page at `/` lists the agents and shows the brief.

| To see | Go to |
|---|---|
| Run it | [README quickstart](README.md#quickstart) |
| How it fits together | [`docs/architecture.md`](docs/architecture.md) |
| Real output, model vs. rules | [`docs/examples/`](docs/examples/) |
| Decisions | [ADR 0001](docs/adr/0001-phase2-stack-and-shape.md), [ADR 0002](docs/adr/0002-dev-only-agent-sdk-summarizer.md) |
| How the AI agents were directed | [`docs/agent-log.md`](docs/agent-log.md), [`docs/workflow.md`](docs/workflow.md) |

## 1. How did you approach it, and how did you use AI to build it?

**Approach.** I wanted something small that answers a real question for whoever runs Wazuh: CIS results are long lists, and the hard part is deciding what to fix first. So the service reads only current state from the server API, ranks it, and says clearly what it could not check. The plan and the decisions behind it are in [`docs/plan.md`](docs/plan.md). The stack choice (FastAPI, server API only, Claude with a rule-based fallback) is in [ADR 0001](docs/adr/0001-phase2-stack-and-shape.md).

**How I used AI.** Heavily, and on purpose in a way that leaves a trail:

- I made the plan with Claude Code in plan mode before touching the lab or the code.
- I set up the agents before any code: [`CLAUDE.md`](CLAUDE.md) with the conventions and hard rules, and two subagents, [`reviewer`](.claude/agents/reviewer.md) and [`docs-keeper`](.claude/agents/docs-keeper.md). That is the first commit of Phase 2.
- I delegated the Phase 2 groundwork to a background subagent in an isolated git worktree, so I could do Phase 1 by hand at the same time while the main session stayed free for my questions. Every prompt it received is in the [agent log](docs/agent-log.md), verbatim.
- The first launch went wrong: worktree isolation follows the session's current directory, which was inside the upstream `wazuh-docker` clone, so the worktree belonged to the wrong repository. The subagent stopped without writing anything. We removed the stray worktree, created the right one explicitly and relaunched. Now I always check which repository a worktree belongs to ([Entry 1](docs/agent-log.md#2026-10-29--entry-1-first-delegation-lands-in-the-wrong-repository)).
- I have no API budget, so at first every brief came from the rule-based mock. To see real model output during development I added a dev-only path through the Claude Agent SDK on my own Claude Code login. It is opt-in, has no tools and no access to the project, and never ships. Production uses an API key ([ADR 0002](docs/adr/0002-dev-only-agent-sdk-summarizer.md)). This is the same pattern as [Prowler Studio](https://github.com/prowler-cloud/prowler-studio), whose rewrite to the Agent SDK I co-authored ([#83](https://github.com/prowler-cloud/prowler-studio/pull/83)). It is internal developer tooling that each engineer runs on their own machine and Claude Code login. Here it is the same idea, scoped down to a single call ([workflow.md](docs/workflow.md#precedent-prowler-studio)).

**What I decided and what the agents did.**

| Decision | Who |
|---|---|
| Stack: FastAPI, Wazuh server API only, Claude with a mock fallback | Me, in the plan |
| `claude-sonnet-5-5` as the API default | Me, in the plan |
| `LLM_PROVIDER` with `claude-code` opt-in only | The main Claude session proposed it, I approved it |
| Redact the API password in the logged prompt, even though it is the public wazuh-docker default | The agent proposed it, I kept it |
| Keep agent `000` (the manager) reachable through the API but hidden in the page | Me |
| Design for the empty SCA result on Ubuntu 26.04 instead of hiding it | The main Claude session proposed it after reading the agent log, I approved it; the subagent found the API call that proves the cause |
| Code, tests, fixtures, CI, docs | The subagent, in small signed commits that I review before merging |

**What review caught.** Both came from reading real output, not from tests:

- The model flagged `/usr/bin/sh` as a world-writable shell. It is a symlink, and Wazuh reports links as `rwxrwxrwx`. Fixed in `04463ee` by marking likely symlinks in the model input.
- On agent `001` the model read the dates from FIM's first scan as recent changes ("verify the account-file changes from 11:40 UTC"), although its own coverage note said FIM is a baseline only. **Still open.**

**AI in Phase 1.** I installed the lab by following the Wazuh docs, and I wrote [`PHASE1.md`](PHASE1.md) myself. In Phase 1, I used AI only to get past three problems I could not solve from the docs:

- **The certificates on macOS.** The generator makes its output folder read-only and only then copies `root-ca.pem` to `root-ca-manager.pem`. On Linux, root ignores the read-only bit. On Docker Desktop for Mac, the bind mount enforces my user's permissions, so the copy fails. The script does not stop on errors, so the failure only shows when `docker compose up` cannot mount the file. The same output also shows `find: command not found`, a separate and harmless gap in the generator image. The Docker guide does not mention macOS.
- **The reserved `admin` user.** The dashboard cannot change its password. Changing it takes a new hash in `internal_users.yml` and a `securityadmin.sh` reload, because the indexer only reads that file on its first start.
- **`nano` would not start in the VM.** Ghostty sets `TERM=xterm-ghostty`, which Ubuntu does not know.

After writing `PHASE1.md`, I also used AI to rewrite some parts and to correct typos. The note at the end of that file says so.

One more finding came from Phase 2, not Phase 1. My agent has no SCA results, because Wazuh 4.14.9 has no CIS policy for Ubuntu 26.04 and the agent skips the 22.04 policy. That shaped the brief's coverage note.

## 2. If users gave you feedback on it, how would you handle it?

- **Collect it where the brief is read:** thumbs up/down on each brief, with an optional comment. Store it with the brief's `source`, model and prompt version (future work: today there is no feedback button and the prompt is not versioned).
- **Triage weekly.** Most complaints will be one of three things: wrong ranking, a wrong fact, or a missing data source. Each goes to a different place: weights in `posture.py`, the model input or prompt, or a new Wazuh call.
- **Turn bad briefs into eval cases.** The two review catches above are exactly the kind of case I'd add: the real `BriefInput` plus a checkable property ("does not report a symlink as world-writable"). A new prompt version must pass the eval set before a feature flag rolls it out to some customers ([saas-target.md, prompt quality](docs/saas-target.md#prompt-quality)).
- **Close the loop** with the user who reported it once the change ships.

## 3. If users report that the service is down, how would you be ready to respond?

What exists today:

- `GET /healthz` (the process is up) and `GET /readyz` (an authenticated Wazuh call works). Together they tell "our service is down" apart from "Wazuh is down".
- Clear errors: 503 `wazuh_unavailable`, 502 `wazuh_auth_failed`, 404 `agent_not_found`, all JSON with a `detail`.
- A [runbook](docs/runbook.md) with symptoms, checks and actions for Wazuh down, Wazuh auth failing, model down or slow, bad model output, and the service itself down.

What I'd add before real users (none of this exists yet):

- External uptime checks on `/healthz` and `/readyz`, and alerts that page an on-call person, with SLO burn-rate alerts rather than one alert per error.
- A status page with one component per dependency, so customers see "the model provider is degraded, briefs use rules" without opening a ticket.
- Deploys with a one-click rollback to the previous image, because most outages follow a change.

## 4. How would you prepare it for a failure, for example when the Wazuh API or the model is down?

Already in the code:

| Failure | Handling |
|---|---|
| Wazuh slow or flaky | Timeout per request, retry with exponential backoff on connection errors, 429 and 5xx ([`wazuh_client.py`](app/src/wazuh_brief/wazuh_client.py)) |
| Wazuh token expired | JWT cached until shortly before it expires, one fresh login on a 401 |
| Wazuh down | Serve the last brief for that agent with `"stale": true`, or a 503 with a clear message if there is none |
| Wazuh credentials wrong | 502 `wazuh_auth_failed`; deliberately not hidden behind the stale cache |
| Model down, slow, refusing or returning bad JSON | Hard timeout, then the rule-based `MockSummarizer` writes the brief from the same input; `source` and `fallback_reason` say so ([`llm.py`](app/src/wazuh_brief/llm.py)) |
| No SCA policy for the OS | Coverage gap computed by rule, confidence `low`, "not checked" instead of "clean" |

All of these paths have tests, and none of the tests needs the lab or a key.

What I'd add: a circuit breaker in front of Wazuh and the model, so a dead dependency is not retried on every request; a queue and workers so briefs are generated off the request path; and a shared cache, so a restart does not lose the stale copies ([saas-target.md](docs/saas-target.md#async-generation)).

## 5. If it grew into a full service with more features and more customers, how would you keep the design integrated?

The target is drawn in [`docs/saas-target.md`](docs/saas-target.md). The parts that keep it integrated:

- **Multi-tenancy from day one:** a tenant ID on every request, set by the gateway; Wazuh credentials per tenant in a secret manager; the tenant ID on every cache key, row, trace and log line. Adding it later means touching everything.
- **One shared Wazuh client.** Today's `wazuh_client.py` becomes a library every feature uses, so retries, auth and typed errors behave the same everywhere.
- **One contract.** FastAPI already generates the OpenAPI schema from the pydantic models (`/openapi.json`, `/docs`). I'd publish it and check changes to it in CI, so the UI and other services build against the same contract.
- **ADRs for every decision that crosses a module**, like the two in [`docs/adr/`](docs/adr/), so new people (and agents) know why things are the way they are.
- **The same pattern for every AI feature:** compute the facts by rule, send the model a small payload, validate its output, keep a deterministic fallback, and record `source`.

## 6. How would you document it, and how would you make sure every change is backed by up-to-date documentation?

How it is documented now:

| Doc | For |
|---|---|
| [README](README.md) | Quickstart, settings, endpoints, errors, the response fields |
| [`docs/architecture.md`](docs/architecture.md), [`docs/workflow.md`](docs/workflow.md) | How it fits together and how I work |
| [`docs/adr/`](docs/adr/) | Why: one ADR per decision |
| [`docs/runbook.md`](docs/runbook.md) | What to do when something breaks |
| [`docs/agent-log.md`](docs/agent-log.md) | How the agents were directed, including every prompt |
| [`app/tests/fixtures/README.md`](app/tests/fixtures/README.md) | Which fixtures are real captures and which were synthesized from the API reference |
| `/docs` on the running service | OpenAPI, generated from the code |

How it stays up to date:

- **The rule is in [`CLAUDE.md`](CLAUDE.md):** docs change in the same commit as the code they describe. Every agent reads that file, so it applies to agent work as well as mine.
- **The [`docs-keeper`](.claude/agents/docs-keeper.md) agent** compares the README, `.env.example` and `docs/` with the code (settings, routes, models, commands) and lists mismatches before a branch is pushed.
- **Generated where possible:** the API reference comes from the code, so it cannot drift.
- **Not yet built:** a CI docs check. I'd add a job that fails when a setting in `config.py` is missing from `.env.example` and the README, or when a route is missing from the README, plus a link checker for `docs/`. Today this is done by the `docs-keeper` agent and by review, not enforced by CI.
