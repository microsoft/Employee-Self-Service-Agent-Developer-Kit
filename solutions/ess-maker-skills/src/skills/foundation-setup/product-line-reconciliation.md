<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Reconcile the Selected Agent Product Line

Run this handoff whenever setup has selected one exact environment and agent, regardless of whether the identity came from a supplied Copilot Studio URL, active local setup state, a configured-agent switch, environment candidate selection, MOS creation, or ALM import. Run it once per `(environmentId, agentId)` in one setup invocation and run it again only when that selected identity changes.

This check is read-only. The script exposes independent identity probes and preserves each service result. This skill owns probe ordering, combines the observations, interprets product support, and presents recovery choices. URL shape, query parameters, display names, generic API failures, and environment-level solution presence are not product evidence.

## Use authoritative native evidence

When a current-invocation MinimalBot operation already returned and validated the exact identity, classify its returned schema without repeating either remote lookup:

```text
python scripts/reconcile_setup_agent.py \
  --known-native-schema "{RETURNED_SCHEMA_NAME}"
```

Parse `DA_SETUP_PRODUCT_RECONCILIATION_JSON:` as one native `found` observation, then apply **Interpret the observations** below.

## Probe an externally supplied identity

For an identity that was not already proven by a native operation, run both independent probes. The Copilot Studio URL's `agentBackend` query value is an ordering hint only:

- `dataverse` means run the Dataverse probe first.
- `cosmos` means run the native probe first.
- A missing or unrecognized value means run the Dataverse probe first.

Do not infer product family, existence, support, or ALM enrollment from this hint. Run the second probe even when the first probe returns `found`; two `found` observations must remain distinguishable.

Run the Dataverse probe:

```text
python scripts/reconcile_setup_agent.py \
  --probe dataverse \
  --environment-id "{ENVIRONMENT_ID}" \
  --agent-id "{AGENT_ID}"
```

Append the parent setup skill's confirmed `--account` when available. Append `--dataverse-url` only when the selected environment's exact Dataverse URL is already authoritative setup input. Do not ask the maker for a Dataverse URL solely for this check.

Run the native MinimalBot probe:

```text
python scripts/reconcile_setup_agent.py \
  --probe native \
  --environment-id "{ENVIRONMENT_ID}" \
  --agent-id "{AGENT_ID}" \
  --ring "{RING}"
```

Append the parent setup skill's confirmed `--account`, validated `--host`, and `--api-version` values when available.

Parse one `DA_SETUP_PRODUCT_RECONCILIATION_JSON:` result from each command. Preserve `backend`, `outcome`, `stage`, `productFamily`, `identity`, and `error` as internal evidence. The probe outcomes are:

- `found` — that identity store returned the exact agent.
- `not-found` — that exact identity endpoint returned HTTP 404.
- `authentication-required` — the endpoint returned HTTP 401.
- `access-denied` — the endpoint returned HTTP 403.
- `uncertain` — transport, service, response-shape, environment-resolution, or other evidence could not establish the result.

Do not convert `authentication-required`, `access-denied`, or `uncertain` into `not-found`.

## Interpret the observations

Schema classification is case-insensitive and prefix-based:

- `msdyn_copilotforemployeeselfservice*` is the solution-backed Employee Self-Service family supported by the compatible `main-ca` kit.
- `gptagent_copilotforemployeeselfservice*` is the DA-GA family.
- Any other or missing schema is custom or unknown.

Apply the first matching rule:

1. When both probes returned `found`, stop before any realm or ALM operation. Say that both supported identity stores returned an agent for the same ID, so setup cannot safely choose a backend. Preserve both observations; do not select one from the URL hint.
2. When exactly one probe returned `found`, that observation proves existence and backend even if the other probe returned `not-found`, an access outcome, or an uncertainty outcome. Preserve a backend-hint mismatch as internal evidence, use the backend that actually returned the agent, and do not call the agent missing.
3. For a native `found` DA-GA observation, continue at the next DA-GA setup operation. Only this result makes native ALM realm inspection applicable.
4. For a Dataverse-only `found` DA-GA observation, stop before native inspection. Say that the agent belongs to the Employee Self-Service DA family but was found only in Dataverse, and this native setup path cannot safely prepare it for local authoring.
5. For any `found` solution-backed Employee Self-Service observation, follow **Use the compatible kit** below. This includes classic CA and DA-Preview variants.
6. For any `found` custom or unknown observation, follow **Unsupported agent** below.
7. When both probes returned `not-found`, say that the exact agent was not found in either accessible identity store.
8. When neither probe returned `found` and at least one returned `authentication-required` or `access-denied`, state the endpoint-specific sign-in or permission blocker. Do not claim the agent is missing.
9. Otherwise state that setup could not establish the agent's identity because one or more lookups were uncertain. Do not continue to realm inspection.

Rules 1, 4, 6, 7, 8, and 9 use the same recovery choices and routes defined under **Unsupported agent**. For every stopped result, render **Choose the starting point and target environment** as complete, **Verify access and agent identity** as blocked, **Establish an editable Dev agent** and **Materialize the local workspace** as pending, and **Review the setup handoff** as in progress while the recovery choice is pending.

## Use the compatible kit

Before offering installation, obtain the pinned compatible-kit operation:

```text
python scripts/reconcile_setup_agent.py --compatible-kit
```

Parse `DA_SETUP_PRODUCT_RECONCILIATION_JSON:`.

After the command returns, proceed directly to the required setup checklist render and the applicable exact maker-facing message below. Do not emit an operational progress line between them. Do not emit **Verified replacement agent identities and resolved compatible ESS kit** or narrate completed probes, schema classification, or compatible-kit resolution.

When `outcome` is `unavailable`, say that the compatible pinned installer could not be resolved and render **Review the setup handoff** as blocked. Do not guess a branch or release. Ask **How would you like to continue setup?** and offer exactly:

- **Choose a different agent**
- **Choose a different environment**
- **Go back**

Do not offer **Install and open the compatible kit**. Follow the shared recovery routes under **Unsupported agent**.

When `outcome` is `available`, send this exact Message block as its own completed chat message. Substitute the display name without adding Markdown emphasis around it:

**Message:**

{agent display name or Selected agent} belongs to a legacy agent family, so this Developer Kit cannot safely continue its setup.

**End message.**

After completing that message, use the `vscode_askQuestions` tool with this exact single-selection control:

```json
[
  {
    "header": "Continue setup",
    "question": "How would you like to continue setup?",
    "options": [
      { "label": "Install and open the compatible kit" },
      { "label": "Choose a different agent" },
      { "label": "Choose a different environment" },
      { "label": "Go back" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave the selection initially unset. Do not add `recommended`, `default`, or any equivalent preselection to an option. Keyboard focus or a visual highlight is not a selected value; wait for the maker to submit an explicit choice before continuing setup.

- For **Install and open the compatible kit**, run `recoveryCommand` in a terminal using `recoveryShell`. On success, render **Review the setup handoff** as complete and say:

  > Continue setup in the workspace opened by the compatible installer. No Copilot Studio agent or setup state was changed by this product-line check.

- Apply the three shared recovery routes below for the other choices.
- When command execution fails, render **Review the setup handoff** as blocked and state the observed installer failure. Do not label the unchanged command as a retry or reinterpret installer failure as a successful handoff. When the output identifies an existing installation, verify that its checkout matches `releaseTag` and offer to open its `solutions/ess-maker-skills` workspace directly. Otherwise provide one recovery action grounded in the observed failure.

## Unsupported agent

For a custom or unknown `found` observation, say:

> **{agent display name or Selected agent}** was found, but it is not part of a supported Employee Self-Service agent family for this Developer Kit.

Use the host's interactive single-selection control and ask exactly:

> How would you like to continue setup?

Offer exactly:

- **Choose a different agent**
- **Choose a different environment**
- **Go back**

Do not preselect a choice.

- For **Choose a different agent**, retain the current account, environment, and ring. Read `src/skills/foundation-setup/da-existing-dev.md` and continue from its environment-scoped `list-agents` candidate-selection path. Do not persist the rejected agent or change the active local agent before another exact candidate passes product-line reconciliation.
- For **Choose a different environment**, retain the current account and ring. Read `src/skills/foundation-setup/da-environment-target.md`, rerun `list-environments`, and continue from its environment picker. A target in another environment follows the parent skill's new-workspace contract.
- For **Go back**, do not persist the rejected agent. Return to **Choose the sign-in account** in the parent skill. After the maker selects an account, read `src/skills/foundation-setup/da-environment-target.md`, list that account's environments, and continue from the selected environment through the parent skill's create-or-connect choice. The direct different-agent and different-environment routes above retain the current account; **Go back** is the account-reset route.

Do not expose the schema name, agent ID, environment ID, API host, raw probe failure, or URL backend hint. Do not reinterpret a missing or failed lookup as product evidence.
