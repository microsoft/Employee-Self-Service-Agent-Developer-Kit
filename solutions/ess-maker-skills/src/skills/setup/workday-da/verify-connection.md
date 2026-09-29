<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Phase 6 - Employee validation

This phase requires a real signed-in employee scenario. Configuration checks
alone cannot complete it.

The skill cannot publish the agent, impersonate an employee, or perform this
scenario on the employee's behalf. It guides the maker through the test and
records only the safe outcome.

Ask the maker to:

1. publish the ESS HR agent;
2. start a new conversation;
3. sign in as a test employee assigned to the Workday Entra application and
   authorized in Workday;
4. run one enabled read-only scenario, such as checking a vacation balance;
5. confirm the agent identifies the signed-in employee and returns real
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

On failure, map the selected result to exactly one stable contract below. Do
not invent a remediation ID, category, or alternate wording.

| Selected result | `remediationId` | `failureCategory` | Canonical `remediation` |
| --- | --- | --- | --- |
| Failed - repeated sign-in | `WD-E2E-001` | `employee-authentication` | `Verify the employee assignment and identify which sign-in surface is prompting again.` |
| Failed - connector error | `WD-E2E-002` | `workday-connection` | `Verify the selected Workday connection is authenticated and targets the reviewed Workday resource.` |
| Failed - flow error | `WD-E2E-003` | `runtime-flow` | `Inspect the failed Workday flow run and reverify delegated authorization before retrying.` |
| Failed - employee mismatch | `WD-E2E-004` | `employee-context` | `Verify the employee NameID and User Context V2 mapping before retrying.` |
| Failed - network error | `WD-E2E-005` | `network` | `Verify the required Workday REST and SOAP hosts are reachable from the configured runtime.` |
| Failed - Workday access denied | `WD-E2E-006` | `workday-access` | `Ask a Workday administrator to verify the test employee's functional-area and domain access.` |
| Failed - agent not published or unavailable | `WD-E2E-007` | `publish-or-agent` | `Publish the selected agent and verify the employee is testing the reviewed agent in the target environment.` |
| Failed - another issue | `WD-E2E-999` | `unknown` | `Capture the failing surface without employee data and route it to ESS support for classification.` |

Record only the selected `remediationId`, its exact `failureCategory`, a
timezone-qualified ISO-8601 `timestamp`, and the exact canonical
`remediation` in
`.local/connect/workday-da/employee-validation-failure.json`, then run:

```powershell
python scripts/workday_connect.py record-validation-failure --evidence-file ".local\connect\workday-da\employee-validation-failure.json"
```

The controller rejects arbitrary IDs, mismatched categories, changed
remediation wording, and additional fields. This marks Employee validation
blocked and persists the stable remediation ID while keeping completed
prerequisite phases intact. Use the failing surface to choose the next check:

- sign-in loop -> identify which credential store prompted and whether the
  account or tenant differs;
- connector error -> inspect the exact Workday connection status and resource
  URL;
- flow error -> inspect the exact flow run and delegated-authorization
  evidence;
- employee mismatch -> inspect NameID and User Context V2 evidence;
- network error -> inspect the exact Workday REST or SOAP host.

After remediation, retry with a new conversation. Do not reset completed
phases.
