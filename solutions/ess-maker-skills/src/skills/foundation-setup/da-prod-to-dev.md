<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Set Up Dev from a Known Prod Agent

Use this experimental path only when the maker supplies a known source Prod
Copilot Studio agent URL and a target Dev environment URL. It is a same-tenant,
create-only happy path. Read `src/reference/native-alm-import.md` for the import
contract and reuse `da-existing-dev.md` for attachment and completion handling.
Do not generate HTTP code or an end-to-end setup script.

## Inspect the source

Tell the maker that Microsoft sign-in may open, using the authorization message
from `SKILL.md`. Run:

```text
python scripts/setup_alm_export.py inspect \
  --source-url "{SOURCE_PROD_AGENT_URL}"
```

Parse `DA_ALM_EXPORT_INSPECTION_JSON:`. The command must validate native Prod
realm `2`; do not infer Prod from names, URLs, or environment metadata.

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

Use the related Dev only when validation succeeds and
`DA_AGENT_VALIDATION_JSON:` returns the same `almFamilyId` as the Prod
inspection. Attach it with the same internal context and
`--setup-source prod-to-dev`, then complete setup through
`da-existing-dev.md`.

## Export and create Dev

When there is no directly validated related Dev, run:

```text
python scripts/setup_alm_export.py export \
  --source-url "{SOURCE_PROD_AGENT_URL}" \
  --tenant-id "{SOURCE_TENANT_ID}"
```

Parse `DA_ALM_EXPORT_JSON:` and pass its temporary `packagePath` to the durable
create-only import command:

```text
python scripts/setup_alm_import.py \
  --target-url "{TARGET_DEV_ENVIRONMENT_URL}" \
  --tenant-id "{SOURCE_TENANT_ID}" \
  --package "{TEMPORARY_PACKAGE_PATH}"
```

Do not pass replacement or retry arguments. Immediately delete the temporary
ZIP after the import command returns, before handling its result. Parse
`DA_ALM_IMPORT_JSON:` even when import exits nonzero. For any result other than
`kind: success`, stop and use the outcome guidance in
`src/reference/native-alm-import.md`; do not retry, recover a collision, or
replace an agent.

On success, attach the returned identity:

```text
python scripts/setup_existing_da.py attach \
  --environment-id "{ENVIRONMENT_ID}" \
  --tenant-id "{TENANT_ID}" \
  --host "{VALIDATED_HOST}" \
  --ring "{RING}" \
  --api-version "{API_VERSION}" \
  --agent-id "{RETURNED_AGENT_ID}" \
  --setup-source prod-to-dev
```

Complete setup through `da-existing-dev.md`. Do not claim Prod changed, Dev was
published, or promotion was configured. Do not add cross-tenant support,
replacement, collision recovery, export receipts, or telemetry.
