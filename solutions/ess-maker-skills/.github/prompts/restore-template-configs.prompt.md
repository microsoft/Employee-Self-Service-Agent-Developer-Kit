---
mode: agent
description: "Type Enter to restore Workday HCM template config customisations from a backup file"
---

# Restore Template Configs

**Setup-state check.** Read `.local/config.json`. If it does not exist, OR `setup` is not `"complete"`, show:

> Welcome to the ESS Maker Kit. Before running `/restore-template-configs`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

Read the skill instructions at `src/skills/restore-template-configs/SKILL.md`, then follow the steps in order.

The skill will:
1. List candidate backup files under `workspace/template-config-backups/` and let the user pick one (or paste a path).
2. Confirm intent and warn if the backup was captured from a different env URL (cross-env restore is OK, just worth confirming).
3. Run `python scripts/restore_template_configs.py --url ... --input ... --yes --force` and report results.

Restore overwrites the `msdyn_value` field on each matched record with the value captured in the backup. Records present in the backup but missing from the target env (e.g. an ESS agent was uninstalled) are skipped with a clear warning rather than treated as a failure. The restore is idempotent — re-running over a partially-restored env writes the same values again, so retries are safe.