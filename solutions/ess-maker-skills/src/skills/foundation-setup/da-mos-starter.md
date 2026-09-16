<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Set Up Dev from an Entitled MOS Starter Package

Use this path only when the maker has no existing agent and wants a fresh installation. Read `src/reference/mos-starter-package.md` before acting. The reference owns the service facts, safety invariants, fuse disposition matrix, and redaction contract. This skill owns the maker conversation and the handoff into existing-Dev setup.

Use only intent supplied in the current request and results observed in this invocation. Do not infer persona, product, target, progress, or retry intent from conversation history.

## Ask what the maker needs

Ask:

> What kind of ESS agent are you setting up?

Offer exactly **HR** and **IT**. Then ask whether the maker wants the core ESS experience or support for a specific connected system, using plain maker language. This intent only guides the maker's catalog choice; it is never sent to or matched by a script, and it does not prove that a matching entitled package exists.

Ask for a Copilot Studio environment URL when the target is not supplied. When fresh-agent intent and the target environment are known, mark **Choose the starting point and target environment** complete.

## List the catalog

Tell the maker that Microsoft sign-in may open, using the exact authorization message from `SKILL.md`. Run:

```text
python scripts/setup_mos_starter.py list \
  --target-url "{POWER_PLATFORM_ENVIRONMENT_URL}"
```

Parse `DA_MOS_STARTER_PACKAGES_JSON:`. Show only each package's safe service-provided name, version, and description. Never show a package's internal `packageId` to the maker.

The successful list proves target access, but not a new agent identity. Keep **Verify access and agent identity** current until create and direct attachment validation succeed.

If the catalog is empty, say that no entitled starter packages are currently available and stop; do not guess a substitute or fall back to another setup path.

If `catalogWarnings` is non-empty, tell the maker the catalog listing
was incomplete -- some entries could not be read -- without repeating
the warning detail itself. A row reported in `catalogWarnings` is never
selectable; only offer packages from the `packages` array.

If the command instead fails, parse
`DA_MOS_STARTER_LIST_ANNOTATIONS_JSON:` and the response body
(`DA_MOS_STARTER_LIST_RESPONSE_JSON:` or `..._RESPONSE_TEXT:`) the same
way `create`'s response is interpreted below; a failed listing never
mutates anything, so it is always safe to retry once the reported cause
is resolved.

## Confirm the exact package and target

Ask the maker to explicitly choose one package by name, and confirm the
target Power Platform environment. Do not preselect a choice or infer one
from the maker's stated product. Once confirmed, keep that package's
internal `packageId`, `name`, and `version` for the next step; these are
internal command inputs, not maker-facing text.

Show:

> Create a new {HR or IT} ESS agent in **{friendly environment name or Selected Power Platform environment}** from **{package name} {version}**?

Offer exactly:

- **Create agent**
- **Choose a different package**
- **Cancel setup**

Do not preselect **Create agent**. Each explicit **Create agent** selection authorizes exactly one create attempt with that package and target.

## Create

Only after the maker selects **Create agent**, run:

```text
python scripts/setup_mos_starter.py create \
  --target-url "{POWER_PLATFORM_ENVIRONMENT_URL}" \
  --package-id "{CONFIRMED_PACKAGE_ID}" \
  --package-name "{CONFIRMED_PACKAGE_NAME}" \
  --package-version "{CONFIRMED_PACKAGE_VERSION}"
```

Do not pass different package arguments to retry a failed or uncertain attempt.

## Interpret the response

Parse `DA_MOS_STARTER_CREATE_ANNOTATIONS_JSON:`, then the response body
(`DA_MOS_STARTER_CREATE_RESPONSE_JSON:` or `..._RESPONSE_TEXT:`), then
`DA_MOS_STARTER_CREATE_JSON:` when the command exits zero. The response
body is already redacted; never ask the maker to supply a token or a
response value it might still contain.

Never infer whether a replay is safe from the response message text. Only
the fuse and transport facts the command already classified govern that --
the annotations report `fuseDisposition` and, on a definitive outcome,
whether it is safe to retry. Never rerun `create` merely because a message
sounds retryable.

When the annotations report `outcome: created`, take the internal
`agentId` from `DA_MOS_STARTER_CREATE_JSON:` and run:

```text
python scripts/setup_existing_da.py attach \
  --target-url "{POWER_PLATFORM_ENVIRONMENT_URL}" \
  --agent-id "{RETURNED_AGENT_ID}" \
  --setup-source mos-starter
```

Parse `DA_EXISTING_DEV_DIAGNOSTIC_JSON:` before handling an attachment
error, then parse `DA_EXISTING_DEV_SETUP_JSON:` on success as described in
`da-existing-dev.md`. Treat setup as complete only when
`connectionStatus` is `workspace-ready` and `connectReady: true`.
The create fuse intentionally remains as an audit note; canonical setup
state independently prevents a second create. If attachment fails, inspect
and rerun only `setup_existing_da.py attach` with the same logged identity.
Never run `create` again for this package.

After direct attachment validation succeeds, mark **Verify access and agent identity** and **Establish an editable Dev agent** complete. Render the factual completion report from `da-existing-dev.md` using **Fresh entitled MOS starter package** as the starting point.

For every non-created outcome (`pre-dispatch-failure`, `collision`,
`rejected`, `malformed-success`, or an uncertain response or transport
failure), do not retry automatically. Use the existing read-only `list`
and `setup_existing_da.py validate-agent`/`list-agents` commands to inspect
the target environment, following the fuse disposition matrix in
`src/reference/mos-starter-package.md`, before deciding with the maker how
to proceed.

Only when the annotations explicitly report that retry is safe, and only after the reported cause is resolved, return to [Confirm the exact package and target](#confirm-the-exact-package-and-target). A new **Create agent** selection authorizes one new attempt. An uncertain outcome never permits another create attempt.

## Hybrid follow-up

After attachment completes, if product intent supplied in the current invocation was a hybrid ISV (Workday or ServiceNow) rather than the core ESS experience, recommend running `/connect` afterward to wire that product's connection. Never invoke `/connect`, install a connector, or configure Dataverse, publishing, promotion, or telemetry from this skill yourself.
