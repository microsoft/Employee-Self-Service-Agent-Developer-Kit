<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# DA-4 — Review Your Workday Configuration

Role: **Environment Maker**. This step reviews everything the earlier steps
verified, re-confirms the extension package is still installed, and gives an
honest summary of what this skill does — and does not yet — check about the
live Workday connection. It owns master-checklist row **DA4.1** (a
programmatic row that completes only after the package recheck passes).

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading.

---

## DA4.1 — Review your Workday configuration

**Re-confirm the extension package.**

```
python scripts/flightcheck/cli.py --checkpoint WD-DA-PKG-001
```

Show the result per [`shared/checklist-updater.md`](shared/checklist-updater.md)
§U.0.

If the current result is not `PASSED`, do not continue from the persisted
DA1.1 state:

- `FAILED` → update DA1.1 with `GATE="prog"`,
  `CHECKPOINT_RESULT="FAILED"` so it becomes `blocked`.
- `WARNING` / `SKIPPED` → update DA1.1 with `GATE="prog"` and that result so
  it becomes `in-progress`.

Tell the user the package must be restored or reverified, then return to the
orchestrator. Do not complete DA4.1.

**Summarize the Entra and tenant configuration recorded so far.** Read
`.local/connect/workday-da/config.json` and render what's known:

**Message:**

Here's where your Workday connection stands:

| Area | Status |
| --- | --- |
| Workday extension package | {✅/❌ from WD-DA-PKG-001} |
| Workday single sign-on (Entra) | {✅ if DA2.1–DA2.7 are all `done`, else "in progress"} |
| Workday tenant configuration | {✅ if DA3.1–DA3.4 are all `done`, else "in progress"} |

**End message.**

If any of DA1.1, DA2.1–DA2.7, or DA3.1–DA3.4 is not `done`, tell the user which
step to finish and stop here — do not present the connection as ready.

**If everything above is done, be transparent about what this skill has — and
has not — verified.** This skill confirms the extension package is installed and
your Entra/tenant configuration is in place. It does not yet run DA-scoped
checks against the Workday extension package's live connection references (the
Workday account sign-in, the Dataverse connection, the REST address, the cloud
flows, or the firewall allowlist) — those checks exist for the CEA Employee
Self-Service agent today (`WD-CONN-AUTH-001`, `DV-CONN-001`, `WD-REST-001`,
`WD-FLOW-*`, `WD-NET-001`) but are not yet built for the DA extension package.

**Message:**

Your Workday extension package, single sign-on, and tenant configuration are all
in place. One thing to know: this skill doesn't yet automatically verify the
live connection inside the extension package itself — things like the account
sign-in, the REST address, or your firewall allowlist. To finish confirming your
agent can reach Workday:

1. Open the [Power Apps maker portal](https://make.powerapps.com), select this
   environment, and confirm the Workday connection shows as **Connected**
   under **Connections**.
2. Try a Workday scenario with your agent (for example, checking a vacation
   balance) and confirm it returns real data.
3. If it doesn't, run
   `python scripts/flightcheck/cli.py --scope workdayda --connect-config ".local/connect/workday-da/config.json"`
   for the DA Workday report, or reach out to your Workday administrator to
   recheck the tenant configuration above.

**End message.**

Update **DA4.1** via [`shared/checklist-updater.md`](shared/checklist-updater.md)
with `STEP_ID="DA4.1"`, `GATE="prog"`,
`CHECKPOINT_RESULT="PASSED"`.

---

## Done

Return control to the orchestrator (`SKILL.md`) — every configuration row
should now be `done`.
