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

On success, record only the scenario name, test-user category, timestamp, and
outcome:

```powershell
python scripts/workday_connect.py record-validation --evidence-json '{...}'
```

Provide only `scenarioName`, `testUserCategory`, `timestamp`, and a passed or
verified `outcome`. The controller rejects additional fields. Never record
employee data or credentials.

On failure, keep the phase active and persist one current blocker. Use the
failing surface to choose the next check:

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
