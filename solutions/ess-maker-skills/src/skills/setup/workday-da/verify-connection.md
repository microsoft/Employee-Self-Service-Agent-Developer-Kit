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
      { "label": "Failed - network error" }
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

On failure, record only a safe `failureCategory`, a timezone-qualified
ISO-8601 `timestamp`, and a concise non-sensitive `remediation` in
`.local/connect/workday-da/employee-validation-failure.json`, then run:

```powershell
python scripts/workday_connect.py record-validation-failure --evidence-file ".local\connect\workday-da\employee-validation-failure.json"
```

This marks Employee validation blocked and persists one current blocker while
keeping completed prerequisite phases intact. Use the failing surface to
choose the next check:

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
