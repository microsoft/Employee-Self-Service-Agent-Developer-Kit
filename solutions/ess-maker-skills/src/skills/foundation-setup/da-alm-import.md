<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Set Up Dev from a Supplied Agent Package

This is an advanced handoff for a maker who has already supplied a native agent
package or explicitly asked to use one. Do not advertise package import as a
primary `/setup` choice. Do not describe package classifications, schema names,
realm numbers, API routes, or setup-source values to the maker.

This path supports one Power Platform environment and one active platform per
ADK workspace. It creates an editable Dev agent by default. It replaces an
existing Dev agent only after the maker explicitly approves that exact target.

## Identify the target

Ask for the target Power Platform environment URL if the maker has not already
provided it. Apply the authentication and environment-selection guidance from
`src/skills/foundation-setup/da-existing-dev.md`. Do not ask the maker to select
a service ring or supply a tenant ID before authentication.

Do not inspect, extract, rewrite, or summarize package content yourself. The
guarded command reads only the required package metadata and lets the service
decide whether the package is compatible.

## Create the editable agent

Tell the maker to select the identity they use for the target Power Platform
environment if browser authentication appears. Run:

```text
python scripts/setup_alm_import.py \
  --target-url "{POWER_PLATFORM_ENVIRONMENT_URL}" \
  --package "{NATIVE_AGENT_PACKAGE_PATH}"
```

Omitting a replacement target is mandatory for the first attempt. Never infer
permission to replace an agent from the package, environment, or a prior setup
attempt.

Parse `DA_ALM_IMPORT_SETUP_JSON:`. Treat setup as complete only when the result
reports both `connectionStatus` as `workspace-ready` and `setupStatus` as
`complete`.

When complete, show:

**{agent display name}** is set up as the editable Dev agent. Its available
topics are in your local workspace and ready for customization.

If the result reports unprojected component kinds or a nonzero
`unprojectedDialogCount`, add:

Some agent content was retained safely in the fetched snapshot but is not
editable through this ADK version yet.

Do not claim that the agent was published, deployed, promoted, or configured
with optional product integrations.

## Handle an existing-agent collision

An HTTP 409 response means create-only protection prevented an existing agent
from being replaced. Explain:

An editable agent created from this package already exists in the target
environment. I did not replace it.

Offer to use the existing agent through the normal existing-Dev path. Offer
replacement only when the maker explicitly needs the supplied package to
replace that Dev agent.

Before replacement, identify and validate the exact existing Dev agent using
the discovery and direct-lookup guidance in
`src/skills/foundation-setup/da-existing-dev.md`. Show its display name, then
ask:

Replacing **{agent display name}** will overwrite its current editable content
with the supplied package. Continue?

Continue only after explicit approval. Pass the selected internal agent ID in
both confirmation arguments without displaying it:

```text
python scripts/setup_alm_import.py \
  --target-url "{POWER_PLATFORM_ENVIRONMENT_URL}" \
  --package "{NATIVE_AGENT_PACKAGE_PATH}" \
  --replace-agent-id "{INTERNAL_AGENT_ID}" \
  --confirm-replace-agent-id "{INTERNAL_AGENT_ID}"
```

The command validates the target as Dev and verifies that replacement retained
the same agent identity. A mismatch is a hard failure.

## Handle interrupted or failed import

If the service returned a normal error response, explain the actionable error
without displaying package content or service diagnostics. Do not write setup
completion state and do not describe the agent as created.

If the request ended without a response, say:

The environment did not return an import result, so I cannot confirm whether
the editable agent was created. I will not retry automatically because that
could repeat a completed operation.

Ask the maker to check the target environment in Copilot Studio. If the agent
exists, continue through the existing-Dev setup path using its URL. If it does
not exist, the maker may explicitly retry the create operation.

Never add polling, retry a mutating request automatically, or convert an
uncertain outcome into success.

## Repair a changed workspace

Use the same explicit refresh flow documented in
`src/skills/foundation-setup/da-existing-dev.md`. Refresh checkpoints and
replaces local workspace content; it does not re-import the package.
