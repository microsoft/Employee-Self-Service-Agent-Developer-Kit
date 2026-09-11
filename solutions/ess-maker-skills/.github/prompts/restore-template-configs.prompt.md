---
mode: agent
description: "Type Enter to restore hybrid Workday template configs"
---

# Restore Template Configs

**Setup-state check.** Read `.local/setup/config.json`. If it does not have `schema_version: 1` and `status: "complete"`, show:

> Welcome to the ESS Maker Kit. Before running `/restore-template-configs`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

Read `src/skills/restore-template-configs/SKILL.md` and follow it. This command
is limited to the Dataverse-backed configuration retained by the hybrid
Workday extension. It must not invoke foundation setup or any retired
CEA/DA-Preview installer, bot-binding, or preferred-solution path.
