# Restore Template Configs Skill

Re-apply ESS Workday HCM template config customisations from a backup file
produced by `/backup-template-configs`. Use this after installing a new ESS
Workday HCM package release, which would otherwise reset customised
reference-data records to the package defaults.

Records are matched by `msdyn_uniquename` (stable across envs), so the same
backup file can also be used to port customisations from dev to prod (warns
once, proceed-or-cancel).

Every **Message** block is the exact text to show the user. Copy it
verbatim. Do not rephrase, add commentary, or tell the user what tools you
are calling.

---

## Start

Read `.local/config.json` to confirm setup is complete and get the
`dataverseEndpoint`.

If setup is not complete, show:

**Message:**

You need to run `/setup` first before restoring template configs.

**End message.**

Stop here.

If setup is complete, proceed.

---

## Step 1: Pick the backup file

List candidate backup files in `workspace/template-config-backups/`:
- Glob: `workspace/template-config-backups/*.json`
- Sort newest first (by mtime).
- If the folder doesn't exist or is empty, show:

  **Message:**

  No backup files were found in `workspace/template-config-backups/`.

  Run `/backup-template-configs` first to capture your customisations, or
  copy a backup file from another machine into that folder and re-run
  `/restore-template-configs`.

  **End message.**

  Stop here.

Use `vscode_askQuestions` with the discovered files as options. Show the
most-recent two or three at the top with a `recommended: true` flag on the
newest. Include the filename, captured timestamp (read from each file's
`metadata.capturedAt`), and record count.

```json
[
  {
    "header": "BackupFile",
    "question": "Which backup file do you want to restore from?",
    "options": [
      { "label": "{filename}", "description": "Captured {capturedAt} — {recordCount} records", "recommended": true },
      { "label": "{older filename}", "description": "Captured {capturedAt} — {recordCount} records" }
    ],
    "allowFreeformInput": true
  }
]
```

Keep `allowFreeformInput: true` so the customer can paste a path to a
backup file they have outside the default folder.

Capture the selection as `{BACKUP_PATH}`.

---

## Step 2: Confirm intent and check env match

Read the chosen backup file to inspect `metadata.envUrl`, `metadata.capturedAt`,
`metadata.recordCount`, and `metadata.agentsDetected`. Also read the current
`dataverseEndpoint` from `.local/config.json`.

Build the summary:

```
Restoring from:
  File         : {BACKUP_PATH}
  Captured at  : {capturedAt}
  Source env   : {envUrl from backup}
  Records      : {recordCount} across {agentsDetected}

Restoring into:
  Target env   : {dataverseEndpoint from .local/config.json}

Note: restore overwrites the `msdyn_value` field on each matched record
with the value captured in the backup. Other fields on the record (name,
unique name, any future fields a newer package version may have added)
keep whatever the current package shipped. Microsoft does not edit the
catalog values in `msdyn_value`, so a full overwrite is the intended
behaviour - your customisations win.
```

If `metadata.envUrl` (in the backup) does NOT match `dataverseEndpoint`
(in the current config), show one additional line in the summary:

```
Note: Backup was captured from a different environment than the target.
This is fine for promoting customisations across envs (e.g. dev -> prod),
but worth confirming.
```

Use `vscode_askQuestions`:

```json
[
  {
    "header": "Confirm",
    "question": "Proceed with restore?",
    "options": [
      { "label": "Yes — restore now", "recommended": true },
      { "label": "Cancel" }
    ],
    "allowFreeformInput": false
  }
]
```

If they pick **Cancel**, show:

**Message:**

Cancelled. Re-run `/restore-template-configs` whenever you're ready.

**End message.**

Stop here.

---

## Step 3: Run the restore

**Message:**

Running restore — this takes 1-2 seconds per record. A typical multi-agent
env finishes in under a minute.

**End message.**

Run in the terminal:

```
python scripts/restore_template_configs.py --url <dataverseEndpoint> --input <BACKUP_PATH> --yes --force
```

- `--yes` skips the script's overwrite prompt (the user already confirmed
  in Step 2).
- `--force` skips the script's own cross-env-mismatch prompt (which would
  duplicate the Note in Step 2's summary if the envs differ; if they match,
  `--force` is a no-op).

Wait for the script to finish. Read its final summary line, which looks
like:

```
Restore complete: N restored, M skipped, K failed.
```

Capture `N`, `M`, `K`, plus exit code.

---

## Step 4: Show the result

### 4a — Full success (exit code 0, failed == 0)

Show:

```
Restore complete.

| | Count |
|---|---|
| Restored | {N} |
| Skipped (not in env) | {M} |
| Failed | 0 |

Your customisations are back. If `Skipped` is non-zero, those records came
from an agent installation that no longer exists in this env (e.g., a
solution was uninstalled). Re-install the missing solution(s) and re-run if
you need those records back.
```

Stop here. Do not add commentary after this block.

### 4b — Partial failure (exit code 4)

The script prints the first failure's full diagnostic at the end of its
output (status code, tip, URL, request id). Show:

```
Restore partially failed.

| | Count |
|---|---|
| Restored | {N} |
| Skipped (not in env) | {M} |
| Failed | {K} |

First failure detail:
```
{paste the "First failure detail" block from the script's stdout verbatim}
```

Follow the tip in the failure message. After fixing the underlying issue
(usually a permission gap, expired session, or transient throttling),
re-run `/restore-template-configs` — already-restored records will simply
overwrite with the same value, so re-running is safe.
```

Stop here.

### 4c — Hard failure (exit code 1)

The script exits 1 only when the backup file is unusable (missing,
unreadable, wrong schema version, no records). The script's stdout has the
specific reason. Show:

```
Restore failed before any records were written.

{paste the script's last few lines of stdout}

Fix the underlying issue (usually a stale or wrong backup file) and re-run
`/restore-template-configs`.
```

Stop here.

---

## Notes for future maintainers of this skill

- The script is idempotent: re-running over a partially-restored env writes
  the same values again. There is no state on the script side to clean up.
- `_call_with_refresh()` in the script handles 401 mid-restore by
  re-authenticating once and retrying. The customer may briefly see a
  "Access token expired" line; that is expected on multi-agent envs that
  take longer than one MSAL token lifetime to restore.
- The script does NOT support a `--dry-run` mode in v1. Showing what the
  PATCH would look like requires diff'ing each `msdyn_value` payload, which
  is out of scope for v1. If the customer asks "what will this overwrite",
  the answer is "every record listed in the summary, with the values that
  were in the backup at capture time."
