# ADR 0002: Dev-only Agent SDK summarizer

- **Status:** accepted
- **Date:** 2026-10-29

## Context

ADR 0001 calls Claude through the Anthropic API with an API key, and falls back to a rule-based mock when there is no key. I have no API budget for this task, so every brief I could see during development came from the mock. That says nothing about the prompt, the schema or how the UI handles real model output.

I do have a Claude Code login. The Claude Agent SDK runs Claude Code as a library and can use that login. The SDK's quickstart is explicit about who may use it that way:

> Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK. Use the API key authentication methods described in this document instead.

So the login can serve me as a developer on my own machine. It cannot be what a product built on this service runs on.

This is not a new pattern for me. [Prowler Studio](https://github.com/prowler-cloud/prowler-studio), whose rewrite to the Agent SDK I co-authored ([#83](https://github.com/prowler-cloud/prowler-studio/pull/83)), is internal developer tooling that each engineer runs through the Agent SDK on their own Claude Code login. This adapter uses the same split: the developer's own login for tooling on their machine, an API key for anything that serves customers.

## Decision

Add `ClaudeCodeSummarizer` (`app/src/wazuh_brief/llm_claude_code.py`) as a **developer-only adapter** on the developer's own Claude Code login.

| Topic | Choice |
|---|---|
| Selection | New setting `LLM_PROVIDER`: `auto` (default) \| `anthropic` \| `claude-code` \| `mock`. `auto` keeps the ADR 0001 behaviour. `claude-code` is chosen only when set explicitly. |
| Same contract | Same system prompt, same `BriefInput` payload, same output schema, validated with the same `Draft` model. The response says `"source": "claude-code"`. |
| Isolation | No tools (`tools=[]`), one turn (`max_turns=1`), no user/project/local settings (`setting_sources=[]`), no MCP servers, no skills, no saved session, and an empty temporary working directory. The model gets the posture JSON and nothing else from the machine. |
| Structured output | The SDK's `output_format` is not used, because it works through an extra `StructuredOutput` tool call and a second turn. The schema goes in the system prompt and the reply is validated by pydantic. |
| Failure | SDK not installed, CLI not found, not logged in, process error, timeout (at least 120 s), or invalid JSON: fall back to the mock, with `fallback_reason` prefixed `claude-code:`. |
| Packaging | `claude-agent-sdk` is an optional extra (`uv sync --extra claude-code`). It bundles the Claude Code CLI, about 260 MB. The default install and CI do not include it, and tests use a fake SDK. |

## Consequences

- **Good:** I can see real model output for the real lab data without spending API money, and compare it with the mock (`docs/examples/`).
- **Good:** the API path, the mock and the response shape are unchanged. Removing the adapter means deleting one module, one extra and one branch in `select_summarizer`.
- **Rule:** this path is **never shipped**. Production uses `LLM_PROVIDER=auto` or `anthropic` with an API key. A deployment must not install the `claude-code` extra.
- **Cost:** the Claude Code path is slower than a direct API call: it starts a CLI process per brief.
- **Cost:** it does not exercise the API-only parts of `ClaudeSummarizer` (`output_config`, `effort`, server-side fallbacks). Those stay covered by unit tests only until someone runs with a key.
- **Cost:** outputs differ between paths. The Claude Code path has no `effort` control and runs inside the Claude Code harness, so its briefs are a good guide to the prompt but not identical to what the API path would produce.
