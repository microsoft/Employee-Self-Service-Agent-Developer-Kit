# Backup Template Configs Skill

Capture the customer's ESS Workday HCM template config customisations before
they install a new ESS Workday HCM package release. The script writes a
portable JSON file; pair with `/restore-template-configs` after the package
update to put the customisations back.

Auto-discovers ESS HR / IT / DA-HR / DA-IT agent flavours installed in the
env. The customer does not pick which agent — the script picks up whatever
`msdyn_*WorkdayHCMReferenceData_*` records are present.

Every **Message** block is the exact text to show the user. Copy it
verbatim. Do not rephrase, add commentary, or tell the user what tools you
are calling.

---

## Start

Read `.local/config.json` to confirm setup is complete and get the
`dataverseEndpoint`.

If setup is not complete, show:

**Message:**

You need to run `/setup` first before backing up template configs.

**End message.**

Stop here.

If setup is complete, proceed.

---

## Step 1: Confirm intent

**Message:**

About to back up your ESS Workday HCM reference-data template configurations.

I'll capture every `msdyn_*WorkdayHCMReferenceData_*` record in your
environment so you can restore them after installing a new ESS Workday HCM
package release.

The backup file will be written under
`workspace/template-config-backups/` and is gitignored by default.

Note: the backup contains your env's reference-data records (the values
you've customised to match your Workday tenant). Treat the file as
customer data — keep it on your machine or in a secure location, don't
check it into a shared repo. If you pass `--output` to point at a custom
path, make sure that path is also outside any tracked location.

**End message.**

Use `vscode_askQuestions`:

```json
[
  {
    "header": "Confirm",
    "question": "Run the backup now?",
    "options": [
      { "label": "Yes — back up now", "recommended": true },
      { "label": "Cancel" }
    ],
    "allowFreeformInput": false
  }
]
```

If they pick **Cancel**, show:

**Message:**

Cancelled. Run `/backup-template-configs` whenever you're ready.

**End message.**

Stop here.

---

## Step 2: Run the backup

**Message:**

Running backup — this takes a few seconds for a typical env (more if many
agent flavours are installed).

**End message.**

Run in the terminal, passing the `dataverseEndpoint` value from
`.local/config.json` as `--url`:

```
python scripts/backup_template_configs.py --url <dataverseEndpoint> --yes
```

The `--yes` flag is correct here because the user already confirmed in
Step 1 — the script's own pre-flight prompt would be a duplicate.

Wait for the script to finish. Capture the path it prints in the final
"Backup complete: ... -> <path>" line. You'll show it to the user in
Step 3.

If the script exits non-zero:
- Exit code 1: print the script output (it includes a friendly error
  message) and stop. Do not retry — the user needs to act.
- Exit code 2: the env has no matching records. Show the message in
  Step 3b (no records) and stop.

---

## Step 3: Show the result

### 3a — Successful backup

Build and show:

```
Backup complete.

| | Value |
|---|---|
| Records captured | {recordCount} |
| Agents detected  | {agentsDetected joined by ", "} |
| Output file      | {output_path} |

When you're ready, install the new ESS Workday HCM package as usual. After
that finishes, run `/restore-template-configs` and point it at this file to
put your customisations back.
```

Pull `recordCount`, `agentsDetected` (e.g., `HR, IT`), and `output_path` from
the script's stdout (the summary block and the final "Backup complete" line).

Stop here. Do not add commentary after this block.

### 3b — No records found (exit code 2)

Show:

```
No ESS Workday HCM template configs were found in this environment.

Confirm the ESS Workday HCM solution is installed in
`{dataverseEndpoint}` and that you're signed in with an account that can
read the `msdyn_employeeselfservicetemplateconfigs` table. Then re-run
`/backup-template-configs`.
```

Stop here.

---

## Notes for future maintainers of this skill

- The backup script is purely a read operation (`query_all`) so there is no
  401-retry helper needed. The auth flow reuses `auth.authenticate()` and
  picks up the existing token cache; the user typically does not see a
  browser prompt.
- The script's default output path uses an env-slug + UTC stamp — no risk
  of two runs overwriting each other.
- Backup files contain no secrets, but they DO contain the raw XML of every
  reference-data template config. Treat them as customer-data, not as code.
