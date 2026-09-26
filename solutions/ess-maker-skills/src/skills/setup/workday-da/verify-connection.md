<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# DA-5 — Validate Workday Readiness

Role: **Environment Maker** with a signed-in Workday test user. This step
re-confirms the extension package, reviews every setup area, and requires a
real Workday scenario before the environment is marked ready. It owns
master-checklist row **DA5.1**.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading.

---

## DA5.1 — Validate a signed-in Workday scenario

**Re-confirm the extension package.**

```
python scripts/flightcheck/cli.py --checkpoint WD-DA-PKG-001 --connect-config ".local/connect/workday-da/config.json"
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
orchestrator. Do not complete DA5.1.

**Summarize the Entra and tenant configuration recorded so far.** Read
`.local/connect/workday-da/config.json` and render what's known:

**Message:**

Here's where your Workday connection stands:

| Area | Status |
| --- | --- |
| Workday extension package | {✅/❌ from WD-DA-PKG-001} |
| Workday single sign-on (Entra) | {✅ if DA2.1–DA2.7 are all `done`, else "in progress"} |
| Workday tenant configuration | {✅ if DA3.1–DA3.4 are all `done`, else "in progress"} |
| Power Platform and agent integration | {✅ if DA4.1–DA4.8 are all `done`, else "in progress"} |

**End message.**

If any of DA1.1, DA2.1–DA2.7, DA3.1–DA3.4, or DA4.1–DA4.8 is not `done`,
tell the user which step to finish and stop here — do not present the
connection as ready.

**Message:**

The configuration checklist is complete. Now validate the actual employee
path:

1. Publish the ESS HR agent.
2. Share the published agent with a test employee who is not the maker who
   created the Workday connection.
3. Confirm that employee is assigned to the Workday Entra application and has
   valid Workday access.
4. Sign in as that employee and start a new conversation so maker credentials
   and stale user-flow state are not reused.
5. Run one enabled, read-only Workday scenario, such as checking a vacation
   balance.
6. Confirm the agent identifies the signed-in employee and returns real
   Workday data without showing a **Connect**, consent, or additional sign-in
   prompt.

Did the scenario complete successfully?

**End message.**

On success, update **DA5.1** with `GATE="manual"`, `ACK=true` and structured
`ROW_EVIDENCE` in this shape:

```json
{
  "outcome": "PASSED",
  "provenance": "user-acknowledgement",
  "note": "Signed-in employee scenario completed with real Workday data.",
  "capturedAt": "<current UTC timestamp>",
  "scenario": {
    "scenarioName": "<safe category, for example vacation balance>",
    "testUserCategory": "non-maker assigned test employee",
    "nonMakerTestUserConfirmed": true,
    "agentSharedWithTestUser": true,
    "signedInUserConfirmed": true,
    "realWorkdayDataConfirmed": true,
    "connectionPromptObserved": false,
    "unexpectedSignIn": false,
    "testSurface": "<safe category, for example Microsoft 365 Copilot>",
    "completedAt": "<current UTC timestamp>"
  }
}
```

Never record the employee's name, email, Workday ID, credentials, prompt
contents, or returned Workday data. Do not write provider `status` directly.
The deterministic state helper fingerprints the current agent/environment
scope and derives `status: "ready"` only when every blocking row is done,
revalidation is complete, and this scenario evidence is valid. Return to the
orchestrator.

On failure, leave DA5.1 `in-progress`. Run
`python scripts/flightcheck/cli.py --scope workdayda --connect-config ".local/connect/workday-da/config.json"`
to recheck the environment and DA package. That scope does not prove the live
connection, flow authorization, employee-context wiring, or topic execution,
so also revisit the DA4 connection, flow, authorization, topic, and firewall
evidence. If connection parameters recently changed, reconnect the Workday
connection and retry with a fresh conversation or test user.

---

## Done

Return control to the orchestrator (`SKILL.md`) — every configuration row
should now be `done`.
