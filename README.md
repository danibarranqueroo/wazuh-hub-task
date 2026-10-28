# Wazuh Hub — Software Engineer technical task

This repository holds my work for the Wazuh Hub team's technical task. The task has three phases:

| Phase | Topic | Where it lives |
|---|---|---|
| 1 | Get to know Wazuh: install a 4.x lab and explore it, without AI | [`PHASE1.md`](PHASE1.md), [`screenshots/`](screenshots/) |
| 2 | Build a small piece of a SaaS service on top of Wazuh, with AI | [`app/`](app/), [`docs/`](docs/), [`PHASE2.md`](PHASE2.md) |
| 3 | Present the work | Live conversation |

## Repository map

```
.
├── PHASE1.md        # Phase 1 write-up (written by hand, no AI)
├── PHASE2.md        # Phase 2 answers
├── screenshots/     # Screenshots of my lab, captioned in PHASE1.md
├── lab/             # Notes for the local Wazuh lab
├── app/             # Phase 2 service (added in Phase 2)
└── docs/
    ├── plan.md      # Work plan and the decisions behind it
    └── diagrams/    # Architecture and workflow diagrams
```

## Lab at a glance

- **Wazuh version:** 4.14.9, the latest stable 4.x release when the task started.
- **Server, indexer and dashboard:** the official [`wazuh-docker`](https://github.com/wazuh/wazuh-docker) single-node deployment, on Docker Desktop on an Apple Silicon Mac.
- **Agent:** an Ubuntu VM in OrbStack, enrolled with the Wazuh manager running in Docker.

The work plan is in [`docs/plan.md`](docs/plan.md). The commit history shows how the work progressed.
