---
mode: agent
description: "Type Enter to check template-config backup availability"
---

# Backup Template Configs

**Setup-state check.** Read `.local/setup/config.json` and `.local/config.json`. If canonical state does not have `schema_version: 1` and `status: "complete"`, or local config does not have `setup: "complete"`, show:

> Welcome to the ESS Maker Kit. Before running `/backup-template-configs`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

Show:

> Template-config backup supported the retired Dataverse-based agent model and is no longer supported in this release.

and STOP.