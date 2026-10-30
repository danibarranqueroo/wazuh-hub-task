# Demo video

[`brief-demo.mp4`](brief-demo.mp4) is a 60-second screen recording of the page against the live lab on 2026-10-30. It is 1280×720 and about 12 MB, re-encoded from the original recording.

| Time | What it shows |
|---|---|
| 0:00 | The agent list with `001` (`ubuntu-lab`, Ubuntu 26.04.1) and `002` (`ubuntu-noble`, Ubuntu 24.04.5). The `001` brief has low confidence because no CIS policy exists for 26.04. |
| ~0:05 | Selecting `002`. The loading state counts the seconds while the `claude-code` provider works, which takes about 40 s here. |
| ~0:45 | The `002` brief: five fixes grouped from 98 failed CIS checks, with evidence and references, then the coverage panel with high confidence |

It was recorded with `LLM_PROVIDER=claude-code`, the dev-only path on my own Claude Code login ([ADR 0002](../adr/0002-dev-only-agent-sdk-summarizer.md)), and the page in dark mode. The JSON for a run on the same agent is in [`../examples/`](../examples/README.md).
