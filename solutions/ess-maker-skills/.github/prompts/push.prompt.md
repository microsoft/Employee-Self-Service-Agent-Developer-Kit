---
mode: agent
model: gpt6.1-sol
description: "Push local changes to Copilot Studio"
---

# Push

**Setup-state check.** Read `.local/setup/config.json` and `.local/config.json`.
If canonical state does not have `schema_version: 4` and an `agents` entry
matching the active workspace slug with `connect_ready: true`, show:

> Welcome to the ESS Maker Kit. Before running `/push`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

## Explicit evaluation push

If the request explicitly targets evaluation test sets, route before the
general-component instructions below. Discover/select the exact workspace or
current-agent set using `src/skills/evaluations/update/SKILL.md`, then follow
`src/skills/evaluations/deployment-flow.md` with helper action `push`.
Preserve existing review state; do not create a review request, mark review
complete, or start a run.
Use the existing backend APIs. Explain native `new_copy`/`reuse` behavior before
consent; a new copy gets a new deployed ID and retains the old remote copy.
Native review sidecars remain local, not shared review metadata. Follow the
shared guide's `reviewMetadataPersisted`/`reviewWarning` outcome rules rather
than adding an in-place-update or remote-review prerequisite.

This branch supports standalone evaluation push even though the normal maker
menu has no Push item. Method admission, target checks, selected-set scope,
dry-run visibility, and required destructive approval remain mandatory.
Use noninteractive execution only after the shared flow obtains chat approval;
its authorized `--yes` does not bypass that consent. Never launch an
interactive evaluation push waiting for unattended stdin.
If evaluation scope is ambiguous, ask rather than pushing all components.
Return after this branch; do not also execute the general push below.

After the shared deployment flow reports a verified successful deployment,
run the one-time DA post-deployment analytics reminder:

```
python scripts/analytics_pointer.py --post-deploy
```

Show any command output verbatim. The command is silent after the reminder has
already been completed for the current environment/agent association. Run it
only after deployment verification; do not show an analytics link after a
preview, cancellation, or failed deployment. If the resolver cannot build the
link, do not substitute the Copilot Studio home page.

## General component push

For a general component push, show:

> General component push for a DA-GA agent is not yet available in this release. No local or remote files have been changed.

and STOP. The explicit evaluation-push branch above remains available.

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