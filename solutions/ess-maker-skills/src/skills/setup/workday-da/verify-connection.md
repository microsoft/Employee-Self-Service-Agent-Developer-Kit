<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Phase 6 - Employee validation

This phase requires a real signed-in employee scenario. Configuration checks
alone cannot complete it.

The skill cannot publish the agent, impersonate an employee, or perform this
scenario on the employee's behalf. It guides the maker through the test and
records only the safe outcome.

First ask the maker to publish the ESS HR agent, open a new Test pane
conversation, and sign in as the assigned non-maker test employee. Stop before
running a Workday scenario.

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

Then ask the maker to immediately:

1. run one enabled read-only scenario, such as checking a vacation balance;
2. confirm the agent identifies the signed-in employee and returns real
   Workday data without an unexpected repeated sign-in.

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

Leave the result unset and do not mark the passing outcome as recommended. If
the test passed, ask for the scenario with this separate structured choice:

```json
[
  {
    "header": "Tested scenario",
    "question": "Which read-only Workday scenario did the test employee run?",
    "options": [
      { "label": "Check vacation balance" },
      { "label": "View employment information" },
      { "label": "View compensation" },
      { "label": "View organization or manager information" },
      { "label": "Another read-only Workday scenario" }
    ],
    "allowFreeformInput": true
  }
]
```

On success, record only the scenario name, test-user category, timestamp, and
outcome in `.local/connect/workday-da/employee-validation.json`. Write the
object using a structured file-write tool rather than a generated shell
command, then run:

```powershell
python scripts/workday_connect.py record-validation --evidence-file ".local\connect\workday-da\employee-validation.json"
```

Provide only `scenarioName`, `testUserCategory`, `timestamp`, and a passed or
verified `outcome`. Use a non-maker employee category and a
timezone-qualified ISO-8601 timestamp. The controller rejects additional
fields. Never record employee data or credentials.

On success, the controller closes the bounded attempt, verifies the reviewed
flow runs from that window, and evaluates final readiness before marking the
lifecycle ready. Show any returned customer-safe remediation without exposing
internal profile or checkpoint identifiers.

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

After remediation, retry with a new conversation. Do not reset completed
phases. Run `begin-employee-test` again immediately before every retried
employee scenario, including when the previous `record-validation` command
returned a readiness or service error. If the prior attempt is still active,
run `abandon-employee-test` first.
