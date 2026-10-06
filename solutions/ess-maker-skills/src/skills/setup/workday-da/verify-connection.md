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

If the maker selects **No**, stop before publishing. Ask what failed, show only
the remediation relevant to that observed surface, and repeat the maker smoke
test after the issue is corrected. Do not start an employee evidence window or
ask a non-maker employee to test.

If the maker selects **Yes**, write this safe evidence to
`.local/connect/workday-da/maker-validation.json` using a structured file-write
tool:

```json
{
  "testUserCategory": "maker",
  "timestamp": "{timezone-qualified current timestamp}",
  "outcome": "passed"
}
```

Then run:

```powershell
python scripts/workday_connect.py record-validation --evidence-file ".local\connect\workday-da\maker-validation.json"
```

The controller marks the guided lifecycle complete immediately. It also clears
any earlier pending validation attempt. Do not run `begin-employee-test`, wait
for Power Automate run-history evidence, rerun final runtime correlation, or
ask the maker or employee to repeat a successful scenario.

## Finish with post-skill next steps

After the controller returns `lifecycleComplete: true`, tell the maker:

> Workday setup is complete, and the maker Test pane scenario passed.
>
> **Next steps:**
>
> 1. Publish and deploy the agent when ready.
> 2. Have each non-maker employee establish their own Workday connections in
>    Microsoft 365 Chat.
> 3. Validate an enabled Workday scenario with the published agent.

Do not wait for those results, record them as lifecycle evidence, or keep the
Workday skill open. They are deployment and adoption validation outside this
guided setup lifecycle.
