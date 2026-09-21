<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Set Up Dev from an Entitled MOS Product

Use this path when the maker wants to install an entitled product. Read `src/reference/mos-starter-package.md` before acting. The reference owns the service facts, safety invariants, request-evidence disposition matrix, and response-evidence contract. This skill owns the maker conversation and the handoff into existing-Dev setup.

Use only intent supplied in the current request and results observed in this invocation. Do not infer persona, product, target, or progress from conversation history.

## Identify the target

Ask for an environment URL when the target is not supplied. Infer its
environment ID and service ring. The URL should have a segment denoting the
ring, such as `test` or `preprod`; when neither segment is present, confirm the
`prod` ring with the user. Ask only when the environment ID is unclear. Retain
the resolved environment ID and ring for every operation in this setup
invocation. Do not ask the maker to classify the product before loading the
catalog. When fresh-agent intent and the target environment are known, mark
**Choose the starting point and target environment** complete.

## Use the workspace environment

Read canonical setup state and `.local/config.json` when present. Continue in an occupied workspace when its recorded environment is the selected target. If it records a different environment, follow **Create and open a new workspace** in `SKILL.md` and stop this invocation after that handoff. Do not reset a same-environment workspace merely to install another product.

## List the catalog

Complete the shared account-selection and authorization steps in `SKILL.md`, then run:

```text
python scripts/setup_mos_starter.py list \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}"
```

Parse `DA_MOS_STARTER_PACKAGES_JSON:`. Preserve every service row as operation evidence. Group rows by exact `packageId` and present one picker option per exact ID, using the service-provided name, version, and description as authoritative inputs. Never show the internal `packageId` to the maker. Do not describe products as remaining, uninstalled, or eligible; the create response is the service-owned decision for the selected package.

For each picker row, infer a concise user-friendly product name only when the service-provided name or description makes the meaning unambiguous. For example, render `Employee Self-Service IT` as `Employee Self-Service (IT)` and render `Employee Self-Service HR` as `Employee Self-Service (HR)`. If a friendly form is not clear, use the exact service-provided product name unchanged. This display-only inference must not change the underlying `packageId`, backend name, or create request.

Use the host's interactive single-selection control and offer one choice for each exact `packageId`. Do not ask the maker to type a product name. Format each choice as **{friendly product name} {version}** and use `shortDescription`, then `description`, as its supporting text. Omit a blank version or description instead of showing an unresolved value. Retain the selected friendly product name for the final exact-agent link.

The successful list proves target access, but not a new agent identity. Keep **Verify access and agent identity** current until create and direct attachment validation succeed.

If the catalog is empty, mark the maker's product choices unavailable, say that no entitled products are currently available, and stop; do not guess a substitute or fall back to another setup path.

If `catalogWarnings` is non-empty, tell the maker the product listing was incomplete -- some entries could not be read -- without repeating the warning detail itself. A row reported in `catalogWarnings` is never selectable; only offer products backed by rows from the `packages` array.

If the command instead fails, parse `DA_MOS_STARTER_LIST_ANNOTATIONS_JSON:` and the response body (`DA_MOS_STARTER_LIST_RESPONSE_JSON:` or `..._RESPONSE_TEXT:`) the same way `create`'s response is interpreted below. Preserve the detailed evidence internally, but tell the maker only that entitled products could not be loaded, nothing was changed, and setup has stopped.

## Confirm the exact product and target

After the maker selects one product from the interactive list, confirm the target Power Platform environment. Do not preselect a choice. Once confirmed, keep the product's underlying `packageId`, `name`, and `version` for the next step; these are internal command inputs, not maker-facing text.

Substitute the selected picker label and show:

> Create a new ESS agent in **{friendly environment name or Selected Power Platform environment}** from **{selected product label}**?

Offer exactly:

- **Create agent**
- **Choose a different product**
- **Cancel setup**

Do not preselect **Create agent**. Run create only after the maker explicitly selects **Create agent** for the displayed product and target.

## Create

Only after the maker selects **Create agent**, run:

```text
python scripts/setup_mos_starter.py create \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}" \
  --package-id "{CONFIRMED_PACKAGE_ID}" \
  --package-name "{CONFIRMED_PACKAGE_NAME}" \
  --package-version "{CONFIRMED_PACKAGE_VERSION}" \
  --client-request-id "{NEW_CLIENT_REQUEST_UUID}"
```

Generate a new UUID only after this confirmation and retain it as the identity of this create request. Wait for the command to finish and interpret its returned evidence before taking further action. Do not invoke create concurrently or automatically. Reusing the same request UUID means the same mutation and must not dispatch another POST.

## Interpret the response

Parse `DA_MOS_STARTER_CREATE_ANNOTATIONS_JSON:`, then the response body (`DA_MOS_STARTER_CREATE_RESPONSE_JSON:` or `..._RESPONSE_TEXT:`), then `DA_MOS_STARTER_CREATE_JSON:` when the command exits zero. Keep the response body as diagnostic evidence.

The response, outcome label, fuse disposition, HTTP status, and request details are diagnostic evidence only. Do not render them as ordinary maker-facing copy. For a definitive non-success, give a plain-language reason only when the service evidence supports it; otherwise say that the service did not create a new agent and setup has stopped. For an uncertain result, say:

> I cannot confirm whether the agent was created because communication ended before a definitive result was received. Setup has stopped.

When the annotations report `outcome: created`, keep the distinction between `catalogPackageVersion` and `templateVersion` in diagnostic evidence; do not explain those internal version concepts to the maker. Say that the new agent was created and setup is not complete.

When the annotations report `outcome: collision`, do not infer which visible agent corresponds to the package. List visible Dev agents in the same environment through `setup_existing_da.py list-agents`, then offer exactly:

- **Choose an existing agent in this environment**
- **Choose a different catalog product**
- **Go back**
- **Cancel setup**

Do not preselect a choice. For **Choose an existing agent in this environment**, show the returned names, let the maker select one exact agent, and continue through `da-existing-dev.md`. The selected agent is maker-supplied intent, not proof of package identity. This path does not replace an agent.

## Enable ALM

After a successful create, say:

> The agent was created. Preparing its local authoring workspace...

Then run:

```text
python scripts/setup_mos_starter.py enable-alm \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}" \
  --agent-id "{RETURNED_AGENT_ID}"
```

Parse `DA_MOS_STARTER_ALM_ANNOTATIONS_JSON:` and its response body when present, then `DA_MOS_STARTER_ALM_JSON:` on success. A failed read-back may instead emit `DA_MOS_STARTER_ALM_VERIFY_ANNOTATIONS_JSON:`, its response body, or `DA_MOS_STARTER_ALM_VERIFY_JSON:`. Continue only for `outcome: enabled` or `outcome: already-enabled` with `persistedValue: true`. If read-back definitively reports `outcome: verification-failed` and `persistedValue: false`, say, "The follow-up check showed that the agent was not prepared for local editing. Setup has stopped without attaching a workspace." If transport or read-back becomes uncertain, preserve the evidence internally, say that the agent could not be confirmed ready for local editing, and stop.

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

This attachment validates the returned agent through its direct Dev route and component identity; it does not require published Dev configuration. On failure, preserve the command's specific `ERROR:` text and any canonical `active_step` and `failure_causes` as diagnostic evidence. Translate them into the visible setup stage and a plain explanation of the unmet prerequisite as described in `da-existing-dev.md`; never show internal step IDs or raw technical output as ordinary maker copy. Publishing is outside foundation setup and is not remediation for an attachment failure. On success, parse `DA_EXISTING_DEV_SETUP_JSON:`. When attachment reports `connectionStatus: workspace-ready`, run the agent-scoped native FlightCheck maintenance sequence in `da-existing-dev.md`. Treat setup as complete only when its final `DA_SETUP_FLIGHTCHECK_JSON:` reports `connectReady: true`. If a FlightCheck blocks setup, translate its evidence according to `da-existing-dev.md`. The request-scoped create evidence intentionally remains as an audit note. Do not publish, remove, or replace components from this path.

After direct attachment validation succeeds, mark **Verify access and agent identity** and **Establish an editable Dev agent** complete. After all four FlightChecks have been attempted, render the factual workspace and runtime-readiness report from `da-existing-dev.md` using **New entitled MOS product** as the starting point, including when `connectReady` is false.

For every non-created outcome (`pre-dispatch-failure`, `collision`, `rejected`, `malformed-success`, `source-package-mismatch`, or an uncertain response or transport failure), end the create operation. The existing read-only `list` and `setup_existing_da.py validate-agent`/`list-agents` commands remain available for a separately requested inspection.

## Hybrid follow-up

After attachment completes, if the selected product explicitly identifies a hybrid ISV such as Workday or ServiceNow, recommend running `/connect` afterward to wire that product's connection. Never invoke `/connect`, install a connector, or configure Dataverse, publishing, promotion, or telemetry from this skill yourself.
