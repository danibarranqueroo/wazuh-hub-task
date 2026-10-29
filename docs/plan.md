# Work plan

The task brief expects about 6 hours of work and gives 24 hours to deliver. This plan was written before starting and is updated whenever a decision changes.

## Phases and time budget

| Step | What | Budget |
|---|---|---|
| 0 | Repo, tooling, version pinning | 20 min |
| 1 | Lab install, detections, settings changes, screenshots | 2 h |
| 1 | `PHASE1.md`, written by hand without AI | 30 min |
| 2 | Service: agent setup, Wazuh API client, AI summary, endpoint and screen, tests, CI | 2 h 30 min |
| 2 | Diagrams and `PHASE2.md` | 40 min |
| 3 | Demo script, final checklist, delivery | 20 min |

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Wazuh version | 4.14.9 | Latest stable 4.x tag on `wazuh-docker`. Its images have arm64 builds. |
| Where the server stack runs | Docker, using the official single-node compose | Reproducible and quick to tear down. The Wazuh OVA is x86-only and does not run on Apple Silicon. |
| Where the agent runs | Ubuntu VM in OrbStack | A real host with systemd, SSH and a filesystem, so detections such as SSH brute force and file integrity monitoring behave as they would in production. |
| Phase 2 stack | Python, FastAPI, httpx, pytest | Small, typed, quick to test. |
| AI in Phase 2 | Claude API, with a deterministic mock fallback | Real output when a key is set. The service keeps working when the model is unavailable. |
| Phase 2 data source | Wazuh server API only (agents, SCA, syscheck, a slice of syscollector) | One credential set and one client. Current posture is what a "fix first" brief needs. See ADR 0001. |

## Rules I am holding myself to

- Phase 1 is done without AI: the lab work, the screenshots and `PHASE1.md`.
- Commit as I go, in small steps, so the history shows how the work progressed.
- No secrets in the repo. Credentials go in `.env`, which is gitignored.

## Phase 2 outline

The Phase 2 idea is an **agent hardening brief**. The service reads one agent's failed configuration-assessment (SCA) checks, recent file-integrity changes and listening ports through the Wazuh server API. It then asks a model to rank the few fixes that matter most and explain them. It exposes one endpoint and one small screen.

The lab agent runs Ubuntu 26.04, which has no CIS policy in Wazuh 4.14.9, so it has no SCA results. The brief reports that as a coverage gap instead of a clean result, and the SCA path is tested with fixtures synthesized from the API reference. Details: [`agent-log.md`](agent-log.md), Entry 3.

Where the Phase 2 material lives:

| What | Where |
|---|---|
| Service, quickstart, endpoints | [`../README.md`](../README.md#phase-2-agent-hardening-brief), [`../app/`](../app/) |
| Stack decision | [`adr/0001-phase2-stack-and-shape.md`](adr/0001-phase2-stack-and-shape.md) |
| Agent setup | [`../CLAUDE.md`](../CLAUDE.md), [`../.claude/agents/`](../.claude/agents/) |
| How agents were directed | [`agent-log.md`](agent-log.md) |
| Diagrams | `diagrams/` (to be added) |
