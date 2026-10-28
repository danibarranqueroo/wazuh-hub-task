# Lab

This lab runs the official [`wazuh-docker`](https://github.com/wazuh/wazuh-docker) single-node deployment, pinned to tag `v4.14.9`. The repository is cloned into `lab/wazuh-docker/`, which is gitignored: the upstream files are not copied into this repo.

| Component | Where it runs |
|---|---|
| Wazuh server (manager), indexer, dashboard | Docker Desktop on macOS (Apple Silicon) |
| Wazuh agent | Ubuntu VM in OrbStack |

The setup steps, what I tested and what I learned are in [`PHASE1.md`](../PHASE1.md).
