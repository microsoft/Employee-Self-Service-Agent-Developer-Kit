---
mode: agent
description: "Type Enter to push local changes to your Copilot Studio agent"
---

# Push

**Setup-state check.** Read `.local/config.json`. If it does not exist, OR `setup` is not `"complete"`, show:

> Welcome to the ESS Copilot Kit. Before running `/push`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

Run a dry-run first so the user sees the exact diff before any mutation:

```
python scripts/push.py --dry-run
```

Show the dry-run output to the user. Then ask: "Push these changes to Copilot Studio? (yes/no)"

Only after the user answers `yes` (or `y`), run:

```
python scripts/push.py
```

Do NOT add `--yes` to the invocation. The script's interactive prompt is the second confirmation layer; bypassing it relies on the chat-side confirmation alone, which is brittle if the user did not actually intend to push.

If the diff includes deletions and the user has confirmed they want to delete, run with `--force-delete` so the script's destructive-op gate accepts:

```
python scripts/push.py --force-delete
```

The script will:
1. Compare your working files against the baseline (last known environment state)
2. Authenticate to Dataverse (re-uses cached credentials when possible)
3. Push each create / update / delete in dependency order
4. Update the baseline only after a fully-successful push (zero errors)

If the script reports any errors, the baseline is intentionally NOT updated so the next push retries the failed components. Do not pass `--yes` as a workaround - investigate the errors first.