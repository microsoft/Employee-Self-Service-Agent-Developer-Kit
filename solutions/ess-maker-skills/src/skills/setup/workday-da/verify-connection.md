<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Phase 6 - Employee validation

This phase requires a real signed-in employee scenario. Configuration checks
alone cannot complete it.

The skill cannot publish or deploy the agent, impersonate an employee, create
an employee's Workday connections, or perform either scenario on the user's
behalf. It guides the maker through both validation stages and records only
the safe final employee outcome.

## Maker smoke test before publishing

First ask the maker to:

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

Leave the selection unset. This smoke test does not complete Employee
validation and must not be recorded as non-maker evidence. If it fails, stop
before publishing, remediate the observed issue, and repeat the maker smoke
test.

## Non-maker employee validation after deployment

Only after the maker smoke test passes, ask the maker to publish the ESS HR
agent and complete the normal deployment or availability step for Microsoft
365 Chat.

Then ask the assigned non-maker Workday test employee to:

1. open the deployed ESS HR agent in Microsoft 365 Chat;
2. establish the required employee-owned Workday connections under the
   employee account, completing the expected first-use sign-in when prompted;
3. open a new conversation after those connections are ready; and
4. stop before sending a Workday scenario request.

Do not reuse the maker's connections or credentials for this stage.

When the employee is ready to send the scenario request, start a bounded test
attempt:

```powershell
python scripts/workday_connect.py begin-employee-test
```

The controller records only bounded, non-secret validation context. If the
command does not succeed, do not ask the employee to run the scenario. If the
test is interrupted or delayed, abandon the attempt without inventing an
employee failure classification:

```powershell
python scripts/workday_connect.py abandon-employee-test
```

Then start a new attempt immediately before retrying.

Then ask the maker to have the employee immediately:

1. run one enabled read-only scenario, such as checking a vacation balance;
2. confirm the agent identifies the signed-in employee and returns real
   Workday data without another unexpected sign-in.

Use `vscode_askQuestions` for the test result:

```json
[
  {
    "header": "Employee test result",
    "question": "What happened in the signed-in employee Workday test?",
    "options": [
      { "label": "Passed - employee identified and Workday data returned" },
      { "label": "Failed - repeated sign-in" },
      { "label": "Failed - connector error" },
      { "label": "Failed - flow error" },
      { "label": "Failed - employee mismatch" },
      { "label": "Failed - network error" },
      { "label": "Failed - Workday access denied" },
      { "label": "Failed - agent not published or unavailable" },
      { "label": "Failed - another issue" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave the result unset and do not mark the passing outcome as recommended. Do
not ask a second question about which scenario was used; the passing result
already confirms that an enabled read-only Workday scenario identified the
employee and returned real Workday data.

On success, record only the test-user category, timestamp, and outcome in
`.local/connect/workday-da/employee-validation.json`. Write the object using a
structured file-write tool rather than a generated shell command, then run:

```powershell
python scripts/workday_connect.py record-validation --evidence-file ".local\connect\workday-da\employee-validation.json"
```

Provide only `testUserCategory`, `timestamp`, and a passed or verified
`outcome`. Use a non-maker employee category and a timezone-qualified ISO-8601
timestamp. The controller accepts the legacy optional `scenarioName` field
but this skill does not collect it. It rejects all other fields. Never record
employee data or credentials.

On success, the controller freezes the bounded attempt, verifies the successful
reviewed runtime flow or flows actually exercised in that window, and evaluates
final readiness before marking the lifecycle ready. A single scenario is not
required to exercise both the main and REST runtime flows. Show any returned
customer-safe remediation without exposing internal profile or checkpoint
identifiers.

On failure, map the selected result to exactly one stable ID below. Do not
invent a remediation ID.

| Selected result                             | `remediationId` |
| ------------------------------------------- | --------------- |
| Failed - repeated sign-in                   | `WD-E2E-001`    |
| Failed - connector error                    | `WD-E2E-002`    |
| Failed - flow error                         | `WD-E2E-003`    |
| Failed - employee mismatch                  | `WD-E2E-004`    |
| Failed - network error                      | `WD-E2E-005`    |
| Failed - Workday access denied              | `WD-E2E-006`    |
| Failed - agent not published or unavailable | `WD-E2E-007`    |
| Failed - another issue                      | `WD-E2E-999`    |

For `WD-E2E-999`, ask where the failure was observed using this separate
structured choice:

```json
[
  {
    "header": "Failure surface",
    "question": "Where was the other issue observed?",
    "options": [
      { "label": "Agent chat" },
      { "label": "Authentication prompt" },
      { "label": "Workday connection" },
      { "label": "Flow run" },
      { "label": "Network path" },
      { "label": "Workday response" },
      { "label": "Agent availability" },
      { "label": "Other" }
    ],
    "allowFreeformInput": false
  }
]
```

Map those choices respectively to `agent-chat`, `authentication-prompt`,
`workday-connection`, `flow-run`, `network-path`, `workday-response`,
`agent-availability`, or `other`.

Record the selected `remediationId` and a timezone-qualified ISO-8601
`timestamp` in
`.local/connect/workday-da/employee-validation-failure.json`, then run:

```powershell
python scripts/workday_connect.py record-validation-failure --evidence-file ".local\connect\workday-da\employee-validation-failure.json"
```

For `WD-E2E-999`, also record the selected bounded `failureSurface`. The
controller derives the safe category and canonical remediation from the ID;
do not copy those strings into the file. It also migrates existing
three-field failure files created by earlier kit versions. Unrecognized
legacy categories widen to `WD-E2E-999` with the `other` surface, and the
legacy free-form remediation text is discarded. Arbitrary IDs,
unbounded failure surfaces, and unknown fields are rejected.

This marks Employee validation blocked and persists the stable remediation ID
and bounded failure surface while keeping completed prerequisite phases
intact. It also closes the active bounded attempt as failed. Use the failing
surface to choose the next check:

- sign-in loop -> identify which credential store prompted and whether the
  account or tenant differs;
- connector error -> inspect the exact Workday connection status and resource
  URL;
- flow error -> inspect the exact flow run and delegated-authorization
  evidence;
- employee mismatch -> inspect NameID and User Context V2 evidence;
- network error -> inspect the exact Workday REST or SOAP host.

Do not automatically ask the employee to repeat a scenario when final readiness
is pending or a transient service/read-history error occurs. Keep the frozen
attempt and rerun `record-validation` with the same evidence file after waiting
or restoring access. Start a new conversation and run `begin-employee-test`
again only when the returned remediation explicitly requires a fresh evidence
window, such as when no reviewed flow ran, multiple candidate runs made the
window ambiguous, the candidate run failed, or the target changed. Do not reset
completed phases. If the prior attempt is still active before a genuinely new
scenario, run `abandon-employee-test` first.
