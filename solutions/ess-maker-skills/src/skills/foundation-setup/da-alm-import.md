<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Set Up Dev from a Supplied Agent Package

This is an advanced handoff for a maker who has already supplied a native agent
package or explicitly asked to use one. Do not advertise package import as a
primary `/setup` choice.

Read `src/reference/native-alm-import.md` before acting. The reference owns the
service facts, safety boundaries, outcome meanings, and unresolved limitations.
This skill owns the maker interaction and the handoff into existing-Dev setup.

## Identify the target

Ask for a Copilot Studio environment URL if the maker has not supplied one. A
recognized Copilot Studio URL is preferred because it identifies both the
environment and service ring. Do not ask the maker to choose a ring or tenant.

Do not inspect, extract, rewrite, or summarize package content yourself. The
durable import command observes only the bounded metadata needed for safety.

## Preflight and create

The import command validates local projection dependencies before
authentication or remote mutation. If preflight fails, follow the reported
setup prerequisite and rerun only after it is resolved.

Tell the maker that Microsoft sign-in may open, using the exact authorization
message from the parent skill. Run:

```text
python scripts/setup_alm_import.py \
  --target-url "{POWER_PLATFORM_ENVIRONMENT_URL}" \
  --package "{NATIVE_AGENT_PACKAGE_PATH}"
```

The first operation must omit both replacement arguments. Never infer
replacement permission from the package, collision, environment, schema, or a
different setup context.

Parse `DA_ALM_IMPORT_JSON:` even when the command exits nonzero.

## Complete workspace setup

When `kind` is `success`, use the returned environment, tenant, host, ring, API
version, and agent identity only as internal command inputs. Do not display
those identifiers. Run:

```text
python scripts/setup_existing_da.py attach \
  --environment-id "{ENVIRONMENT_ID}" \
  --tenant-id "{TENANT_ID}" \
  --host "{VALIDATED_HOST}" \
  --ring "{RING}" \
  --api-version "{API_VERSION}" \
  --agent-id "{RETURNED_AGENT_ID}" \
  --setup-source alm-import
```

Parse `DA_EXISTING_DEV_SETUP_JSON:`. Treat import `kind: success` only as
permission to begin attachment. Treat setup as complete only when attachment
reports `connectionStatus` as `workspace-ready` and `connectReady: true`.

If attachment reports that the managed workspace changed, use the explicit
checkpoint-and-refresh choice from `da-existing-dev.md`. A refresh never
repeats the import.

When complete, show:

**{agent display name}** is set up as the editable Dev agent. Its available
topics are in your local workspace and ready for customization.

If the result reports nonempty `unprojectedComponentKinds`, add:

Some agent content was retained safely in the fetched snapshot but is not
editable through this ADK version yet.

Do not claim publication, deployment, promotion, or optional integration
configuration.

## Handle a collision

When `kind` is `conflict`, explain:

An editable agent created from this package already exists in the target
environment. I did not replace it.

Offer to use the existing agent through `da-existing-dev.md`. Offer replacement
only when the maker explicitly needs the supplied package to overwrite that
agent.

Before replacement, directly validate the exact existing Dev agent using its
Copilot Studio URL or known agent ID without attaching it or writing setup
state:

```text
python scripts/setup_existing_da.py validate-agent \
  --target-url "{COPILOT_STUDIO_AGENT_URL}"
```

Parse `DA_AGENT_VALIDATION_JSON:`. Show its display name, then ask:

Replacing **{agent display name}** will overwrite its current editable content
with the supplied package. Continue?

When presenting structured choices, default to **Use existing agent** or
**Cancel setup**. Never preselect or recommend **Continue replacement**.
Continue only after the maker explicitly selects replacement. Pass the same
validated internal ID in both confirmation arguments:

```text
python scripts/setup_alm_import.py \
  --target-url "{POWER_PLATFORM_ENVIRONMENT_URL}" \
  --package "{NATIVE_AGENT_PACKAGE_PATH}" \
  --replace-agent-id "{INTERNAL_AGENT_ID}" \
  --confirm-replace-agent-id "{INTERNAL_AGENT_ID}"
```

After a successful replacement, complete workspace setup through the existing
attach command above. If local files differ, obtain separate approval before
checkpointing and refreshing them.

## Handle other outcomes

- `pre-dispatch-failure`: no request reached the service. Explain the local,
  DNS, or connection prerequisite. Do not retry automatically.
- `rejected`: the service returned a normal error response. Explain the
  actionable error without exposing diagnostics. Do not retry automatically.
- `invalid-success` or `ambiguous`: the mutation may have completed, but no
  usable identity is available. Do not retry. Follow the manual reconciliation
  procedure in `src/reference/native-alm-import.md`.

If the command exits during direct verification after recording status
`imported`, the mutation already returned an identity. Do not start another
import. Resolve the reported verification prerequisite, then rerun the
identical command. Receipt replay resumes verification without another POST.
If verification still fails, stop and retain the receipt.

The command caches every operation outcome. Repeating the same command returns
the cached result without another POST. After the cause of a recorded
`pre-dispatch-failure` or `rejected` outcome is resolved, another request
requires explicit maker approval and `--retry-safe-failure`.

Never remove or edit import records merely to permit another mutation.
