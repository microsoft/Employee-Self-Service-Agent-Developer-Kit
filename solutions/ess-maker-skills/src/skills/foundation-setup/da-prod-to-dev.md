<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Set Up Dev from a Known Prod Agent

Use this setup path when server-backed inspection identifies the maker's
Copilot Studio agent URL as Prod. It is a same-tenant, create-only path. Read
`src/reference/native-alm-import.md` for the import contract and reuse
`da-existing-dev.md` for attachment and completion handling. Do not generate
HTTP code or an end-to-end setup script.

## Resume from durable evidence

Use only canonical setup state and durable operation records read in this invocation. Do not infer an interrupted step from conversation history.

When canonical setup state shows that attachment started, use its persisted identity and the resume rules in `da-existing-dev.md`; do not inspect, export, or import again.

When a matching import record reports `kind: success`, or reports that the service accepted the package but direct Dev verification did not finish, use a fresh [source inspection](#inspect-the-source) to obtain its current ALM-family identity. Rerun the import command with the same target, tenant, and recorded temporary package path:

```text
python scripts/setup_alm_import.py \
  --environment-id "{TARGET_ENVIRONMENT_ID}" \
  --ring "{TARGET_RING}" \
  --tenant-id "{SOURCE_TENANT_ID}" \
  --package "{FORMER_TEMPORARY_PACKAGE_PATH}" \
  --resume-create-after-cleanup \
  --expected-alm-family-id "{SOURCE_ALM_FAMILY_ID}"
```

The package must already be removed. The matching import receipt for the exact
target and family must finish direct verification or return its verified result
with `importStatus: resumed`, without another export or import request. Do not
use this flag for a normal import. Immediately run:

```text
python scripts/setup_alm_export.py cleanup
```

Then attach the cached verified result through [Attach and complete](#attach-and-complete).
If no matching create receipt exists, stop rather than exporting again.

## Inspect the source

Tell the maker that Microsoft sign-in may open, using the authorization message
from `SKILL.md`. Run:

```text
python scripts/setup_alm_export.py inspect \
  --environment-id "{SOURCE_ENVIRONMENT_ID}" \
  --agent-id "{SOURCE_AGENT_ID}" \
  --ring "{SOURCE_RING}"
```

Parse `DA_ALM_EXPORT_INSPECTION_JSON:`. The command must validate native Prod
realm `2`; do not infer Prod from names, URLs, or environment metadata.

After successful inspection, mark **Verify access and agent identity** complete and show:

> Prod agent verified. Checking for its related editable Dev agent...

If `relatedDevAgentId` is present, validate that exact agent using the returned
environment, tenant, host, ring, and API version:

```text
python scripts/setup_existing_da.py validate-agent \
  --environment-id "{SOURCE_ENVIRONMENT_ID}" \
  --tenant-id "{SOURCE_TENANT_ID}" \
  --host "{SOURCE_VALIDATED_HOST}" \
  --ring "{SOURCE_RING}" \
  --api-version "{SOURCE_API_VERSION}" \
  --agent-id "{RELATED_DEV_AGENT_ID}"
```

Use the related Dev only when validation succeeds and `DA_AGENT_VALIDATION_JSON:` returns the same `almFamilyId` as the Prod inspection. Mark **Establish an editable Dev agent** complete, then show:

> Found the related editable Dev agent: **{agent display name}**. Preparing its
> local authoring workspace...

Continue through [Attach and complete](#attach-and-complete) with that identity. Do not offer to create a duplicate Dev agent when a related Dev already exists.

## Export and create Dev

Continue here only when no directly validated related Dev exists. Keep **Establish an editable Dev agent** current and show:

> No related editable Dev agent was found. Setup can create one from the
> verified Prod agent without changing Prod.

Use the same Power Platform environment as the supplied Prod agent. If the maker explicitly requests another environment, ask for its environment URL and infer its environment ID and service ring. The URL should have a segment denoting the ring, such as `test` or `preprod`; when neither segment is present, confirm the `prod` ring with the user. Ask only when the environment ID is unclear. Then run:

```text
python scripts/setup_alm_export.py export \
  --environment-id "{SOURCE_ENVIRONMENT_ID}" \
  --agent-id "{SOURCE_AGENT_ID}" \
  --tenant-id "{SOURCE_TENANT_ID}" \
  --ring "{SOURCE_RING}"
```

If the maker cancels after export, run `setup_alm_export.py cleanup`. A later
fresh inspect or export also removes a recorded package left by an interrupted
run before continuing.

Parse `DA_ALM_EXPORT_JSON:` and pass its temporary `packagePath` to the durable
create-only import command:

Immediately before import, ask:

> Create a new editable Dev agent in the same Power Platform environment as
> the supplied Prod agent?

Offer exactly:

- **Create editable Dev agent**
- **Cancel setup**

Do not preselect **Create editable Dev agent**. Continue only after the maker selects it.

When the maker explicitly selected another environment, use its friendly display name when an authoritative operation returned one in this invocation. Otherwise say "the selected Power Platform environment" without showing internal IDs or URLs. Run no other operation between the maker's confirmation and the create-only import:

```text
python scripts/setup_alm_import.py \
  --environment-id "{TARGET_ENVIRONMENT_ID}" \
  --ring "{TARGET_RING}" \
  --tenant-id "{SOURCE_TENANT_ID}" \
  --package "{TEMPORARY_PACKAGE_PATH}" \
  --expected-alm-family-id "{SOURCE_ALM_FAMILY_ID}"
```

Do not pass replacement or retry arguments. Capture `DA_ALM_IMPORT_JSON:` even
when import exits nonzero. Immediately after the import command returns, before
handling its result, run:

```text
python scripts/setup_alm_export.py cleanup
```

If cleanup fails, report the local cleanup error and stop; the durable import
result remains the primary operation evidence and can be resumed after cleanup
succeeds.

When import returns `kind: conflict`, rerun the read-only source inspection command above with the same source values to refresh `/realms`.

If the refreshed result contains a related Dev, validate that exact agent with
`setup_existing_da.py validate-agent` as in [Inspect the source](#inspect-the-source).
Only when validation returns the same `almFamilyId` as the refreshed Prod
inspection, show:

> A related editable Dev agent now exists: **{agent display name}**. Use it for
> this workspace?

Offer exactly **Use related Dev agent** and **Cancel setup**, and offer to attach it through [Attach and complete](#attach-and-complete). Continue only when the maker selects **Use related Dev agent**. If no related Dev is returned or the family cannot be proven, stop with the safe conflict outcome from `src/reference/native-alm-import.md`. Do not recover a collision or offer replacement.

For any other result besides `kind: success`, stop and use the outcome guidance
in `src/reference/native-alm-import.md`; do not retry or replace an agent.

If source inspection or export is unavailable or unauthorized, report the
observed limitation and stop. A maker who already has the editable Dev agent
can restart `/setup` with that Dev agent's Copilot Studio URL; do not infer the
relationship from the failed Prod operation.

## Attach and complete

On a validated related-Dev path or successful import result, attach the returned
identity:

```text
python scripts/setup_existing_da.py attach \
  --environment-id "{ENVIRONMENT_ID}" \
  --tenant-id "{TENANT_ID}" \
  --host "{VALIDATED_HOST}" \
  --ring "{RING}" \
  --api-version "{API_VERSION}" \
  --agent-id "{RETURNED_AGENT_ID}" \
  --setup-source prod-to-dev \
  --expected-schema-name "{RETURNED_SCHEMA_NAME}"
```

The earlier source inspection and import or related-Dev validation own ALM-family proof. Attachment validates the returned Dev route and component schema without requiring published Dev configuration. When attachment reports `connectionStatus: workspace-ready`, run the native FlightCheck maintenance sequence in `da-existing-dev.md`. Complete runtime readiness only after its final `DA_SETUP_FLIGHTCHECK_JSON:` reports `connectReady: true`. After all four FlightChecks have been attempted, render the factual workspace and runtime-readiness report there, including when `connectReady` is false. Use **Existing Prod agent; related Dev reused** as the starting point for a validated related-Dev path and **Existing Prod agent; new Dev created** after a successful create-only import. Do not claim Prod changed, Dev was published, or promotion was configured. Do not add cross-tenant support, replacement, collision recovery, export receipts, or telemetry.
