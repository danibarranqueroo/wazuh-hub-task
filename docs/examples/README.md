# Example briefs

Two real responses from `GET /agents/000/brief` against the lab on 2026-10-29. Agent `000` is the Wazuh manager (Amazon Linux 2023). It is the only agent in the lab with real SCA results (46 failed CIS checks), so it shows the full SCA path. The page hides it, but the API serves it.

| File | `source` | How it was produced |
|---|---|---|
| [`brief-000-claude-code.json`](brief-000-claude-code.json) | `claude-code` | `LLM_PROVIDER=claude-code`: the dev-only Agent SDK path on Dani's Claude Code login ([ADR 0002](../adr/0002-dev-only-agent-sdk-summarizer.md)), model `claude-sonnet-5-5` |
| [`brief-000-mock.json`](brief-000-mock.json) | `mock` | `LLM_PROVIDER=mock`: the rule-based `MockSummarizer` |

Both read the same Wazuh data and receive the same `BriefInput`. The responses are unedited apart from pretty-printing. They hold no tokens or credentials; the agent IP is the manager's loopback address.

What to compare:

| | Mock | Claude Code |
|---|---|---|
| Ranking | Fixed keyword weights; one failed check per fix | Groups related checks into one fix (password policy, audit rules, hygiene batch) |
| Exposure | Not raised: the manager listens on 1514, 1515 and 55000, but the mock rule only names SSH explicitly and ranks other ports low | Ranks a default-deny firewall in front of the Wazuh ports first |
| Coverage note | First two rule-computed gaps | Its own wording, built from the same gaps |

A known weakness, visible in fix 3 of the Claude Code brief: FIM reports `/usr/bin/sh` as `rwxrwxrwx`. That is how Wazuh shows a symlink, and on Amazon Linux `/usr/bin/sh` is a link to `bash`. The model hedged ("It may just be a symlink... verify before acting") but still ranked it. The input now marks such entries as likely links (see the `fix:` commit after this one). The example was captured before that change and is kept as it was.
