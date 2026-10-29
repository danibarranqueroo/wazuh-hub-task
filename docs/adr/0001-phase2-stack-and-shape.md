# ADR 0001: Phase 2 stack and shape

- **Status:** accepted
- **Date:** 2026-10-29

## Context

Phase 2 asks for "a small piece of a SaaS service on top of Wazuh" that reads real lab data through the Wazuh API and uses AI on it. One screen, one endpoint or one script is enough. The model call may be stubbed.

The lab is Wazuh 4.14.9 single-node in Docker, with one Ubuntu agent. The server API (port 55000) exposes agents, SCA results, FIM (syscheck) state and Syscollector inventory. The indexer (port 9200) holds alerts, but reading it needs a second set of credentials and a different query language.

The time budget for the service is about two and a half hours, including tests and CI.

## Decision

| Topic | Choice |
|---|---|
| Shape | One FastAPI service with one JSON endpoint, `GET /agents/{id}/brief`, and one HTML page at `/`. No database, no queue, no build step for the page. |
| Language and tooling | Python 3.12+, `uv`, httpx, pydantic, pytest + respx, ruff. |
| Data source | **Wazuh server API only.** Agent info, SCA policies and failed checks, syscheck entries, and a small slice of Syscollector (OS, listening ports). No indexer access. |
| AI | Claude through the Anthropic SDK, asked for structured JSON with a bounded token budget. A deterministic, rule-based `MockSummarizer` produces the same response shape when there is no API key or the call fails. Every response says `"source": "claude"` or `"mock"`. |
| Failure handling | Typed Wazuh errors. If Wazuh is unreachable the endpoint returns 503, or the last brief for that agent from an in-memory cache, flagged `stale`. |

## Consequences

- **Good:** one credential set, one API, one client to test. The server API returns current state per agent, which is what a "what do I fix first" brief needs.
- **Good:** the service works and the tests pass without an API key. A reviewer can run it against their own lab without paying for tokens, and the output is still useful because the mock ranks findings by rule.
- **Good:** the model sees a small, curated JSON payload: check titles, rationale, remediation, file paths. No raw logs and no credentials leave the service.
- **Cost:** no alert history. The brief describes current posture, not recent attacks. Adding the indexer later would be a second client, not a rewrite.
- **Cost:** the in-memory cache is per process and lost on restart. Fine for a demo; a real service would use Redis or similar.
- **Cost:** SCA coverage depends on the agent's OS. Where no policy applies, the brief must say so instead of looking clean (see `docs/agent-log.md`).
