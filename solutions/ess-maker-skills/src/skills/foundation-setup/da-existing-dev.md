<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Set Up an Existing DA Dev Agent

Connect this ADK workspace to an existing editable DA Dev agent. Do not run the Dataverse setup path, request a Dataverse URL, create a preferred solution, or start Dataverse MCP.

Use one Power Platform environment per ADK workspace. The workspace can contain multiple Dev agents from that environment and has one active agent. A target in another environment uses **Create and open a new workspace** from the parent skill.

## Connect from the agent URL

Ask for the URL of the agent in Copilot Studio only when the parent setup router has neither a current-invocation inspection result nor a complete recorded local target. A complete agent URL is preferred for a new target because it identifies the environment and agent without tenant-wide inventory. Never request a URL merely to revalidate the exact agent already recorded for this workspace.

Infer the environment ID, agent ID, and service ring from the URL. When the URL
does not identify the ring, use **Resolve the service ring** in
`src/skills/foundation-setup/da-environment-target.md` exactly. Ask only when
the environment ID or agent ID is unclear.

Use a current-invocation `DA_AGENT_ROUTE_JSON:` result when the parent setup
router already inspected the supplied or recorded agent. Otherwise, use the
shared authorization message from `SKILL.md`, then run:

```text
python scripts/setup_existing_da.py inspect-agent \
  --environment-id "{ENVIRONMENT_ID}" \
  --agent-id "{AGENT_ID}" \
  --ring "{RING}"
```

Parse `DA_AGENT_ROUTE_JSON:`. Continue only when the current invocation has a
service result reporting `realm: dev`. Do not infer the realm from the URL,
agent name, environment metadata, canonical setup state, or conversation
history. If the service reports another realm, explain that this setup path
requires an editable Dev agent and stop.

After a Dev result, show:

> Editable Dev agent verified. Preparing its local authoring workspace...

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

The access token supplies the tenant identity during initial inspection; do not infer it from the environment ID.

The command validates the exact agent identity and direct Dev route, fetches the authoritative component change set, confirms its component identity and schema, converts supported authoring components with the Microsoft Object Model serializer, and materializes the local workspace. It does not require published Dev configuration; publishing is outside foundation setup and is not attachment remediation. It persists canonical setup progress for that agent before materialization when identity is complete. Complete the native FlightCheck maintenance below before treating the agent's `connect_ready: true` as current.

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

If the maker provides an environment URL without an agent ID, list visible Dev-realm candidates:

```text
python scripts/setup_existing_da.py list-agents \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}"
```

When candidates are returned, show their display names and ask the maker to choose one. For an identity returned by this native list, run the parent's selected-agent product-line reconciliation with `--native-da-ga` before validation or attachment. Validate only the selected candidate through `validate-agent` or `attach`.

When the list is empty, say:

> No visible editable Dev agents were listed in this environment. A directly addressable agent may still be available.

Present **Retry setup with another target** from `da-environment-target.md`, including its **Use an agent URL** choice. For an exact agent selected through that URL, run the full selected-agent product-line reconciliation without `--native-da-ga` before validating it directly.

## Maintain native FlightCheck evidence

After every successful `attach` or unchanged existing-workspace resume, run the three setup-readiness FlightChecks and the broad connection diagnostic for the exact agent. Attempt every check whose prerequisites remain available and present all four together.

Run each checkpoint into its dedicated local evidence folder:

```text
python scripts/flightcheck/cli.py --checkpoint DA-AGENT-001 --quiet-auth --no-open --output .local/setup/agents/{AGENT_ID}/flightcheck/DA-AGENT-001
python scripts/flightcheck/cli.py --checkpoint ENV-CAPACITY-001 --quiet-auth --no-open --output .local/setup/agents/{AGENT_ID}/flightcheck/ENV-CAPACITY-001
python scripts/flightcheck/cli.py --checkpoint "DA-CONN-*" --quiet-auth --no-open --output .local/setup/agents/{AGENT_ID}/flightcheck/DA-CONN
python scripts/flightcheck/cli.py --checkpoint DA-CONTENT-001 --quiet-auth --no-open --output .local/setup/agents/{AGENT_ID}/flightcheck/DA-CONTENT-001
```

After each setup-readiness run, even when that FlightCheck exits nonzero, apply its result to canonical setup state. Apply agent access and content directly:

```text
python scripts/setup_existing_da.py maintain-flightcheck --agent-id "{AGENT_ID}" --checkpoint DA-AGENT-001 --results .local/setup/agents/{AGENT_ID}/flightcheck/DA-AGENT-001/results.json
python scripts/setup_existing_da.py maintain-flightcheck --agent-id "{AGENT_ID}" --checkpoint DA-CONTENT-001 --results .local/setup/agents/{AGENT_ID}/flightcheck/DA-CONTENT-001/results.json
```

Inspect the exact `ENV-CAPACITY-001` row before applying it. Apply `Passed` or `Failed` normally. When its status is `Manual`, present this guidance and confirmation before applying the result:

**Message:**

### Capacity follow-up

We weren’t able to automatically verify capacity for this environment. Your agent and local authoring workspace are already available.

#### Copilot Studio message capacity

1. Open [Power Platform Admin Center]({POWER_PLATFORM_ADMIN_ORIGIN}/billing/licenses/copilotStudio/overview).
2. In the left navigation, select **Licensing**.
3. Under **Products**, select **Copilot Studio**.
4. Select **Manage Copilot Credits**.
5. Find **{friendly environment name or selected Power Platform environment}**.
6. Confirm that the environment has more than zero allocated Copilot Credits. If it does not, allocate credits and save the change.

**End message.**

Then ask exactly:

**After checking Power Platform Admin Center, is Copilot Studio message capacity allocated to this environment?**

Offer exactly:

- **Yes — capacity is allocated**
- **Not yet**

For **Yes — capacity is allocated**, apply the same current evidence with explicit attestation:

```text
python scripts/setup_existing_da.py maintain-flightcheck --agent-id "{AGENT_ID}" --checkpoint ENV-CAPACITY-001 --results .local/setup/agents/{AGENT_ID}/flightcheck/ENV-CAPACITY-001/results.json --manual-attested
```

For **Not yet**, apply the result without `--manual-attested`. Leave capacity blocked, preserve the manual verification guidance, and return control to the maker.

Resolve `{POWER_PLATFORM_ADMIN_ORIGIN}` from the selected service ring: `prod` is `https://admin.powerplatform.microsoft.com`, `preprod` is `https://admin.preprod.powerplatform.microsoft.com`, and `test` is `https://admin.test.powerplatform.microsoft.com`. Do not send a maker from a non-production setup ring to the production admin center.

When canonical `SETUP-05` contains a registry-declared `requirement`, also apply the broad connection result:

```text
python scripts/setup_existing_da.py maintain-flightcheck --agent-id "{AGENT_ID}" --checkpoint "DA-CONN-*" --results .local/setup/agents/{AGENT_ID}/flightcheck/DA-CONN/results.json
```

Parse every `DA_SETUP_FLIGHTCHECK_JSON:` result. Its `state`, `connectReady`, `activeStep`, and `failureCauses` are the setup-readiness verdict. Use the three maintained checks and the exact Self-Help diagnostic projection below for maker-facing evidence and remediation. After attachment, attempt every available check before producing the final runtime-readiness table. When maker action is required or an operation prevents later checks from running, state the observed blocker and supported recovery. Do not use a FlightCheck result to roll back a completed maker-facing checklist stage.

Read `src/reference/da-product-setup-registry.json` as the authoritative product requirement registry. Attachment resolves the product only by an exact registered catalog display name or agent schema name and records the declared requirement on `SETUP-05`. Do not infer requiredness from a partial name, persona wording, or the logical references returned by FlightCheck.

`DA-CONN-*` remains broad diagnostic evidence. Preserve its complete result locally, but do not use its aggregate summary row for setup UX or canonical state. When `SETUP-05` declares a requirement, inspect only the individual row whose description identifies that exact `connectorApiName`; the current registry maps the IT product to `shared_alchemy`, displayed as **Microsoft 365 Self-Help**. Do not project `shared_service-now` or another undeclared reference into the table, remediation, Overall status, or completion choices.

For the exact registry-required row:

- `Passed` is **✅ Ready**.
- `Warning` is **⚠️ Ready with limitation** and retains its warning disclaimer.
- `NotConfigured` or `Failed` is **⛔ Action required**.
- `Error` is **⚠️ Check unavailable** and retains the observed authentication, permission, or service evidence.
- A completed diagnostic without the required exact row is **⛔ Action required** because the required connection could not be verified.

When the registry declares no connection requirement for the resolved product, or the agent does not exactly match a registered product, keep `SETUP-05` skipped and render Connections as **➖ Not required**. A required connection does not prevent creation, attachment, or workspace materialization, but it does keep canonical `connectReady` false until its exact post-attachment evidence is ready.

`ENV-CAPACITY-001` uses the Licensing API when available. `Passed` is **✅ Ready** and `Failed` is **⛔ Action required**. `Manual` is **⛔ Manual confirmation required** until the maker explicitly confirms the allocation; an accepted `--manual-attested` result is **✅ Ready — manually confirmed**. Manual confirmation is allowed only for an unreadable allocation and never overrides a known zero allocation or another failed result. Non-queryable governance prerequisites are outside this check; disclose that limitation without treating it as a setup policy or a downstream `/connect` deferral.

## Interpret results

Canonical setup state is authoritative for each agent's setup progress and readiness. Local workspace materialization is complete when attachment reports `connectionStatus: workspace-ready`, canonical workspace evidence is present, and `SETUP-07` is `done`. Runtime readiness is complete only when every step in that agent's canonical record is `done` and the final `DA_SETUP_FLIGHTCHECK_JSON:` reports `connectReady: true`.

Canonical state records native environment access, capacity, the registry-declared product connection requirement, and baseline content readiness. Preferred-solution configuration remains skipped because it does not apply to the DA-only foundation path. Undeclared product and integration references remain diagnostic and do not alter canonical completion.

Before materialization completes, render an incomplete `SETUP-03` as **Establish an editable Dev agent** and an incomplete `SETUP-07` as **Materialize the local workspace**. After materialization completes, render blocked capacity or content steps and the Self-Help diagnostic only in the runtime-readiness table. Explain each unmet prerequisite in maker language and offer the bounded remediation supported by that evidence.

If content was synced to the local workspace but the returned result is not workspace-ready and supplies no specific failure cause, keep **Materialize the local workspace** current and show:

> The agent content was synced to your local workspace, but the workspace is not ready to connect. Setup is not complete and has stopped.

Do not invent a cause or run another operation without new maker intent.

After successful materialization and after the three setup-readiness checks and broad connection diagnostic have been attempted, build the agent link from `DA_EXISTING_DEV_SETUP_JSON:` and build the runtime-readiness table from the applied FlightCheck results and canonical state. Render both even when `connectReady` is false.

Infer a concise user-friendly product name from the authoritative product or agent display name when its meaning is unambiguous. For example, render `Employee Self-Service IT` as `Employee Self-Service (IT)` and `Employee Self-Service HR` as `Employee Self-Service (HR)`. If a friendly form is not clear, use the authoritative backend display name unchanged. Never use a schema name or agent ID as link text.

Build the exact agent URL as `{COPILOT_STUDIO_ORIGIN}/environments/{ENVIRONMENT_ID}/bots/{AGENT_ID}/overview`, using the validated Copilot Studio origin for the selected service ring and the exact environment and agent IDs from setup evidence. Never link to the environment's agent-list page.

**Message:**

Your local workspace is ready for authoring. The remote agent is available at [{USER_FRIENDLY_PRODUCT_NAME}]({ACTUAL_AGENT_URL}) in Microsoft Copilot Studio.

### Runtime readiness

| Check                | Status                          | Details                                  |
| -------------------- | ------------------------------- | ---------------------------------------- |
| Agent access         | {agent access status}           | {agent access evidence summary}          |
| Environment capacity | {environment capacity status}   | {environment capacity evidence summary}  |
| Connections          | {connections status}            | {connections evidence summary}           |
| Agent content        | {agent content status}          | {agent content evidence summary}         |
| **Overall**          | **{overall readiness status}**  | **{maker-facing readiness summary}**     |

**End message.**

Use the same five rows and order in every runtime-readiness table. Map the three setup-readiness checks directly from their evidence: `Passed` is **✅ Ready**, an actionable failure is **⛔ Action required**, an unavailable check is **⚠️ Check unavailable**, and a check without current evidence is **⬜ Not checked**. Build the Connections row only from the registry-declared requirement and its exact diagnostic row.

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

Resolve `{POWER_APPS_ORIGIN}` from the selected service ring: `prod` is `https://make.powerapps.com`, `preprod` is `https://make.preprod.powerapps.com`, and `test` is `https://make.test.powerapps.com`. Do not send a maker from a non-production setup ring to the production maker portal.

Do not append this section for a ready, warning, or unavailable required result, or when the registry declares no requirement. Do not add another completion choice. A later request to check the connection reruns the broad diagnostic and reapplies its exact required row to `SETUP-05`.

This report is a factual handoff, not another readiness gate. If the maker disputes a fact, inspect the underlying operation evidence rather than changing canonical state conversationally. Then present the shared completion choices from `SKILL.md`.

Preserve service status, error code, request ID, and local projection-failure evidence for diagnosis. In ordinary maker-facing copy, explain the specific service or conversion failure in plain language without exposing raw technical output. Do not replace it with a generic setup error.

For an identity or authorization failure, rerun the same operation with `--select-account`. Use `--tenant-id` only when the maker supplies the tenant that owns the target and understands that tenant selection does not grant access.

## Refresh changed content

An unchanged rerun verifies the remote snapshot without overwriting local files.

If the remote snapshot changed, or the existing workspace uses an older projection, ask:

> The local workspace differs from the current agent snapshot. Refresh will create a checkpoint and replace the managed agent files; it will not merge them.

Offer exactly:

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
