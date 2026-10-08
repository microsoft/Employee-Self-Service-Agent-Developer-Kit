<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Phase 6 - Maker validation

This is the final guided Workday setup phase. It ends after the maker
successfully validates one enabled read-only Workday scenario in the Copilot
Studio Test pane. Publishing, deployment, and non-maker employee validation
are next steps outside this skill lifecycle.

The skill cannot perform the Test pane interaction on the maker's behalf. The
skill cannot publish or deploy the agent; those are post-skill next steps.

## Run the maker smoke test

Ask the maker to:

1. open **Employee Self-Service (HR)** in Classic Copilot Studio;
2. open a new Test pane conversation without publishing the agent;
3. use the maker's configured Workday connection to run one enabled read-only
   scenario, such as checking a vacation balance; and
4. confirm that the agent identifies the maker's Workday user and returns real
   Workday data without an unexpected repeated sign-in.

Use `vscode_askQuestions`:

```json
[
  {
    "header": "Maker smoke test",
    "question": "Did the Workday scenario succeed in the Copilot Studio Test pane?",
    "options": [
      { "label": "Yes, the Test pane scenario passed" },
      { "label": "No, the Test pane scenario needs remediation" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave the selection unset.
Do not mark the passing option as recommended.

If the maker selects **No**, stop before publishing and ask what failed. For
failures other than the exact Workday response `Task not authorized`, show only
the remediation relevant to that surface and repeat the maker smoke test after
the issue is corrected.

For `Task not authorized`, ask the maker for the name of the scenario that
failed. Ask the Workday administrator to correct the domain security policy
for that scenario, then collect the affected Workday security domain. Write
this safe evidence to
`.local/connect/workday-da/maker-authorization-remediation.json`:

```json
{
  "remediationId": "WD-E2E-006",
  "scenarioName": "{named scenario that failed}",
  "affectedDomain": "{Workday security domain corrected by the administrator}",
  "timestamp": "{timezone-qualified timestamp when the failure was observed}"
}
```

Run:

```powershell
python scripts/workday_connect.py record-validation-failure --evidence-file ".local\connect\workday-da\maker-authorization-remediation.json"
```

Then require the maker to retest that same named scenario. Do not accept a
different scenario as the retest. Do not start an employee evidence window or
ask a non-maker employee to test.

If the maker selects **Yes**, write this safe evidence to
`.local/connect/workday-da/maker-validation.json` using a structured file-write
tool:

```json
{
  "testUserCategory": "maker",
  "scenarioName": "{named scenario, required after Task not authorized remediation}",
  "timestamp": "{timezone-qualified current timestamp}",
  "outcome": "passed"
}
```

Omit `scenarioName` when no authorization remediation was required.

Then run:

```powershell
python scripts/workday_connect.py record-validation --evidence-file ".local\connect\workday-da\maker-validation.json"
```

The controller marks the guided lifecycle complete immediately. It also clears
any earlier pending validation attempt. Do not run `begin-employee-test`, wait
for Power Automate run-history evidence, rerun final runtime correlation, or
ask the maker or employee to repeat a successful scenario.

## Finish with post-skill next steps

After the controller returns `lifecycleComplete: true`, name the completed
realm from `activeTargetRealm` and render only the returned
`postSkillNextSteps`. Do not add Production employee-adoption steps to a
Development or Test completion.

For Development, tell the maker:

> Workday setup is complete in Development, and the maker Test pane scenario
> passed.
>
> **Next steps:**
>
> 1. Promote the agent from Development to Test when ready.
> 2. Return to Connect Workday and say that the agent was promoted to Test.

For Test, tell the maker:

> Workday setup is complete in Test, and the maker Test pane scenario passed.
>
> **Next steps:**
>
> 1. Promote the agent from Test to Production when ready.
> 2. Return to Connect Workday and say that the agent was promoted to
>    Production.

Only for Production, tell the maker:

> Workday setup is complete in Production, and the maker Test pane scenario
> passed.
>
> **Next steps:**
>
> 1. Publish and deploy the Production agent when ready.
> 2. Have each non-maker employee establish their own Workday connections in
>    Microsoft 365 Chat.
> 3. Validate an enabled Workday scenario with the published Production agent.

Do not wait for those results, record them as lifecycle evidence, or keep the
Workday skill open. They are deployment and adoption validation outside this
guided setup lifecycle.
