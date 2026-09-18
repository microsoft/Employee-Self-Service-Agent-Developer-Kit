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

When both the package and target environment are known, mark **Choose the
starting point and target environment** complete. Keep **Verify access and agent
identity** current until the import operation returns a directly validated Dev
identity.

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
those identifiers. Mark **Verify access and agent identity** and **Establish an
editable Dev agent** complete, then show:

> Agent package imported and verified as an editable Dev agent. Preparing its
> local authoring workspace...

Run:

```text
python scripts/setup_existing_da.py attach \
  --environment-id "{ENVIRONMENT_ID}" \
  --tenant-id "{TENANT_ID}" \
  --host "{VALIDATED_HOST}" \
  --ring "{RING}" \
  --api-version "{API_VERSION}" \
  --agent-id "{RETURNED_AGENT_ID}" \
  --expected-schema-name "{RETURNED_SCHEMA_NAME}" \
  --setup-source alm-import
```

Parse `DA_EXISTING_DEV_SETUP_JSON:`. Treat import `kind: success` only as
permission to begin attachment. When attachment reports `connectionStatus` as
`workspace-ready`, show:

> The imported Dev agent is now available in the local authoring workspace. I
> materialized {TOPIC_COUNT} topics and {VARIABLE_COUNT} variables. Publishing
> was not required to prepare the workspace. Next I'll validate its setup.

Run the native FlightCheck maintenance sequence in `da-existing-dev.md`. Treat
setup as complete only when its final
`DA_SETUP_FLIGHTCHECK_JSON:` reports `connectReady: true`.

If attachment reports that the managed workspace changed, use the explicit
checkpoint-and-refresh choice from `da-existing-dev.md`. A refresh never
repeats the import.

If attachment fails after import `kind: success`, state:
**The agent package was imported and verified in Dev, but its local workspace
was not prepared. No new import is needed.** Show the attachment error and
rerun only the attach command after resolving it.

When complete, render the factual completion report from `da-existing-dev.md`
using **Supplied native agent package** as the starting point. Build every other
field from `DA_EXISTING_DEV_SETUP_JSON:` and retain its limits on completion
claims.

## Handle a collision

When `kind` is `conflict`, mark **Establish an editable Dev agent** blocked and
show:

> An editable agent created from this package already exists in the target
> environment. I did not replace it.

Offer exactly:

- **Use existing agent** — continue through `da-existing-dev.md`.
- **Replace existing agent with this package** — validate the exact agent and
  request separate replacement approval.
- **Cancel setup**

Default to **Use existing agent**. Do not recommend replacement.

Before replacement, directly validate the exact existing Dev agent using its
Copilot Studio URL or known agent ID without attaching it or writing setup
state:

```text
python scripts/setup_existing_da.py validate-agent \
  --target-url "{COPILOT_STUDIO_AGENT_URL}"
```

Parse `DA_AGENT_VALIDATION_JSON:`. Show its display name, then ask:

> Replacing **{agent display name}** will overwrite its current editable
> content with the supplied package. Continue?

Offer exactly:

- **Continue replacement**
- **Use existing agent**
- **Cancel setup**

Never preselect or recommend **Continue replacement**. Continue only after the
maker explicitly selects it. Pass the same validated internal ID in both
confirmation arguments:

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

- `imported-unverified`: the import request completed and returned the persisted
  agent identity, while direct agent or Dev-realm verification did not finish.
  State clearly:
  **The agent package was imported, but verification is not available yet, so
  I have not prepared its local workspace.**
  Preserve the reported verification status, error code, and request ID when
  available. Do not infer that publication is required. Resolve the reported
  access or service prerequisite, then rerun the identical command; receipt
  replay resumes verification without another import POST.
- `pre-dispatch-failure`: no request reached the service. Explain the local,
  DNS, or connection prerequisite. State that no remote import was observed. Do
  not retry automatically.
- `rejected`: the service returned a normal error response. Explain the
  actionable error and preserve its status, error code, and request ID when
  available. Do not retry automatically.
- `invalid-success` or `ambiguous`: the mutation may have completed, but no
  usable identity is available. Show: **The import outcome could not be proven.
  I stopped to avoid creating or replacing the agent twice.** Do not retry.
  Follow the manual reconciliation procedure in
  `src/reference/native-alm-import.md`.

If an older command exits during direct verification after recording status
`imported`, treat it as the same completed-import state. Rerun the identical
command with the updated tooling. Receipt replay verifies the direct agent and
Dev route without another POST. If verification still fails, stop and retain
the receipt.

The command caches every operation outcome. Repeating the same command returns
the cached result without another POST. After the cause of a recorded
`pre-dispatch-failure` or `rejected` outcome is resolved, another request
requires explicit maker approval. Ask:

> The reported prerequisite has been resolved. Start a new import request?

Offer exactly:

- **Retry import**
- **Stop without retrying**

Use `--retry-safe-failure` only after the maker selects **Retry import**.

Never remove or edit import records merely to permit another mutation.
