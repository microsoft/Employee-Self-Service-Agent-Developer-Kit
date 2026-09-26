<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Reconcile the Selected Agent Product Line

Run this handoff whenever setup has selected one exact environment and agent, regardless of whether the identity came from a supplied Copilot Studio URL, active local setup state, a configured-agent switch, environment candidate selection, MOS creation, or ALM import. Run it once per `(environmentId, agentId)` in one setup invocation and run it again only when that selected identity changes.

This check is read-only. It may prove that the selected agent belongs to the native DA-GA service or to a recognized solution-backed product. URL shape, query parameters, display names, generic API failures, and environment-level solution presence are not product evidence.

## Run the reconciliation

For an identity already returned and validated by a native MinimalBot operation, run:

```text
python scripts/reconcile_setup_agent.py \
  --environment-id "{ENVIRONMENT_ID}" \
  --agent-id "{AGENT_ID}" \
  --ring "{RING}" \
  --native-da-ga
```

Otherwise run:

```text
python scripts/reconcile_setup_agent.py \
  --environment-id "{ENVIRONMENT_ID}" \
  --agent-id "{AGENT_ID}" \
  --ring "{RING}"
```

Append the parent setup skill's confirmed `--account`, validated `--host`, and `--api-version` values when available. Append `--dataverse-url` only when the selected environment's exact Dataverse URL is already authoritative setup input. Do not ask the maker for a Dataverse URL solely for this check.

Parse `DA_SETUP_PRODUCT_RECONCILIATION_JSON:`.

- For `action: continue-da-ga-setup`, continue at the next DA-GA setup operation. `classification: unknown` is deliberately fail-open; do not persist it or tell the maker that DA-GA was proven.
- For `action: stop-and-use-cea-kit`, stop before inspection, validation, attachment, import, Object Model installation, or other DA-GA-only work. Render **Choose the starting point and target environment** as complete, **Verify access and agent identity** as blocked, **Establish an editable Dev agent** and **Materialize the local workspace** as pending, and **Review the setup handoff** as in progress while the kit-switch choice is pending.

  When `recoveryUnavailable` is `true`, say that the compatible pinned installer could not be resolved and render **Review the setup handoff** as blocked. Do not guess a branch or release. Use the host's interactive single-selection control, ask **How would you like to continue setup?**, and offer exactly:
  - **Choose a different agent**
  - **Choose a different environment**
  - **Go back**

  Do not offer **Install and open the compatible kit** when its pinned installer is unavailable. Follow the corresponding Setup routes below.

  Otherwise say:

  > **{agent display name or Selected agent}** belongs to the classic Employee Self-Service agent product line, so this Developer Kit cannot safely continue its setup.

  Then use the host's interactive single-selection control and ask exactly:

  > How would you like to continue setup?

  Offer exactly:
  - **Install and open the compatible kit**
  - **Choose a different agent**
  - **Choose a different environment**
  - **Go back**

  Do not preselect a choice.
  - For **Install and open the compatible kit**, run `recoveryCommand` in a terminal using `recoveryShell`. On success, render **Review the setup handoff** as complete and say:

    > Continue setup in the workspace opened by the compatible installer. No Copilot Studio agent or setup state was changed by this product-line check.

  - For **Choose a different agent**, retain the current account, environment, and ring. Read `src/skills/foundation-setup/da-existing-dev.md` and continue from its environment-scoped `list-agents` candidate-selection path. Do not persist the rejected agent or change the active local agent before another exact candidate passes product-line reconciliation.
  - For **Choose a different environment**, retain the current account and ring. Read `src/skills/foundation-setup/da-environment-target.md`, rerun `list-environments`, and continue from its environment picker. A target in another environment follows the parent skill's new-workspace contract.
  - For **Go back**, do not persist the rejected agent. Return to **Choose the sign-in account** in the parent skill. After the maker selects an account, read `src/skills/foundation-setup/da-environment-target.md`, list that account's environments, and continue from the selected environment through the parent skill's create-or-connect choice. The direct different-agent and different-environment routes above retain the current account; **Go back** is the account-reset route.

  - When command execution fails, render **Review the setup handoff** as blocked and state the observed installer failure. Do not label the unchanged command as a retry or reinterpret installer failure as a successful handoff. When the output identifies an existing installation, verify that its checkout matches `releaseTag` and offer to open its `solutions/ess-maker-skills` workspace directly. Otherwise provide one recovery action grounded in the observed failure.

Do not expose the schema name, agent ID, environment ID, API host, or raw classifier failures. Do not reinterpret a missing or failed lookup as classic CEA evidence.
