---
mode: agent
description: "Type Enter to back up your Workday HCM template config customisations before an ESS package update"
---

# Backup Template Configs

**Setup-state check.** Read `.local/config.json`. If it does not exist, OR `setup` is not `"complete"`, show:

> Welcome to the ESS Maker Kit. Before running `/backup-template-configs`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

Read the skill instructions at `src/skills/backup-template-configs/SKILL.md`, then follow the steps in order.

The script will:
1. Query every `msdyn_*WorkdayHCMReferenceData_*` record in the env (auto-discovers HR / IT / DA-HR / DA-IT agent flavours that are installed).
2. Write a portable JSON to `workspace/template-config-backups/<envslug>-<utc-stamp>.json` by default.

The backup file contains your env's customised reference-data records. Treat it as customer data — don't commit it to a shared repo. The default output folder is gitignored. If you pass a custom `--output` path, make sure it's also outside any tracked location.

Pair with `/restore-template-configs` after the ESS Workday HCM package update finishes.