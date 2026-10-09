<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Setup Steps 2.1 and 2.2 — Prerequisites

This playbook may run only when the current persisted `active_step` is
`SETUP-02.1` or `SETUP-02.2`. If state reports any other active step, stop this
playbook immediately and return to the foundation router. Do not rerun
Dataverse MCP, capacity, or governance checks for a completed prerequisite
step.

Mark the access and Dataverse substep in progress:

```text
python scripts/setup_state.py update-step --step SETUP-02.1 --status in-progress
```

Read the locked environment without loading unrelated state:

```text
python scripts/setup_state.py show --view environment
```

## Access and Dataverse

Run:

```text
python scripts/flightcheck/cli.py \
  --checkpoint ENV-002 \
  --quiet-auth \
  --environment-url "{ENVIRONMENT_URL}" \
  --environment-id "{ENVIRONMENT_ID}"
```

The environment was already resolved and locked by `SETUP-01`; do not list all
environments again. `ENV-002` must pass for that locked environment.

Continue immediately when the check passes. Do not ask whether the maker can
open the environment in Power Platform or Copilot Studio. If `ENV-002` fails,
show the exact command error and block the prerequisite step;
do not replace a failed automated result with manual attestation.

Persist and complete the first substep:

```text
python scripts/setup_state.py record-step-result \
  --step SETUP-02.1 \
  --checkpoint ENV-002 \
  --mode automated
python scripts/setup_state.py update-step --step SETUP-02.1 --status done
python scripts/setup_state.py update-step --step SETUP-02.2 --status in-progress
```

## Dataverse MCP client

Check the documented Allowed MCP Client record for Microsoft GitHub Copilot:

```text
python scripts/check_dataverse_mcp.py --url "{ENVIRONMENT_URL}"
```

Parse `DATAVERSE_MCP_STATUS_JSON:`:

- `enabled`: continue immediately without asking the maker anything.
- `disabled` or `missing`: show the following guidance, then offer **Check
  again**:

  1. Open [Power Platform admin center](https://admin.powerplatform.microsoft.com/environments).
  2. Select the `{ENVIRONMENT_NAME}` environment.
  3. Open `Settings` → `Product` → `Features`.
  4. Turn on **Allow MCP clients to interact with Dataverse MCP server**.
  5. Open `Advanced Settings`.
  6. Open **Microsoft GitHub Copilot** and set `Is Enabled` to `Yes`.
  7. Choose `Save & Close`, then select **Check again** here.

  Rerun the command when selected.
- command failure: show the exact error and stop. Do not replace an unavailable
  API result with manual attestation.

The setup must not ask whether MCP is already enabled. Dataverse is the source
of truth.

## Capacity and billing

Run:

```text
python scripts/flightcheck/cli.py \
  --checkpoint ENV-CAPACITY-001 \
  --quiet-auth \
  --environment-url "{ENVIRONMENT_URL}" \
  --environment-id "{ENVIRONMENT_ID}"
```

Do not ask the maker to select or confirm a billing model. Inspect the exact
`ENV-CAPACITY-001` row and branch on its structured status.

For `Passed`, record the verified disposition and continue:

```text
python scripts/setup_state.py set-prerequisite \
  --name capacity \
  --status complete \
  --value "Verified: allocated capacity is greater than zero."
```

For `Failed`, `Error`, or command failure, show the observed failure and stop.
These outcomes are not eligible for override because setup does not have
trustworthy evidence of a successful capacity read. Keep `SETUP-02.2` blocked
with the observed cause; do not replace the failure with manual attestation.

A `Warning` means the Licensing API ran successfully and found zero allocated
capacity. On the first `Warning`:

1. Run:

   ```text
   python scripts/setup_state.py update-step \
     --step SETUP-02.2 \
     --status blocked \
     --cause "Copilot Studio message capacity is not allocated"
   python scripts/setup_state.py set-prerequisite \
     --name capacity \
     --status pending \
     --value "Verified: zero allocated capacity."
   ```

2. Show this message verbatim once. Do not summarize, rephrase, or replace it
   with the checkpoint remediation:

   ```text
   Copilot Studio message capacity must be allocated to `{ENVIRONMENT_NAME}`
   before setup can pass this check automatically.

   1. Open [Power Platform admin center](https://admin.powerplatform.microsoft.com/billing/licenses/copilotStudio/overview).
   2. Select `Licensing` in the left navigation.
   3. Under **Copilot Studio**, select `Manage`.
   4. Open the `Manage capacity` tab.
   5. Find `{ENVIRONMENT_NAME}`.
   6. Allocate Copilot Studio message capacity to the environment.
   7. Select `Save`, then return here and choose **Check again before overriding**.
   ```

   If the visible Power Platform admin center labels differ, use the linked
   **Copilot Studio capacity** page and locate `{ENVIRONMENT_NAME}` in its
   environment allocation table. Do not invent alternate navigation labels.
3. Ask only this non-freeform question:

   ```json
   [
     {
       "header": "Capacity unavailable",
       "question": "The capacity check found zero allocated capacity for `{ENVIRONMENT_NAME}`. What would you like to do?",
       "options": [
         {
           "label": "Check again before overriding",
           "description": "Rerun the capacity check before deciding whether to override it."
         },
         {
           "label": "Pause setup",
           "description": "Pause setup at the capacity check."
         }
       ],
       "allowFreeformInput": false
     }
   ]
   ```

4. For **Check again before overriding**, rerun the checkpoint.
5. For **Pause setup**, leave capacity pending and `SETUP-02.2` blocked, then
   stop.

Render the verbatim remediation only once, before the question. After asking
the question, do not print another blocked-state summary, repeat the portal
steps, paraphrase them, or add a second capacity message. The question is the
final rendered content until the maker responds.

If the recheck reports `Passed`, set `SETUP-02.2` back to `in-progress`, record
the verified capacity disposition above, and continue.

If the recheck returns `Warning` again, state that the second successful check
still found zero allocated capacity. Before presenting the next choices, state
that a Power Platform administrator must be present to override the capacity
check and that overriding does not allocate capacity, verify capacity, or
change the observed zero-capacity result. Then ask:

```json
[
  {
    "header": "Capacity still unavailable",
    "question": "The recheck still found zero allocated capacity for `{ENVIRONMENT_NAME}`. Do you want to continue with an administrator-attested skip?",
    "options": [
      {
        "label": "Continue with administrator-attested skip",
        "description": "Confirm that a Power Platform administrator is present and accepts that capacity remains unverified."
      },
      {
        "label": "Pause setup",
        "description": "Leave setup blocked at the capacity check and continue later."
      }
    ],
    "allowFreeformInput": false
  }
]
```

- For **Continue with administrator-attested skip**, set `SETUP-02.2` back to
  `in-progress`, then record:

  ```text
  python scripts/setup_state.py set-prerequisite \
    --name capacity \
    --status complete \
    --value "Administrator-attested skip after repeated zero-allocation checks; capacity was not verified."
  ```

  Continue to governance without claiming that capacity is allocated or ready.
- For **Pause setup**, leave capacity pending and `SETUP-02.2` blocked, then
  stop.

If any recheck returns `Failed`, `Error`, or a command failure, preserve that
new result and stop. Do not offer or apply an administrator-attested skip.

Do not accept Pay-as-you-go or a billing-model selection in place of allocated
capacity. Manual attestation is available only after two successful checks
both report zero allocation.

## Governance

Ask for explicit status of:

- DLP allowlisting;
- firewall/outbound allowlisting required for planned integrations;
- organization approvals.

A required item that is pending is a failure. Persist each answer with
`set-prerequisite`.

## Blocking guard

If any mandatory prerequisite failed or remains unknown:

1. Set `SETUP-02.2` to `blocked` with one normalized cause per missing item.
2. Show the missing items and stop.

If all prerequisite checks pass or the capacity prerequisite contains the
administrator-attested disposition above, persist one consolidated step result:

```text
python scripts/setup_state.py record-step-result \
  --step SETUP-02.2 \
  --checkpoint ENV-CAPACITY-001 \
  --mode manual-attested
```

Then complete the step:

```text
python scripts/setup_state.py update-step --step SETUP-02.2 --status done
```
