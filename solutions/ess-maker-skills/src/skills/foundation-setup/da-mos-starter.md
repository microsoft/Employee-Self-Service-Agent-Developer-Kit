<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Set Up a Dev Agent from an Agent Template

Use this path when the maker wants to create a fresh agent from an available agent template. Read `src/reference/mos-starter-package.md` before acting. The reference owns the service facts, safety invariants, request-evidence disposition matrix, and response-evidence contract. This skill owns the maker conversation and the handoff into existing-Dev setup.

Use only intent supplied in the current request and results observed in this invocation. Do not infer persona, product, target, or progress from conversation history.

## Identify the target

Read `src/skills/foundation-setup/da-environment-target.md` and follow it, including its exact **Resolve the service ring** decision surface whenever the ring is not identified. Retain the resolved environment ID and ring for every operation in this invocation. Do not ask the maker to classify an agent template before loading the catalog. When fresh-agent intent and the target environment are known, mark **Choose the starting point and target environment** complete.

## Use the workspace environment

Read canonical setup state and `.local/config.json` when present. Continue in an occupied workspace when its recorded environment is the selected target. If it records a different environment, follow the conflicting-environment flow under **Shared workspace choices** in `SKILL.md`. Do not reset a same-environment workspace merely to set up another agent.

Once the target environment is resolved, use this fixed opening as the first agent-setup surface:

**Message:**

Here's your ESS agent setup:

- ✅ Choose the starting point and target environment
- 🔄 Verify access and agent identity
- ⬜ Establish an editable Dev agent
- ⬜ Materialize the local workspace
- ⬜ Review the setup handoff

Loading available agent templates for **{environment name}**...

**End message.**

## List the catalog

If account selection was not already completed while discovering the target,
complete the shared account-selection and authorization steps in `SKILL.md`.
Before running the catalog list, complete the parent skill's **Confirm people and role availability for the selected path** checkpoint if it was not already completed for the current fresh-agent path, environment, and account. Use **Fresh-agent setup** from `permission-guidance.md`. A **Yes, the required people are present** answer does not replace the creation permission check. After **No, one or more required people are unavailable**, add **Review available agent templates without creating** before the shared account, environment, and **Go back** choices. That choice allows the catalog and read-only agent inventory below, retains that creation access is unavailable, and returns to the role handoff choices before dispatching any **Create** action.
Then run:

```text
python scripts/setup_mos_starter.py list \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}"
```

Parse `DA_MOS_STARTER_PACKAGES_JSON:`. Preserve every service row as operation evidence. Group rows by exact `packageId` and present one picker option per exact ID, using the service-provided name, version, and description as authoritative inputs. Never show the internal `packageId` to the maker. Do not describe agent templates as remaining, uninstalled, or eligible; the create response is the service-owned decision for the selected package.

After a successful catalog list, independently run the environment-scoped read-only agent listing:

```text
python scripts/setup_existing_da.py list-agents \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}"
```

Parse `DA_AGENT_LIST_JSON:` as two independent endpoint results. `minimalBots.response` is the untouched MinimalBot-card array for the explicit `CopilotStudio` and `AgentBuilder` creation sources. `copilotStudioAgents.response` is the untouched array of MakerOperations page objects, including each page's exact `Entities` and `ContinuationToken`. Each endpoint label has its own `error`. Do not treat either endpoint's empty response or failure as evidence about the other endpoint.

At the session layer, build one candidate per exact ID while retaining every untouched source object that supplied it. Match only MinimalBot `botId` to MakerOperations `cdsBotId`; never correlate by display name. The `list-agents` operation itself does not merge, classify, enrich, or directly inspect identities.

Before projecting catalog state, establish product and route evidence for the exact candidates needed by the picker. A MakerOperations BotEntity may provide an exact `schemaName`. For a MinimalBot-only candidate or a MakerOperations candidate without a usable schema, run the parent's exact selected-agent product-line reconciliation so the native component response can establish product identity. Run `inspect-agent` for each product-matched candidate to distinguish Dev, Prod, unenrolled, and unresolved routes. Keep these session-derived facts separate from the raw list response.

Catalog results and session-established candidate identities resolve workspace observations before the checked-in seed in `src/reference/da-product-setup-registry.json`. Join catalog rows only to exact candidates whose product identity was established by a MakerOperations `schemaName`, an exact native component result, or a workspace observation connecting that exact schema to the catalog product. The mapping identifies a product family; it is not starter-package provenance and does not prove the installed agent's template version.

Determine product mapping values from available operation evidence: `setup_mos_starter.py list` for package ID, catalog name, descriptions, and catalog version; `setup_mos_starter.py create` for successful `sourcePackage` identity or a definitive collision response; raw `setup_existing_da.py list-agents` responses for exact candidate IDs and source-specific fields; and exact product reconciliation for authoritative schema identity.

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

If both endpoint labels report errors, preserve both failures and continue with the catalog using only installation facts already established by workspace observations. If one endpoint fails, retain candidates from the successful endpoint and preserve that inventory is incomplete. Do not interpret any failed operation as an empty environment. Candidates with unresolved product or route evidence remain individually selectable only through exact-ID reconciliation; do not claim that unmatched agent templates are uninstalled. Test and Prod identities remain service evidence, not direct editable-Dev matches for catalog **Use** actions. A selected Prod identity can still follow the parent setup skill's established Prod-to-Dev route.

For each picker row, infer a concise user-friendly agent name only when the service-provided name or description makes the meaning unambiguous. Render `Employee Self-Service` as `Employee Self-Service (Hub)`, render `Employee Self-Service IT` or `Employee Self-Service (IT)` as `Employee Self-Service (IT)`, and render `Employee Self-Service HR` or `Employee Self-Service (HR)` as `Employee Self-Service (HR)`. If a friendly form is not clear, use the exact service-provided catalog name unchanged. This display-only inference must not change the underlying `packageId`, backend name, or create request.

For the recognized ESS agents listed below, render the following friendly agent name and default supporting description exactly as written. Do not paraphrase, shorten, or combine this copy with the service-provided description. The installed-without-matching-Dev case below replaces the default supporting description for that row.

| Friendly agent name           | Supporting description                                                                                                       |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `Employee Self-Service (Hub)` | Choose this agent if you want to organize HR, IT, or other agents behind one unified employee experience.                    |
| `Employee Self-Service (HR)`  | Create an HR agent that helps employees get HR answers and complete requests.                                                |
| `Employee Self-Service (IT)`  | Create an IT agent that helps employees resolve technical issues and access support.                                         |

For every other catalog entry, use its exact service-provided name unchanged and use `shortDescription`, then `description`, as the supporting text.

When listing succeeds, render this mostly fixed catalog surface:

**Message:**

{PRODUCT_COUNT} agent templates are available for **{environment name}**. What would you like to do?

{PRODUCT_ROWS}

**End message.**

Set `{PRODUCT_COUNT}` to the exact grouped `packageId` count and `{PRODUCT_ROWS}` to the unnumbered agent rows defined below; never assume a fixed agent count. In the host's interactive single-selection control, present those agent choices followed by **Help me decide**, **Refresh list**, and **Choose a different environment**, in that order. Leave the selection initially unset, and disable custom entry inside the control. Use **Choose an ESS agent or setup action.** as the exact question. Do not imply that selecting an installed agent creates it.

For **Help me decide**, follow the shared contract in `SKILL.md`. Ask what employee experience the maker wants to provide. Compare **Employee Self-Service (Hub)** for one experience coordinating HR, IT, or other connected agents, **Employee Self-Service (HR)** for HR answers and requests, and **Employee Self-Service (IT)** for technical support and issue resolution. For another catalog entry, use only its service-provided description. Recommend an exact current catalog choice and preserve whether that choice is **Create** or **Use — Already installed**.

For **Refresh list**, rerun the catalog list and agent list in their existing order, then rebuild the complete surface from the fresh results. This is a new maker-requested read, not an automatic retry. For **Choose a different environment**, retain the selected account and ring, read `da-environment-target.md`, rerun `list-environments`, and continue from its environment picker. Do not ask the maker to type an agent name or number any choice.

Build the agent picker as a projection of the latest successful catalog result, both endpoint-labeled list results, and the session's exact-ID product and route evidence. Group selectable rows by exact `packageId` and render exactly one choice for every resulting catalog entry, preserving the catalog-defined template set and order. Only an exact candidate whose product identity and editable Dev route were established renders **Use — Already installed**. An older workspace observation without a currently validated exact identity is historical evidence, not a sticky installed label. When both endpoint reads fail or exact candidate reconciliation remains unresolved, retain the observation only as historical evidence and state that current installation could not be established; do not convert that uncertainty into either installed or uninstalled. Rebuild this projection whenever a fresh catalog or agent-list result arrives.

When one or more exact validated Dev candidates match the same catalog entry, format that choice as **Use {friendly agent name} — Already installed**. Keep the catalog version in supporting text when present; never present it as the installed agent's version. Selecting this choice does not invoke create:

- When exactly one agent has the matching key, the effective path changes to existing-agent setup. Complete the parent checkpoint for that path, environment, and Microsoft login using **Existing-agent setup** from `permission-guidance.md`, then run the parent's selected-agent product-line reconciliation for that exact returned identity and continue through `da-existing-dev.md`.
- When multiple agents have the matching key, show those exact returned agent names followed by **Help me decide** as the standard choices, leave the selection initially unset, disable custom entry inside the control, and let the maker select one. For **Help me decide**, use the existing-agent picker guidance in `da-existing-dev.md`. The effective path then changes to existing-agent setup; complete its parent checkpoint using **Existing-agent setup** from `permission-guidance.md` before reconciliation and `da-existing-dev.md`.

When the current setup invocation retains a definitive collision for an agent template and the latest successful agent list contains no exact matching identity, format that choice as **Resolve {friendly agent name} — Existing installation not visible**. Use this exact supporting description:

> Copilot Studio confirmed that an installation exists, but it was not returned among the agents created by this Microsoft login.

This resolution state takes precedence over the historical-observation and normal **Create** rows below. Selecting it must not submit another create request. Show the same no-visible-match message and choice set defined under **Interpret the response**. For **Use a Microsoft Copilot Studio URL**, continue through direct inspection. For **I have another login we can use to try connecting to this agent**, retain the ring, environment, collided product, and package facts; return to the shared account-selection step in `SKILL.md`; then rerun `list-agents` directly for the same environment and correlate the same product before rendering the next outcome-specific surface. For **Go back**, rebuild the catalog without rerunning create.

When the current setup invocation retains a definitive collision but its latest agent-list attempt failed or returned malformed evidence, format that choice as **Resolve {friendly agent name} — Agent visibility unavailable**. Use this exact supporting description:

> Copilot Studio confirmed that an installation exists, but the agent list for this Microsoft login could not be loaded.

Selecting it must show the same unavailable-inventory message and choice set defined under **Interpret the response**. A later successful exact match replaces this resolution row with **Use {friendly agent name} — Already installed**.

When an older environment-scoped observation reports `installed: true` with source `setup_mos_starter.py create collision` and the latest successful agent list contains no exact matching identity, label the row **Create {friendly agent name} {version} — Previous create conflict**. Replace the agent template's default supporting description with:

> {default agent template supporting description} The last create attempt reported that this agent type already exists in the environment, but the existing agent was not returned among the agents created by this Microsoft login.

Selecting this row must show:

**Message:**

Copilot Studio reported a conflict the last time setup tried to create **{friendly agent name}** because this agent type already exists in the environment. The existing agent was not returned among the agents created by this Microsoft login.

**End message.**

Immediately ask **How would you like to continue?** and present **Create anyway**, **Use a Microsoft Copilot Studio URL**, **I have another login we can use to try connecting to this agent**, and **Go back** as the standard choices, with no preselected choice and custom entry disabled inside the control.

For **Create anyway**, retain the selected package facts and proceed through **Create** with a new client request UUID. Do not claim that the agent type is absent or that creation will succeed; preserve the service's success or collision result. Apply the documented direct-inspection, alternate-login, or catalog-return route when another choice is selected.

When an older environment-scoped observation reports `installed: true` but the latest successful agent list contains no exact matching identity, label the row **Create {friendly agent name} {version} — Installation status unconfirmed**. When listing failed or was incomplete, use **Installation status unavailable** instead. In either case, explain that an earlier installation was observed but current agent visibility could not confirm it. Selecting this row asks:

> Setup previously observed this ESS agent type in the environment, but current agent visibility could not confirm it. An existing agent may still be hidden from this account. Create anyway and let Copilot Studio validate the current state?

Present **Create anyway**, **Use a Microsoft Copilot Studio URL**, **Try with a different user**, and **Go back** as the standard choices, with no preselected choice and custom entry disabled inside the control. **Create anyway** retains the selected package facts and proceeds through **Create** with a new client request UUID. It does not claim that a matching agent is absent or that creation will succeed; preserve the service's success or collision result. Apply the documented route when one of the other standard choices is selected. Do not add another prohibition based on the earlier observation.

When no current exact Dev identity is established, format the choice as **Create {friendly agent name} {version}**. This label is an action, not a claim that no matching agent exists. Omit a blank version instead of showing an unresolved value. After the maker selects the choice, retain the exact `packageId`, backend `name`, catalog `version`, and friendly agent name, then begin **Create**. Retain the friendly agent name for the final exact-agent link.

Unknown catalog entries and agents without a registry match remain unclassified. Render an unknown catalog row as a **Create** choice using its exact service-provided name and do not correlate it with agents by display name.

The successful list proves target access, but not a new agent identity. Keep **Verify access and agent identity** current until create and direct attachment validation succeed.

If the catalog is empty, mark the maker's template choices unavailable and say that no agent templates are currently available in the selected environment. Present **Retry setup with another target** from `da-environment-target.md`.
If `catalogWarnings` is non-empty, tell the maker the available agent templates were incomplete -- some entries could not be read -- without repeating the warning detail itself. A row reported in `catalogWarnings` is never selectable; only offer templates backed by rows from the `packages` array.

If the command instead fails, parse `DA_MOS_STARTER_LIST_ANNOTATIONS_JSON:` and the response body (`DA_MOS_STARTER_LIST_RESPONSE_JSON:` or `..._RESPONSE_TEXT:`) the same way `create`'s response is interpreted below. Preserve the detailed evidence internally, say that agent templates could not be loaded and nothing was changed, then present **Retry setup with another target** from `da-environment-target.md`.

Read `src/reference/da-product-setup-registry.json` for setup requirements. A registry-declared connection is evaluated after creation and attachment; do not inspect or require a physical connection before dispatching create. Catalog entries without a declared requirement proceed without a connection gate.

## Create

Only after the maker selects a **Create {friendly agent name} {version}** catalog choice, render **Fresh-agent creation** from `permission-guidance.md`. Then generate a new client request UUID and run:

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

When a definitive create response returns HTTP 401 or 403, preserve its evidence and follow **Fresh-agent creation** in `permission-guidance.md`. After HTTP 401 authentication completes, return here; this route retains ownership of the next create operation and its existing request-evidence contract. HTTP 403 uses the account, environment, and **Go back** recovery routes without an immediate retry. If the evidence explicitly identifies missing first-party application approval, follow **Microsoft authorization** instead. Do not claim that a generic denial proves **Environment Maker** is missing.

> I cannot confirm whether the agent was created because communication ended before a definitive result was received. I’ll check the current catalog and agent inventory before offering the next action.

Say setup stopped only after reconciliation cannot prove an identity and the
maker selects a stop or escalation action.

When the annotations report `outcome: created`, keep the distinction between `catalogPackageVersion` and `templateVersion` in diagnostic evidence; do not explain those internal version concepts to the maker. Say that the new agent was created and setup is not complete.

The successful native create result is authoritative identity and environment-scoped installation evidence. Record its exact package, catalog, returned schema, environment, and ring through `da_product_registry.py observe` with source `setup_mos_starter.py create`, then run the parent's selected-agent product-line reconciliation with the returned identity and `--known-native-schema "{RETURNED_SCHEMA_NAME}"` before the enable-ALM operation.

When the annotations report `outcome: collision`, preserve the exact selected package ID and catalog name. Do not render an intermediate collision message. Before listing or validating collision candidates, complete the parent checkpoint for the current existing-agent path, environment, and Microsoft login and use **Existing-agent setup** from `permission-guidance.md`. When `list-agents` or `validate-agent` returns an authentication or authorization failure, follow **Existing-agent discovery and access** there; do not recommend **Environment Maker** as remediation for existing-agent access. First record and reconcile all available evidence, then render exactly one outcome-specific message immediately followed by the choice set it explains. A collision message must never be separated from its next interactive choice set by another operation or maker-facing message.

When the definitive collision response supplies an exact agent schema, record that mapping and its environment-scoped installed state immediately through `da_product_registry.py observe` with source `setup_mos_starter.py create collision`; this observation does not prove that a selectable agent is visible. Then list agents in the same environment through `setup_existing_da.py list-agents`. Correlate raw source rows only by exact ID, establish product identity through an exact MakerOperations schema or native component result, and compare that schema with the collided product. Never offer unrelated listed agents or bulk-enroll unresolved rows.

When exactly one selectable identity matches after exact-ID product reconciliation, show:

**Message:**

Copilot Studio says an agent for **{friendly agent name}** already exists. This Microsoft login can inspect **{agent display name}**.

**End message.**

Immediately ask **Use {agent display name}?** and present **Use this agent** and **Go back** as the standard choices. Do not add a separate choose-from-existing step.

When multiple selectable identities match, show:

**Message:**

Copilot Studio says an agent for **{friendly agent name}** already exists. This Microsoft login can inspect more than one matching agent.

**End message.**

Immediately ask **Choose the installed {friendly agent name}.**, present those matching identities followed by **Help me decide** and **Go back** as the standard choices, and render every agent identity option as its exact service-provided display name only. For **Help me decide**, use the existing-agent picker guidance in `da-existing-dev.md`.

Leave every collision choice initially unset and disable custom entry inside the control. Retain IDs and schemas as internal evidence; never display an ID, schema, product key, or **schema will be verified** annotation in either the message or choice panel.

For a selected identity whose matching MakerOperations BotEntity supplies a usable schema, pass that exact schema into the parent's selected-agent product-line reconciliation as `--known-native-schema "{RETURNED_SCHEMA_NAME}"`. Otherwise run both exact identity probes so the native component result can establish schema identity. Only a supported native `found` result may continue to route inspection and optional enrollment; a native `not-found`, access failure, or uncertain result must stop without offering enrollment. Successful enrollment requires reconciliation and route inspection before the normal attachment path; skipped enrollment with established supported native identity returns to the attachment command below with `--allow-unenrolled-authoring`.

If both endpoint labels report errors, or neither endpoint supplies structurally usable evidence, show:

**Message:**

Copilot Studio says an agent for **{friendly agent name}** already exists, but I couldn’t load the agent list for this Microsoft login.

**End message.**

Immediately ask **How would you like to connect to this agent?** and present **Retry agent list**, **Use a Microsoft Copilot Studio URL**, **I have another login we can use to try connecting to this agent**, and **Go back** as the standard choices. **Retry agent list** reruns only the same read-only `list-agents` operation for the retained environment and then renders the resulting outcome-specific surface. Apply the direct-inspection and alternate-login routes below for their corresponding choices.

If one endpoint reports an error, the other endpoint returns no exact matching identity, and no matching exact identity is otherwise established, use the same surface but replace `couldn’t load the agent list` with `couldn’t load the complete agent list`. Do not treat the successful endpoint's empty or nonmatching response as proof that the collided agent is hidden.

If both endpoint reads succeed but no exact identity matches, show:

**Message:**

Copilot Studio says an agent for **{friendly agent name}** already exists, but it was not returned among the agents created by this Microsoft login.

**End message.**

Immediately ask **How would you like to connect to this agent?** and present **Use a Microsoft Copilot Studio URL**, **I have another login we can use to try connecting to this agent**, and **Go back** as the standard choices instead of presenting unrelated agents.

For **Use a Microsoft Copilot Studio URL**, ask for the exact Microsoft Copilot Studio URL and continue through direct inspection in `da-existing-dev.md`. For **I have another login we can use to try connecting to this agent**, retain the ring, environment, collided product, and package facts; return to the shared account-selection step in `SKILL.md`; then rerun `list-agents` directly for the same environment and correlate the same product before rendering the next outcome-specific surface. Neither path creates or replaces an agent.

For **Go back**, preserve the collided create result and its client request UUID, then render the complete action-oriented catalog composed from every selectable row in the latest successful catalog result and latest agent-list attempt. The collided product must render as the applicable **Resolve** row above, not as **Create** or **Installation status unconfirmed**. Do not display another standalone collision message before the catalog. A later create is available only if fresh evidence removes the resolution state and the catalog projection again produces a **Create** row; every such create uses a new client request UUID and never repeats the collided request.

## Prepare the authoring route

Build `{ACTUAL_AGENT_URL}` as `{COPILOT_STUDIO_ORIGIN}/environments/{ENVIRONMENT_ID}/copilots/{RETURNED_AGENT_ID}/details?agentBackend=cosmos`, using the origin retained by **Resolve the service ring** and the exact environment and agent IDs from the successful create result. An explicit Preview target keeps its Preview origin even though its logical ring is `prod`.

After a successful create, show:

**Message:**

The agent was created.

> **Open [{USER_FRIENDLY_AGENT_NAME}]({ACTUAL_AGENT_URL}) in Classic Copilot Studio.**

**End message.**

Inspect the service-owned authoring route before offering enrollment:

```text
python scripts/setup_existing_da.py inspect-agent \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}" \
  --agent-id "{RETURNED_AGENT_ID}"
```

When `DA_AGENT_ROUTE_JSON:` reports `routeStatus: resolved`, `alm.isEnrolled: true`, and `realm: dev`, continue directly to **Attach** without an enrollment write. When it reports `routeStatus: not-established` and `alm.isEnrolled: false`, read `alm-enrollment.md` and follow its exact **Continue (Recommended)** / **Skip enrollment** choice, mutation evidence, read-back, and route-inspection contract. A resolved Dev result from successful enrollment returns to the normal **Attach** command below. Skipped enrollment with exact supported native identity returns to the same command with `--allow-unenrolled-authoring`. For another realm, service failure, or transport failure, preserve the evidence and stop without enrollment, attachment, or publication.

Do not invoke `ensure-alm` directly from this file. The shared path owns maker confirmation, operation invocation, result interpretation, and the non-mutating skip outcome.

## Attach

After the initial route inspection establishes a Dev route, successful enrollment establishes and verifies that route, or skipped enrollment authorizes components-based local authoring, run:

```text
python scripts/setup_existing_da.py attach \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}" \
  --agent-id "{RETURNED_AGENT_ID}" \
  --setup-source mos-starter \
  --expected-schema-name "{RETURNED_SCHEMA_NAME}"
```

Append `--allow-unenrolled-authoring` only for the shared path's explicit **Skip enrollment** result. Preserve `--setup-source mos-starter` and `--expected-schema-name`.

The normal attachment validates the returned agent through its direct Dev route and component identity. The skip attachment validates exact direct identity and `/components` without establishing or recording a Dev ALM realm. Neither mode requires published Dev configuration. It resolves any connection requirement from the product registry by exact agent identity and records that requirement on canonical `SETUP-05`. On failure, preserve the command's specific `ERROR:` text and any canonical `active_step` and `failure_causes` as diagnostic evidence. Translate them into the visible setup stage and a plain explanation of the unmet prerequisite as described in `da-existing-dev.md`; never show internal step IDs or raw technical output as ordinary maker copy. Publishing is outside foundation setup and is not remediation for an attachment failure. On success, parse `DA_EXISTING_DEV_SETUP_JSON:`. When attachment reports `connectionStatus: workspace-ready`, mark the access, identity, editable-agent, and materialization stages complete, then run the three setup-readiness FlightChecks and broad connection diagnostic as the single presentation unit defined in `da-existing-dev.md`. Complete every check whose prerequisites remain available before producing the factual workspace and runtime-readiness handoff. When an operation requires maker action or prevents later checks from running, state the observed blocker and supported recovery. The request-scoped create evidence intentionally remains as an audit note. Do not publish, remove, or replace components from this path.

After all four FlightChecks have been attempted, render the factual workspace and runtime-readiness report from `da-existing-dev.md` using **New ESS agent** as the starting point, including when `connectReady` is false.
For every non-created outcome (`pre-dispatch-failure`, `collision`, `rejected`, `malformed-success`, `source-package-mismatch`, or an uncertain response or transport failure), end the create operation. The existing read-only `list` and `setup_existing_da.py validate-agent`/`list-agents` commands remain available for a separately requested inspection.

Connection setup is outside this foundation path. Never invoke `/connect`, install a connector, or configure Dataverse, publishing, promotion, or telemetry from this skill.
