<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Set Up Dev from an Entitled MOS Product

Use this path when the maker wants to install an entitled product. Read `src/reference/mos-starter-package.md` before acting. The reference owns the service facts, safety invariants, request-evidence disposition matrix, and response-evidence contract. This skill owns the maker conversation and the handoff into existing-Dev setup.

Use only intent supplied in the current request and results observed in this invocation. Do not infer persona, product, target, or progress from conversation history.

## Identify the target

Read `src/skills/foundation-setup/da-environment-target.md` and follow it, including its exact **Resolve the service ring** decision surface whenever the ring is not identified. Retain the resolved environment ID and ring for every operation in this invocation. Do not ask the maker to classify the product before loading the catalog. When fresh-agent intent and the target environment are known, mark **Choose the starting point and target environment** complete.

## Use the workspace environment

Read canonical setup state and `.local/config.json` when present. Continue in an occupied workspace when its recorded environment is the selected target. If it records a different environment, follow **Create and open a new workspace** in `SKILL.md` and stop this invocation after that handoff. Do not reset a same-environment workspace merely to install another product.

Once the target environment is resolved, use this fixed opening as the first product-installation surface:

**Message:**

Here's your ESS agent setup:

- ✅ Choose the starting point and target environment
- 🔄 Verify access and agent identity
- ⬜ Establish an editable Dev agent
- ⬜ Materialize the local workspace
- ⬜ Review the setup handoff

Loading entitled products for **{environment name}**...

**End message.**

## List the catalog

If account selection was not already completed while discovering the target,
complete the shared account-selection and authorization steps in `SKILL.md`.
Then run:

```text
python scripts/setup_mos_starter.py list \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}"
```

Parse `DA_MOS_STARTER_PACKAGES_JSON:`. Preserve every service row as operation evidence. Group rows by exact `packageId` and present one picker option per exact ID, using the service-provided name, version, and description as authoritative inputs. Never show the internal `packageId` to the maker. Do not describe products as remaining, uninstalled, or eligible; the create response is the service-owned decision for the selected package.

After a successful catalog list, independently run the environment-scoped read-only agent listing:

```text
python scripts/setup_existing_da.py list-agents \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}"
```

Parse `DA_AGENT_LIST_JSON:`. The result classifies every safely reportable listed identity into `devAgents`, `testAgents`, `prodAgents`, or `realmNotEstablishedAgents`. Catalog and `devAgents` results resolve workspace observations before the checked-in seed in `src/reference/da-product-setup-registry.json`. Join catalog rows only to `devAgents` by the returned `productKey`, or by the exact returned `agentSchemaName` and `schemaName` when a workspace observation supplies them. The mapping identifies a product family; it is not starter-package provenance and does not prove the installed agent's template version.

Determine product mapping values from available operation evidence: `setup_mos_starter.py list` for package ID, catalog name, descriptions, and catalog version; `setup_mos_starter.py create` for successful `sourcePackage` identity or a definitive collision response; `setup_existing_da.py list-agents` for visible editable agents and their exact schemas; and `setup_existing_da.py validate-agent` for the exact identity and schema of a selected agent.

The checked-in registry is the initial seed. When current operation results establish a newer package, catalog, and schema mapping, record it with:

```text
python scripts/da_product_registry.py observe \
  --product-key "{PRODUCT_KEY}" \
  --package-id "{PACKAGE_ID}" \
  --catalog-name "{CATALOG_NAME}" \
  --agent-schema-name "{SCHEMA_NAME}" \
  --source "{OPERATION_SOURCE}" \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}"
```

Parse `DA_PRODUCT_OBSERVATION_JSON:`. The workspace-local observation becomes the preferred mapping for later catalog and agent lists and records that the mapped product was definitively observed as installed in that environment and ring. Product identity interpretation and operation ordering remain session responsibilities; the command only validates and writes the supplied facts.

If agent listing fails, preserve its failure evidence and continue with the catalog using only installation facts already established by workspace observations. Do not interpret a failed operation as an empty environment. When `realmNotEstablishedAgents` is non-empty or `productIdentityUnavailableCount` is nonzero, known exact matches remain usable, but do not claim that unmatched catalog products are uninstalled. `testAgents` and `prodAgents` remain service evidence; they are not direct editable-Dev matches for catalog **Use** actions. A selected Prod identity can still follow the parent setup skill's established Prod-to-Dev route.

For each picker row, infer a concise user-friendly product name only when the service-provided name or description makes the meaning unambiguous. Render `Employee Self-Service` as `Employee Self-Service (Hub)`, render `Employee Self-Service IT` or `Employee Self-Service (IT)` as `Employee Self-Service (IT)`, and render `Employee Self-Service HR` or `Employee Self-Service (HR)` as `Employee Self-Service (HR)`. If a friendly form is not clear, use the exact service-provided product name unchanged. This display-only inference must not change the underlying `packageId`, backend name, or create request.

For the recognized ESS products listed below, render the following friendly product name and default supporting description exactly as written. Do not paraphrase, shorten, or combine this copy with the service-provided description. The installed-without-matching-Dev case below replaces the default supporting description for that row.

| Friendly product name         | Supporting description                                                                                                       |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `Employee Self-Service (Hub)` | Use this product if you want to organize HR, IT, or other agents as connected agents behind one unified employee experience. |
| `Employee Self-Service (HR)`  | Create an HR agent that helps employees get HR answers and complete requests.                                                |
| `Employee Self-Service (IT)`  | Create an IT agent that helps employees resolve technical issues and access support.                                         |

For every other product, use its exact service-provided name unchanged and use `shortDescription`, then `description`, as the supporting text.

When listing succeeds, render this mostly fixed catalog surface:

**Message:**

{PRODUCT_COUNT} entitled products are available for **{environment name}**. What would you like to do?

{PRODUCT_ROWS}

**End message.**

Set `{PRODUCT_COUNT}` to the exact grouped `packageId` count and `{PRODUCT_ROWS}` to the unnumbered product rows defined below; never assume a fixed product count. In the host's interactive single-selection control, present those product choices followed by **Refresh list** and **Choose a different environment**, in that order. Leave the selection initially unset, and disable custom entry inside the control. Use **Choose an ESS product or setup action.** as the exact question. Do not describe the surface as selecting a product to create.

For **Refresh list**, rerun the catalog list and agent list in their existing order, then rebuild the complete surface from the fresh results. This is a new maker-requested read, not an automatic retry. For **Choose a different environment**, retain the selected account and ring, read `da-environment-target.md`, rerun `list-environments`, and continue from its environment picker. Do not ask the maker to type a product name or number any choice.

Build the product picker as a projection of the latest successful catalog result and the latest agent-list attempt. Group selectable rows by exact `packageId` and render exactly one choice for every resulting catalog product, preserving the catalog-defined product set and order. Enrich each projected row with workspace observations and the latest `devAgents` evidence. A successful complete agent list is authoritative for the current picker, but only an exact identity in that result renders **Use — Already installed**. An older workspace observation without a current exact identity is historical evidence, not a sticky installed label. When agent listing fails or reports unresolved identities, retain the observation only as historical evidence and state that current installation could not be established; do not convert that uncertainty into either installed or uninstalled. Rebuild this projection whenever a fresh catalog or agent-list result arrives.

When one or more `devAgents` have the same exact `productKey` as a catalog row, format that choice as **Use {friendly product name} — Already installed**. Keep the catalog version in supporting text when present; never present it as the installed agent's version. Selecting this choice does not invoke create:

- When exactly one agent has the matching key, run the parent's selected-agent product-line reconciliation for that exact returned identity and continue through `da-existing-dev.md`.
- When multiple agents have the matching key, show those exact returned agent names as the standard choices, leave the selection initially unset, disable custom entry inside the control, and let the maker select one before reconciliation and `da-existing-dev.md`.

When an older environment-scoped observation reports `installed: true` but the latest successful agent list contains no exact matching identity, label the row **Create {friendly product name} {version} — Installation status unconfirmed**. When listing failed or was incomplete, use **Installation status unavailable** instead. In either case, explain that an earlier installation was observed but current agent visibility could not confirm it. Selecting this row asks:

> Setup previously observed this product in the environment, but current agent visibility could not confirm it. An existing agent may still be hidden from this account. Create anyway and let Copilot Studio validate the current state?

Present **Create anyway**, **Use an agent URL**, **Try with a different user**, and **Go back** as the standard choices, with no preselected choice and custom entry disabled inside the control. **Create anyway** retains the selected package facts and proceeds through **Create** with a new client request UUID. It does not claim that the product is absent or that creation will succeed; preserve the service's success or collision result. Apply the documented route when one of the other standard choices is selected. Do not add another prohibition based on the earlier observation.

When no current exact Dev identity is established, format the choice as **Create {friendly product name} {version}**. This label is an action, not a claim that no matching agent exists. Omit a blank version instead of showing an unresolved value. After the maker selects the choice, retain the exact `packageId`, backend `name`, catalog `version`, and friendly product name, then begin **Create**. Retain the friendly product name for the final exact-agent link.

Unknown catalog products and agents without a registry match remain unclassified. Render an unknown catalog row as a **Create** choice using its exact service-provided name and do not correlate it with agents by display name.

The successful list proves target access, but not a new agent identity. Keep **Verify access and agent identity** current until create and direct attachment validation succeed.

If the catalog is empty, mark the maker's product choices unavailable and say that no entitled products are currently available in the selected environment. Present **Retry setup with another target** from `da-environment-target.md`.
If `catalogWarnings` is non-empty, tell the maker the product listing was incomplete -- some entries could not be read -- without repeating the warning detail itself. A row reported in `catalogWarnings` is never selectable; only offer products backed by rows from the `packages` array.

If the command instead fails, parse `DA_MOS_STARTER_LIST_ANNOTATIONS_JSON:` and the response body (`DA_MOS_STARTER_LIST_RESPONSE_JSON:` or `..._RESPONSE_TEXT:`) the same way `create`'s response is interpreted below. Preserve the detailed evidence internally, say that entitled products could not be loaded and nothing was changed, then present **Retry setup with another target** from `da-environment-target.md`.

Read `src/reference/da-product-setup-registry.json` for setup requirements. A registry-declared connection is evaluated after creation and attachment; do not inspect or require a physical connection before dispatching create. Products without a declared requirement proceed without a connection gate.

## Create

Only after the maker selects a **Create {friendly product name} {version}** catalog choice, generate a new client request UUID and run:

```text
python scripts/setup_mos_starter.py create \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}" \
  --package-id "{CONFIRMED_PACKAGE_ID}" \
  --package-name "{CONFIRMED_PACKAGE_NAME}" \
  --package-version "{CONFIRMED_PACKAGE_VERSION}" \
  --client-request-id "{NEW_CLIENT_REQUEST_UUID}"
```

Retain the UUID as the identity of this create request. Wait for the command to finish and interpret its returned evidence before taking further action. Do not invoke create concurrently or automatically. Reusing the same request UUID means the same mutation and must not dispatch another POST.

## Interpret the response

Parse `DA_MOS_STARTER_CREATE_ANNOTATIONS_JSON:`, then the response body (`DA_MOS_STARTER_CREATE_RESPONSE_JSON:` or `..._RESPONSE_TEXT:`), then `DA_MOS_STARTER_CREATE_JSON:` when the command exits zero. Keep the response body as diagnostic evidence.

The response, outcome label, fuse disposition, HTTP status, and request details are diagnostic evidence only. Do not render them as ordinary maker-facing copy. For a definitive non-success, give a plain-language reason only when the service evidence supports it. For an uncertain result, preserve the current request evidence, show a nonterminal progress message, run fresh read-only catalog and agent inventory operations, and attempt exact identity reconciliation. If no created identity can be proven, ask whether to submit a separately confirmed create request with a new client request UUID. Explain that the earlier request may have succeeded and that Copilot Studio may return a collision. Never reuse the uncertain request UUID or delete its fuse.

> I cannot confirm whether the agent was created because communication ended before a definitive result was received. I’ll check the current catalog and agent inventory before offering the next action.

Say setup stopped only after reconciliation cannot prove an identity and the
maker selects a stop or escalation action.

When the annotations report `outcome: created`, keep the distinction between `catalogPackageVersion` and `templateVersion` in diagnostic evidence; do not explain those internal version concepts to the maker. Say that the new agent was created and setup is not complete.

The successful native create result is authoritative identity and environment-scoped installation evidence. Record its exact package, catalog, returned schema, environment, and ring through `da_product_registry.py observe` with source `setup_mos_starter.py create`, then run the parent's selected-agent product-line reconciliation with the returned identity and `--known-native-schema "{RETURNED_SCHEMA_NAME}"` before the enable-ALM operation.

When the annotations report `outcome: collision`, preserve the exact selected package ID and catalog name. Say that Copilot Studio reports an installed copy of the selected product. When the definitive collision response supplies an exact agent schema, record that mapping and its environment-scoped installed state immediately through `da_product_registry.py observe` with source `setup_mos_starter.py create collision`; this observation does not prove that a selectable agent is visible. Then list visible Dev agents in the same environment through `setup_existing_da.py list-agents` and correlate only exact `productKey` or observed-schema matches for the collided product. Never offer unrelated listed agents.

When exactly one Dev identity matches, ask **Use {agent display name}?** and present **Use this agent** and **Go back** as the standard choices. Do not add a separate choose-from-existing step. When multiple Dev identities match, ask **Choose the installed {friendly product name} agent.**, present those matching identities plus **Go back** as the standard choices, and render every agent option as its exact service-provided display name only. Leave every collision choice initially unset and disable custom entry inside the control. Retain IDs and schemas as internal evidence; never display an ID, schema, product key, or **schema will be verified** annotation in either panel.

For a selected matching identity, run `setup_existing_da.py validate-agent` only when the list result does not already establish its exact schema, then run the parent's selected-agent product-line reconciliation with `--known-native-schema "{RETURNED_SCHEMA_NAME}"` and continue through `da-existing-dev.md`. If no Dev identity matches, use the installed-without-matching-Dev explanation and **Use an agent URL**, **Try with a different user**, and **Go back** recovery above instead of presenting other agents. This path does not replace an agent.

For **Go back**, preserve the collided create result and its client request UUID, then return to the complete action-oriented catalog composed from every selectable row in the latest successful catalog result and the latest agent list. Any later **Create** selection uses a new client request UUID; never repeat the collided request.

## Enable ALM

Build `{ACTUAL_AGENT_URL}` as `{COPILOT_STUDIO_ORIGIN}/environments/{ENVIRONMENT_ID}/copilots/{RETURNED_AGENT_ID}/details?agentBackend=cosmos`, using the Copilot Studio origin for the selected service ring and the exact environment and agent IDs from the successful create result.

After a successful create, show:

**Message:**

The agent was created.

> **Open [{USER_FRIENDLY_PRODUCT_NAME}]({ACTUAL_AGENT_URL}) in Classic Copilot Studio.**

Preparing its local authoring workspace...

**End message.**

Then run:

```text
python scripts/setup_mos_starter.py enable-alm \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}" \
  --agent-id "{RETURNED_AGENT_ID}"
```

Parse `DA_MOS_STARTER_ALM_ANNOTATIONS_JSON:` and its response body when present, then `DA_MOS_STARTER_ALM_JSON:` on success. A failed read-back may instead emit `DA_MOS_STARTER_ALM_VERIFY_ANNOTATIONS_JSON:`, its response body, or `DA_MOS_STARTER_ALM_VERIFY_JSON:`. Continue only for `outcome: enabled` or `outcome: already-enabled` with `persistedValue: true`. If read-back definitively reports `outcome: verification-failed` and `persistedValue: false`, say, "The follow-up check showed that the agent was not prepared for local editing. Setup has stopped without attaching a workspace." If transport or read-back becomes uncertain, preserve the evidence internally, say that the agent could not be confirmed ready for local editing, and stop. An enabled or already-enabled result proceeds directly to attachment.

## Attach

After ALM read-back succeeds, run:

```text
python scripts/setup_existing_da.py attach \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}" \
  --agent-id "{RETURNED_AGENT_ID}" \
  --setup-source mos-starter \
  --expected-schema-name "{RETURNED_SCHEMA_NAME}"
```

This attachment validates the returned agent through its direct Dev route and component identity; it does not require published Dev configuration. It resolves any connection requirement from the product registry by exact agent identity and records that requirement on canonical `SETUP-05`. On failure, preserve the command's specific `ERROR:` text and any canonical `active_step` and `failure_causes` as diagnostic evidence. Translate them into the visible setup stage and a plain explanation of the unmet prerequisite as described in `da-existing-dev.md`; never show internal step IDs or raw technical output as ordinary maker copy. Publishing is outside foundation setup and is not remediation for an attachment failure. On success, parse `DA_EXISTING_DEV_SETUP_JSON:`. When attachment reports `connectionStatus: workspace-ready`, mark the access, identity, editable-agent, and materialization stages complete, then run the three setup-readiness FlightChecks and broad connection diagnostic as the single presentation unit defined in `da-existing-dev.md`. Complete every check whose prerequisites remain available before producing the factual workspace and runtime-readiness handoff. When an operation requires maker action or prevents later checks from running, state the observed blocker and supported recovery. The request-scoped create evidence intentionally remains as an audit note. Do not publish, remove, or replace components from this path.

After all four FlightChecks have been attempted, render the factual workspace and runtime-readiness report from `da-existing-dev.md` using **New entitled MOS product** as the starting point, including when `connectReady` is false.
For every non-created outcome (`pre-dispatch-failure`, `collision`, `rejected`, `malformed-success`, `source-package-mismatch`, or an uncertain response or transport failure), end the create operation. The existing read-only `list` and `setup_existing_da.py validate-agent`/`list-agents` commands remain available for a separately requested inspection.

Connection setup is outside this foundation path. Never invoke `/connect`, install a connector, or configure Dataverse, publishing, promotion, or telemetry from this skill.
