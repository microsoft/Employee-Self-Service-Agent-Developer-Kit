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

  When `recoveryUnavailable` is `true`, say that the compatible pinned installer could not be resolved, render **Review the setup handoff** as blocked, make no changes, and stop without guessing a branch or release.

  Otherwise say:

  > **{agent display name or Selected agent}** belongs to the classic Employee Self-Service agent product line, so this Developer Kit cannot safely continue its setup.
  >
  > Want me to install the compatible CEA kit in a separate folder and open it now?

  - When the maker accepts, run `recoveryCommand` in a terminal using `recoveryShell`. On success, render **Review the setup handoff** as complete and say:

    > Continue setup in the workspace opened by the compatible installer. No Copilot Studio agent or setup state was changed by this product-line check.

  - When the maker declines, render **Review the setup handoff** as complete, show `recoveryCommand` in a fenced block whose language is `recoveryShell`, and say:

    > Run this pinned command later to install the compatible kit in a separate folder. No Copilot Studio agent or setup state was changed by this product-line check.

  - When command execution fails, render **Review the setup handoff** as blocked and state the observed installer failure. Do not label the unchanged command as a retry or reinterpret installer failure as a successful handoff. When the output identifies an existing installation, verify that its checkout matches `releaseTag` and offer to open its `solutions/ess-maker-skills` workspace directly. Otherwise provide one recovery action grounded in the observed failure.

Do not expose the schema name, agent ID, environment ID, API host, or raw classifier failures. Do not reinterpret a missing or failed lookup as classic CEA evidence.
