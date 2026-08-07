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

Do not ask the maker to select or confirm a billing model. Continue only when
the checkpoint reports `Passed` because message capacity is allocated to the
environment.

Treat every other result and command failure as immediately blocking:

1. Run:

   ```text
   python scripts/setup_state.py update-step \
     --step SETUP-02.2 \
     --status blocked \
     --cause "Copilot Studio message capacity is not allocated"
   ```

2. Show this message verbatim once. Do not summarize, rephrase, or replace it
   with the checkpoint remediation:

   ```text
   Copilot Studio message capacity must be allocated to `{ENVIRONMENT_NAME}`
   before setup can continue.

   1. Open [Power Platform admin center](https://admin.powerplatform.microsoft.com/billing/licenses/copilotStudio/overview).
   2. Select `Licensing` in the left navigation.
   3. Under **Copilot Studio**, select `Manage`.
   4. Open the `Manage capacity` tab.
   5. Find `{ENVIRONMENT_NAME}`.
   6. Allocate Copilot Studio message capacity to the environment.
   7. Select `Save`, then return here and choose **Check again**.
   ```

   If the visible Power Platform admin center labels differ, use the linked
   **Copilot Studio capacity** page and locate `{ENVIRONMENT_NAME}` in its
   environment allocation table. Do not invent alternate navigation labels.
3. Ask only this non-freeform question:

   ```json
   [
     {
       "header": "Capacity required",
       "question": "After allocating Copilot Studio message capacity to `{ENVIRONMENT_NAME}`, what would you like to do?",
       "options": [
         {
           "label": "Check again",
           "description": "Rerun the required capacity validation."
         }
       ],
       "allowFreeformInput": false
     }
   ]
   ```

4. Rerun the checkpoint only when **Check again** is selected.

Render the verbatim remediation only once, before the question. After asking
the question, do not print another blocked-state summary, repeat the portal
steps, paraphrase them, or add a second capacity message. The question is the
final rendered content until the maker responds.

**STOP here while capacity remains unverified.** Do not ask governance
questions, collect any other prerequisite answers, or continue to another setup
step. There is no skip, continue, defer, or manual-attestation path. If a maker
nevertheless replies with `skip` or any response other than **Check again**,
repeat that capacity is mandatory and stop without asking another question.

Do not accept Pay-as-you-go, a billing-model selection, or manual attestation in
place of allocated capacity.

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

If all prerequisite checks pass, persist one consolidated step result:

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
