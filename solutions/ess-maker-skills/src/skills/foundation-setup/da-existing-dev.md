<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Set Up an Existing DA Dev Agent

Connect this ADK workspace to an existing editable DA Dev agent. Do not run the Dataverse setup path, request a Dataverse URL, create a preferred solution, or start Dataverse MCP.

Use one Power Platform environment per ADK workspace. The workspace can contain multiple Dev agents from that environment and has one active agent. A target in another environment uses the parent skill's conflicting-environment flow.

Before this file runs its first `list-agents`, `inspect-agent`,
`validate-agent`, or `attach` operation, complete the parent skill's **Confirm
people and role availability for the selected path** checkpoint if it was not
already completed for the current existing-agent path, environment, and
account. Use **Existing-agent setup** from `permission-guidance.md`. A **Yes,
the required people are present** answer does not replace the exact-agent
access check below.

## Connect from a Microsoft Copilot Studio URL

Ask for the Microsoft Copilot Studio URL only when the parent setup router has neither a current-invocation inspection result nor a complete recorded local target. A complete Microsoft Copilot Studio URL is preferred for a new target because it identifies the environment and agent without tenant-wide inventory. Never request a URL merely to revalidate the exact agent already recorded for this workspace.

Infer the environment ID, agent ID, and service ring from the URL. When the URL
does not identify the ring, use **Resolve the service ring** in
`src/skills/foundation-setup/da-environment-target.md` exactly. Ask only when
the environment ID or agent ID is unclear.

Use a current-invocation `DA_AGENT_ROUTE_JSON:` result when the parent setup
router already inspected the supplied or recorded agent. The result is based on
the direct Swagger-defined `MinimalBotCard`; this setup inspection does not call
the ALM `/realms` endpoint. Otherwise, use the
shared authorization message from `SKILL.md`, render the **Agent access check**
from `permission-guidance.md`, then run:

```text
python scripts/setup_existing_da.py inspect-agent \
  --environment-id "{ENVIRONMENT_ID}" \
  --agent-id "{AGENT_ID}" \
  --ring "{RING}"
```

Parse `DA_AGENT_ROUTE_JSON:`. Continue only when the current invocation has a
service result reporting `routeStatus: resolved` and `realm: dev`. This route
check does not require readable `/configure` state: an unpublished Dev agent can
still be fetched and materialized for local authoring. Do not infer the realm
from the URL, agent name, environment metadata, canonical setup state, or
conversation history. When `routeStatus` is `not-established` and
`alm.isEnrolled` is `false`, preserve that the native agent exists, explain that
setup could not establish its ALM authoring route, then read
`src/skills/foundation-setup/alm-enrollment.md` and follow
its exact choice surface and operation sequence. When the maker skips enrollment
after exact native product identity was established, that shared path returns to
the attachment contract below with `--allow-unenrolled-authoring`; it does not
reinterpret the absent ALM route as Dev. If the service reports another realm,
explain that this setup path requires a Dev agent and stop.

After a Dev result, show:

> Dev agent route verified. Preparing its local authoring workspace...

Run:

```text
python scripts/setup_existing_da.py attach \
  --environment-id "{ENVIRONMENT_ID}" \
  --tenant-id "{TENANT_ID}" \
  --host "{VALIDATED_HOST}" \
  --ring "{RING}" \
  --api-version "{API_VERSION}" \
  --agent-id "{AGENT_ID}"
```

Append `--allow-unenrolled-authoring` only when the maker explicitly selected
**Skip enrollment** in `alm-enrollment.md` and selected-agent product
reconciliation had already established the exact supported native identity.

The access token supplies the tenant identity during initial inspection; do not infer it from the environment ID.

Normally the command validates the exact agent identity and the Swagger-defined direct metadata as an enrolled Dev realm, fetches the authoritative component change set, confirms its component identity and schema, converts supported authoring components with the Microsoft Object Model serializer, and materializes the local workspace. With the explicit unenrolled-authoring flag, it validates the exact direct `botId`, requires that same direct metadata to normalize to `alm.isEnrolled: false`, and relies on the exact `/components` identity and schema for authoring capability. Neither mode calls the ALM `/realms` endpoint. The unenrolled mode records `alm.isEnrolled: false` and omits `realm` rather than serializing `realm: null` or fabricating Dev. A later normal attachment after successful enrollment can update the same workspace to `alm.isEnrolled: true` and the normalized direct `realm: dev`. The command does not require published Dev configuration in either mode; publishing is outside foundation setup and is not attachment remediation. The command persists canonical setup progress for that agent before materialization when identity is complete. Complete the native FlightCheck maintenance below before treating the agent's `connect_ready: true` as current.

If Object Model dependencies are missing, run:

```text
python scripts/install_agentbuilder_object_model.py
```

This prerequisite check runs before authentication or remote agent validation. Report it as a local prerequisite failure, then rerun the same attach command after installation.

## Inspect without attaching

Use these independent read-only operations when setup needs to classify, select, or validate a target:

```text
python scripts/setup_existing_da.py inspect-agent \
  --environment-id "{ENVIRONMENT_ID}" \
  --agent-id "{AGENT_ID}" \
  --ring "{RING}"

python scripts/setup_existing_da.py validate-agent \
  --environment-id "{ENVIRONMENT_ID}" \
  --agent-id "{AGENT_ID}" \
  --ring "{RING}"
```

`inspect-agent` returns the service-owned route realm. `validate-agent` verifies one exact editable Dev agent without writing setup state or workspace files. Do not run `validate-agent` immediately before `attach` merely to create another visible step; `attach` performs its own exact validation.

If the maker provides an environment URL without an agent ID, list the environment's realm-classified agent inventory:

```text
python scripts/setup_existing_da.py list-agents \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}"
```

Parse `DA_AGENT_LIST_JSON:` as endpoint-labeled evidence. `minimalBots.response` is the untouched array returned by `GET /copilotstudio/minimalBots/api` for the explicit `CopilotStudio` and `AgentBuilder` creation sources. `copilotStudioAgents.response` is the untouched array of paged response objects returned by `GET /copilotstudio/agents`; each page retains its exact `Entities` and `ContinuationToken` fields. Each endpoint label also has an `error` field. The command does not merge, deduplicate, rename, enrich, classify, or directly inspect any listed identity.

When `list-agents`, `inspect-agent`, `validate-agent`, or `attach` returns an
authentication or authorization failure, follow **Existing-agent discovery and
access** in `permission-guidance.md`. Use its inventory message for a failed
list and its exact-agent message for a failed direct operation. Do not recommend
**Environment Maker** as remediation for access to an existing agent.

Interpret the two sources independently. A successful empty response from one source does not negate identities returned by the other, and one endpoint's error does not make the other endpoint unavailable. Preserve every endpoint-specific error. At the session layer, correlate candidates only by exact `botId` from a MinimalBot card or exact `cdsBotId` from a MakerOperations BotEntity. Retain both untouched source objects when the same ID appears in both responses, but render only one picker option per exact ID. Never correlate by display name.

Use exact source fields only. A MakerOperations BotEntity may provide `displayName` and `schemaName`; a MinimalBot card may provide `shortBotName`, `fullBotName`, and `realm`, but it does not provide schema identity. Do not copy a value between source-specific fields or insert a synthesized schema into either response. Every maker-facing agent option contains only the selected source's service-provided display name. Do not append a realm, enrollment state, ALM status, source, or preparation suffix.

When both endpoint labels report an error, agent inventory is unavailable. Preserve both failures and say:

> I couldn’t load the agent list for this Microsoft login.

Then use **Retry setup with another target** from `da-environment-target.md`.

When exact-ID candidates are returned by either endpoint, show their exact service-provided display names followed by **Help me decide** and ask the maker to choose one exact identity. Every agent identity option contains only its service-provided display name; the separate help action is not an agent identity. Run the parent's selected-agent product-line reconciliation for the selected ID before realm-specific setup:

For **Help me decide**, follow the shared contract in `SKILL.md`. Ask what the intended agent is used for, which name or owner the maker recognizes, and whether they have its Microsoft Copilot Studio URL. Recommend only one exact returned display name grounded in the maker's answer. If the intended identity still cannot be established, tell the maker not to guess and explain that its Microsoft Copilot Studio URL or creator login can resolve the target.

- When the matching MakerOperations BotEntity has a non-empty exact `schemaName`, pass it as `--known-native-schema "{RETURNED_SCHEMA_NAME}"`.
- When no matching MakerOperations BotEntity supplies a usable schema, do not synthesize one or withhold the candidate. Run both exact identity probes so the native component response can establish product identity.
- After successful product reconciliation, run `inspect-agent` for the exact ID. A resolved Dev route continues through normal validation or attachment. A resolved Prod route continues through `da-prod-to-dev.md`; do not validate or attach the Prod ID as though it were Dev. An unenrolled route may offer optional enrollment or `--allow-unenrolled-authoring` only under the established rules. Native not-found, access failure, or uncertainty uses stopped-result recovery.

Never bulk-enroll, validate, or attach unselected rows.

When both endpoint reads succeed and both contain no identities, say:

> No agents created by this Microsoft login were returned for this environment.

Present **Retry setup with another target** from `da-environment-target.md`, including its **Use a Microsoft Copilot Studio URL** choice. For an exact agent selected through that URL, run both independent identity probes in the full selected-agent product-line reconciliation before validating it directly.

When one endpoint reports an error and the other succeeds with no identities, do not use the empty-list message. State that the successful source returned no agents but the other source could not be loaded, then present the same recovery choices.

## Maintain native FlightCheck evidence

After every successful `attach` or unchanged existing-workspace resume, run the three setup-readiness FlightChecks and the broad connection diagnostic for the exact agent. Attempt every check whose prerequisites remain available and present all four together.

Before running `ENV-CAPACITY-001` for the first time in the invocation, render
the **Capacity check** from `permission-guidance.md`.

Run each checkpoint into its dedicated local evidence folder:

```text
python scripts/flightcheck/cli.py --checkpoint DA-AGENT-001 --quiet-auth --no-open --output .local/setup/agents/{AGENT_ID}/flightcheck/DA-AGENT-001
python scripts/flightcheck/cli.py --checkpoint ENV-CAPACITY-001 --quiet-auth --no-open --output .local/setup/agents/{AGENT_ID}/flightcheck/ENV-CAPACITY-001
python scripts/flightcheck/cli.py --checkpoint "DA-CONN-*" --quiet-auth --no-open --output .local/setup/agents/{AGENT_ID}/flightcheck/DA-CONN
python scripts/flightcheck/cli.py --checkpoint DA-CONTENT-001 --quiet-auth --no-open --output .local/setup/agents/{AGENT_ID}/flightcheck/DA-CONTENT-001
```

FlightCheck resolves the ring from the explicit ring persisted by setup and validates it against the canonical Power Platform environment endpoint using `ring_from_environment_host()`. If the ring is missing, malformed, or contradictory, do not assume production. Ask the maker to confirm whether the environment uses **prod**, **preprod**, or **test**, then rerun the affected checkpoint with `--ring "{CONFIRMED_RING}"`.

After each setup-readiness run, even when that FlightCheck exits nonzero, apply its result to canonical setup state. Apply agent access and content directly:

```text
python scripts/setup_existing_da.py maintain-flightcheck --agent-id "{AGENT_ID}" --checkpoint DA-AGENT-001 --results .local/setup/agents/{AGENT_ID}/flightcheck/DA-AGENT-001/results.json
python scripts/setup_existing_da.py maintain-flightcheck --agent-id "{AGENT_ID}" --checkpoint DA-CONTENT-001 --results .local/setup/agents/{AGENT_ID}/flightcheck/DA-CONTENT-001/results.json
```

Inspect the exact `ENV-CAPACITY-001` row before applying it. `Passed` requires an observed allocation greater than zero and can be applied normally. `Failed` remains blocked. A `Warning` means the Licensing API ran successfully and found zero allocated credits; do not complete the capacity step from that result without an explicit manual override.

For `Warning`, present:

**Message:**

### Capacity follow-up

FlightCheck checked **{friendly environment name or selected Power Platform environment}** and found **0 allocated Copilot Credits**. Your agent and local authoring workspace are already available.

1. Open [Power Platform Admin Center]({POWER_PLATFORM_ADMIN_ORIGIN}/billing/licenses/copilotStudio/overview).
2. In the left navigation, select **Licensing**.
3. Under **Products**, select **Copilot Studio**.
4. Select **Manage Copilot Credits**.
5. Find **{friendly environment name or selected Power Platform environment}**.
6. Allocate more than 0 Copilot Credits and save the change.

**End message.**

Present these standard choices:

- **Check again**
- **Not yet**

For **Not yet**, leave capacity unresolved. The final readiness table remains available and shows capacity as **⛔ Action required**.

For **Check again**, rerun `ENV-CAPACITY-001` before applying capacity state. If the new result is `Passed`, apply it normally. If it is still `Warning`, say that the recheck still found 0 allocated credits and present:

- **Check again**
- **Continue with manual override**

If the recheck cannot produce a verdict, preserve its failure category and safe request or correlation evidence, explain why verification is unavailable, and offer its supported next action. Never treat the maker's statement that capacity was allocated as verification.

For **Continue with manual override**, apply the current `Warning` evidence explicitly:

```text
python scripts/setup_existing_da.py maintain-flightcheck --agent-id "{AGENT_ID}" --checkpoint ENV-CAPACITY-001 --results .local/setup/agents/{AGENT_ID}/flightcheck/ENV-CAPACITY-001/results.json --manual-overridden
```

When the status is `Manual`, automatic verification did not produce an allocation verdict. Present this guidance and confirmation before applying the result:

**Message:**

### Capacity follow-up

We weren’t able to automatically verify capacity for this environment. Your agent and local authoring workspace are already available.

#### Copilot Studio message capacity

1. Open [Power Platform Admin Center]({POWER_PLATFORM_ADMIN_ORIGIN}/billing/licenses/copilotStudio/overview).
2. In the left navigation, select **Licensing**.
3. Under **Products**, select **Copilot Studio**.
4. Select **Manage Copilot Credits**.
5. Find **{friendly environment name or selected Power Platform environment}**.
6. Confirm that the environment has allocated Copilot Credits. Setup requires a nonzero allocation; for initial use, we recommend allocating **500 or more Copilot Credits**.

If you cannot view capacity settings, ask a **Power Platform administrator** to verify the allocation for this exact environment.

**End message.**

Then ask exactly:

**After checking Power Platform Admin Center, is Copilot Studio message capacity allocated to this environment?**

Present these standard choices:

- **Yes — capacity is allocated**
- **Not yet**
- **Help me decide**

For **Help me decide**, follow the shared contract in `SKILL.md`. Ask what the maker or administrator can see for this exact environment in **Manage Copilot Credits**. Recommend **Yes — capacity is allocated** only when they confirm a positive allocation for this environment; recommend **Not yet** when it has not been checked, cannot be viewed, or still shows zero. This conversation is not capacity verification and does not apply manual attestation.

For **Yes — capacity is allocated**, apply the same current evidence with explicit attestation:

```text
python scripts/setup_existing_da.py maintain-flightcheck --agent-id "{AGENT_ID}" --checkpoint ENV-CAPACITY-001 --results .local/setup/agents/{AGENT_ID}/flightcheck/ENV-CAPACITY-001/results.json --manual-attested
```

For **Not yet**, leave capacity unresolved. After the maker allocates capacity, offer **Check again** and rerun `ENV-CAPACITY-001`.

Use the `{POWER_PLATFORM_ADMIN_ORIGIN}` retained by **Resolve the service ring** in `da-environment-target.md`. Do not reconstruct it from `{RING}` alone: an explicit Preview target remains logical ring `prod` while retaining the Preview admin-center origin.

When canonical `SETUP-05` contains a registry-declared `requirement`, also apply the broad connection result:

```text
python scripts/setup_existing_da.py maintain-flightcheck --agent-id "{AGENT_ID}" --checkpoint "DA-CONN-*" --results .local/setup/agents/{AGENT_ID}/flightcheck/DA-CONN/results.json
```

Parse every `DA_SETUP_FLIGHTCHECK_JSON:` result. Its `state`, `connectReady`, `activeStep`, and `failureCauses` are the setup-readiness evidence. Use the three maintained checks and the exact Self-Help diagnostic projection below for maker-facing evidence and remediation. After successful materialization, render the compact in-progress runtime-readiness line defined below before the first check and whenever one of its four check statuses changes. Finish each snapshot before running the next operation or opening a maker question. Do not repeat a snapshot when no status changed. Attempt every available check before producing the final runtime-readiness table. When maker action is required or an operation prevents later checks from running, render the current in-progress line, then state the observed blocker and supported recovery. Do not use a FlightCheck result to roll back a completed maker-facing checklist stage.

Read `src/reference/da-product-setup-registry.json` as the authoritative product requirement registry. Attachment resolves the product only by an exact registered catalog display name or agent schema name and records the declared requirement on `SETUP-05`. Do not infer requiredness from a partial name, persona wording, or the logical references returned by FlightCheck.

`DA-CONN-*` remains broad diagnostic evidence. Preserve its complete result locally, but do not use its aggregate summary row for setup UX or canonical state. When `SETUP-05` declares a requirement, inspect only the individual row whose description identifies that exact `connectorApiName`; the current registry maps the IT product to `shared_alchemy`, displayed as **Microsoft 365 Self-Help**. Do not project `shared_service-now` or another undeclared reference into the table, remediation, Overall status, or completion choices.

For the exact registry-required row:

- `Passed` is **✅ Ready**.
- `Warning` is **⚠️ Ready with limitation** and retains its warning disclaimer.
- `NotConfigured` or `Failed` is **⛔ Action required**.
- `Error` is **⚠️ Check unavailable** and retains the observed authentication, permission, or service evidence.
- A completed diagnostic without the required exact row is **⛔ Action required** because the required connection could not be verified.

When the registry declares no connection requirement for the resolved product, keep `SETUP-05` skipped and render Connections as **➖ Not required**. When the agent does not exactly match a registered product, also keep `SETUP-05` skipped, but state that no foundation connection requirement was applied because the product identity is not registered; do not claim that the registry declares no requirement for that product. A required connection does not prevent creation, attachment, or workspace materialization, but it does keep canonical `connectReady` false until its exact post-attachment evidence is ready.

`ENV-CAPACITY-001` uses the Licensing API when available. `Passed` is **✅ Ready** and requires an observed allocation greater than zero. `Warning` is **⛔ Action required** until a recheck passes or the maker chooses **Continue with manual override**; an accepted `--manual-overridden` result is **✅ Ready — manually overridden**. `Failed` is **⛔ Action required** for a checkpoint error that prevents trustworthy evaluation, such as an unavailable environment identity. `Manual` is **⛔ Manual confirmation required** until the maker explicitly confirms the allocation; an accepted `--manual-attested` result is **✅ Ready — manually confirmed**. Manual confirmation is allowed only for an unreadable allocation, while manual override is allowed only for a successful check that found zero. Neither path converts its source evidence into an automated pass. Non-queryable governance prerequisites are outside this check; disclose that limitation without treating it as a setup policy or a downstream `/connect` deferral.

## Interpret results

Canonical setup state is authoritative for each agent's setup progress and readiness. Local workspace materialization is complete when attachment reports `connectionStatus: workspace-ready`, canonical workspace evidence is present, and `SETUP-07` is `done`. Runtime readiness is complete only when every step in that agent's canonical record is `done` and the final `DA_SETUP_FLIGHTCHECK_JSON:` reports `connectReady: true`.

Canonical state records native environment access, capacity, the registry-declared product connection requirement, and baseline content readiness. Preferred-solution configuration remains skipped because it does not apply to the DA-only foundation path. Undeclared product and integration references remain diagnostic and do not alter canonical completion.

Before materialization completes, render an incomplete `SETUP-03` as **Establish an editable Dev agent** and an incomplete `SETUP-07` as **Materialize the local workspace**. After materialization completes, render blocked capacity or content steps and the Self-Help diagnostic only in the runtime-readiness table. Explain each unmet prerequisite in maker language and offer the bounded remediation supported by that evidence.

If content was synced to the local workspace but the returned result is not workspace-ready and supplies no specific failure cause, keep **Materialize the local workspace** current and show:

> The agent content was synced to your local workspace, but the workspace is not ready to connect. Setup is not complete and has stopped.

Preserve the observed evidence and offer **Retry workspace materialization** and **Go back**. **Retry workspace materialization** reruns attachment after the maker confirms that the reported prerequisite was addressed. When the error specifically identifies an unmanaged workspace or changed managed files, also offer the parent skill's **Reset and use this workspace** or the explicit **Checkpoint and refresh** path as applicable. Do not offer reset for an unrelated service or projection failure.

After successful materialization, use this compact two-line snapshot while readiness evidence is still being gathered:

**Message:**

**Runtime readiness:** Agent access {agent access progress status} · Capacity {environment capacity progress status} · Connections {connections progress status} · Content {agent content progress status}

**{readiness progress status}: {readiness progress summary}**

**End message.**

Use **✅ Ready** only for current passing evidence, **🔄 Checking** only for the operation that will run next, **⬜ Pending** for an applicable check that has not run, **⛔ Action required** for an authoritative actionable failure or a zero allocation awaiting recheck or override, **⛔ Manual confirmation required** for unreadable capacity awaiting the maker's answer, **⚠️ Check unavailable** for an attempted check without a verdict, **⚠️ Ready with limitation** for the supported connection warning state, **➖ Not required** only when the registry explicitly declares no requirement, **✅ Ready — manually confirmed** only after accepted capacity attestation, and **✅ Ready — manually overridden** only after the maker accepts a current automatic zero-allocation result.

While checks remain, render the second line's status as **🔄 {resolved count} of 4 resolved** and say that setup is still verifying runtime readiness. Count **Ready**, **Ready — manually confirmed**, **Ready — manually overridden**, **Ready with limitation**, **Action required**, **Check unavailable**, and **Not required** as resolved; do not count **Checking**, **Pending**, or **Manual confirmation required**. When maker action is required before checks can continue, render the second line's status as **⛔ Waiting for action** and identify the blocking check without converting pending checks into failures. Do not calculate or display the final **Overall** verdict in this in-progress snapshot.

After successful materialization and after the three setup-readiness checks and broad connection diagnostic have been attempted, build the agent link from `DA_EXISTING_DEV_SETUP_JSON:` and build the runtime-readiness table from the applied FlightCheck results and canonical state. Render both even when `connectReady` is false.

Infer a concise user-friendly agent name from the authoritative product or agent display name when its meaning is unambiguous. For example, render `Employee Self-Service IT` as `Employee Self-Service (IT)` and `Employee Self-Service HR` as `Employee Self-Service (HR)`. If a friendly form is not clear, use the authoritative backend display name unchanged. Never use a schema name or agent ID as link text.

Build the exact Microsoft Copilot Studio URL for the agent as `{COPILOT_STUDIO_ORIGIN}/environments/{ENVIRONMENT_ID}/copilots/{AGENT_ID}/details?agentBackend=cosmos`, using the retained origin from **Resolve the service ring** and the exact environment and agent IDs from setup evidence. An explicit Preview target keeps its Preview origin even though its logical ring is `prod`. Never link to the environment's agent-list page.

**Message:**

Your local workspace is ready for authoring.

> **Open [{USER_FRIENDLY_AGENT_NAME}]({ACTUAL_AGENT_URL}) in Classic Copilot Studio.**

For listing newer declarative agents, use the Classic experience. From the new experience, open the **…** menu beside your profile, select **Open classic experience**, then select **Skip feedback** or **Open in a new tab**.

### Runtime readiness

| Check                | Status                         | Details                                 |
| -------------------- | ------------------------------ | --------------------------------------- |
| Agent access         | {agent access status}          | {agent access evidence summary}         |
| Environment capacity | {environment capacity status}  | {environment capacity evidence summary} |
| Connections          | {connections status}           | {connections evidence summary}          |
| Agent content        | {agent content status}         | {agent content evidence summary}        |
| **Overall**          | **{overall readiness status}** | **{maker-facing readiness summary}**    |

**End message.**

Use the same five rows and order in every runtime-readiness table. Map the three setup-readiness checks directly from their evidence: `Passed` is **✅ Ready**, an actionable failure is **⛔ Action required**, an unavailable check is **⚠️ Check unavailable**, and a check without current evidence is **⬜ Not checked**. Build the Connections row only from the registry-declared requirement and its exact diagnostic row.

Each evidence summary states whether the check ran, its target, and the result file's `started` observation time when available. Preserve the row's safe `serviceStatus`, `requestId`, `outcome`, and other non-secret evidence when a check is unavailable. Do not expose tokens, authorization headers, or customer content.

Convert every maker-facing FlightCheck timestamp to the local timezone of the machine running setup. Render timestamps at second precision using `YYYY-MM-DDTHH:mm:ss`, for example `2026-10-03T01:43:19`. Truncate fractional seconds; do not round. Do not display a UTC suffix, numeric offset, or timezone abbreviation. Apply this format to every `{observation time}` and `{recorded time}` in the runtime-readiness table. Format presentation only; do not rewrite persisted evidence. If a source timestamp is missing, invalid, or lacks timezone information, omit the displayed time rather than inferring one.

Use concise factual details:

- Agent access: **Access to {agent display name} was verified. Observed at {observation time}.**
- Environment capacity after an automatic pass: **{allocated credits} credits are allocated to {environment display name}. Observed at {observation time}.**
- Environment capacity after attestation: **Automatic verification was unavailable for {environment display name}. Capacity was manually confirmed at {recorded time}.**
- Environment capacity after override: **A recheck of {environment display name} at {observation time} found 0 allocated credits. You selected Continue with manual override.**
- Connections when ready: **{required connection display name} is connected for {environment display name}. Observed at {observation time}.**
- Agent content when ready: **Agent content is present in your local workspace. Observed for {agent display name} at {observation time}.**

Calculate Overall from canonical `connectReady`. When `connectReady` is true, render Overall as **✅ Foundation ready**. When it is false after materialization, render Overall as **⚠️ Foundation needs attention** and state that local authoring is ready while the setup-owned prerequisites remain. Do not add inferred warnings or place publishing, connector installation, promotion, product-extension configuration, or non-queryable governance requirements in this table.

When the registry-required `shared_alchemy` result is `NotConfigured` or `Failed`, append this section after the complete table and before the shared completion choices:

**Message:**

### Connection follow-up

Complete this connection to finish foundation readiness. Your agent and local authoring workspace are already available.

#### Microsoft 365 Self-Help

For `NotConfigured`, show:

1. Open [Power Apps]({POWER_APPS_ORIGIN}/).
2. Select **{friendly environment name or selected Power Platform environment}**.
3. Open **Connections**.
4. Select **New connection**.
5. Search for **Microsoft 365 Self-Help**.
6. Create the connection and complete authentication.

For `Failed`, replace steps 4 through 6 with: open the existing **Microsoft 365 Self-Help** connection and repair its authentication.

When the connection is ready, return here and ask me to check it again.

**End message.**

Use the `{POWER_APPS_ORIGIN}` retained by **Resolve the service ring** in `da-environment-target.md`. Do not reconstruct it from `{RING}` alone or collapse an explicit Preview target to the production maker portal.

Do not append this section for a ready, warning, or unavailable required result, or when the registry declares no requirement. Do not add another completion choice. A later request to check the connection reruns the broad diagnostic and reapplies its exact required row to `SETUP-05`.

This report is a factual handoff, not another readiness gate. If the maker disputes a fact, inspect the underlying operation evidence rather than changing canonical state conversationally. Then present the shared completion choices from `SKILL.md`.

Preserve service status, error code, request ID, and local projection-failure evidence for diagnosis. In ordinary maker-facing copy, explain the specific service or conversion failure in plain language without exposing raw technical output. Do not replace it with a generic setup error.

For an identity or authorization failure, preserve the operation evidence and follow **Existing-agent discovery and access** in `permission-guidance.md`. Run the account picker only after the maker chooses the different-account route. Retain the selected environment and exact agent, rerender **Existing-agent setup** for the new login, then let the session invoke the relevant existing operation again. Use `--tenant-id` only when the maker supplies the tenant that owns the target and understands that tenant selection does not grant access.

## Refresh changed content

An unchanged rerun verifies the remote snapshot without overwriting local files.

If the remote snapshot changed, or the existing workspace uses an older projection, ask:

> The local workspace differs from the current agent snapshot. Refresh will create a checkpoint and replace the managed agent files; it will not merge them.

Present these standard choices:

- **Checkpoint and refresh**
- **Keep local files unchanged**

For **Keep local files unchanged**, preserve the managed local files and canonical setup state, then say:

> Your local files were left unchanged. Setup stopped without refreshing them.

This choice ends the current setup attempt at the refresh decision. FlightChecks and the final handoff resume after a later unchanged attachment or successful refresh.

Continue only after the maker explicitly selects **Checkpoint and refresh**:

```text
python scripts/setup_existing_da.py attach \
  --environment-id "{ENVIRONMENT_ID}" \
  --tenant-id "{TENANT_ID}" \
  --host "{VALIDATED_HOST}" \
  --ring "{RING}" \
  --api-version "{API_VERSION}" \
  --agent-id "{AGENT_ID}" \
  --refresh
```

Report the returned checkpoint number. Do not imply a three-way merge.
