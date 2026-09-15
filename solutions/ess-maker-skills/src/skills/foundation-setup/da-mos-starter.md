<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Set Up Dev from an Entitled MOS Starter Package

Use this path only when the maker has no existing agent and wants a fresh
installation. Read `src/reference/mos-starter-package.md` before acting. The
reference owns the service facts, safety invariants, fuse disposition
matrix, and redaction contract. This skill owns the maker conversation and
the handoff into existing-Dev setup.

## Ask what the maker needs

Ask whether the agent is for HR or IT, and which product it should support
(the core ESS experience, or a specific ISV such as Workday or ServiceNow),
in plain maker language. This choice guides which catalog entry the maker
picks below; it is never sent to or matched by any script.

## List the catalog

Tell the maker that Microsoft sign-in may open, using the exact
authorization message from `SKILL.md`. Run:

```text
python scripts/setup_mos_starter.py list \
  --target-url "{POWER_PLATFORM_ENVIRONMENT_URL}"
```

Parse `DA_MOS_STARTER_PACKAGES_JSON:`. Show only each package's safe
service-provided name, version, and description. Never show a package's
internal `packageId` to the maker.

If the catalog is empty, say that no entitled starter packages are
currently available and stop; do not guess a substitute or fall back to
another setup path.

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

## Create

Run:

```text
python scripts/setup_mos_starter.py create \
  --target-url "{POWER_PLATFORM_ENVIRONMENT_URL}" \
  --package-id "{CONFIRMED_PACKAGE_ID}" \
  --package-name "{CONFIRMED_PACKAGE_NAME}" \
  --package-version "{CONFIRMED_PACKAGE_VERSION}"
```

There is exactly one create attempt per confirmed package selection; do not
pass different package arguments to retry a failed or uncertain attempt.

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
`connectionStatus` is `workspace-ready` and `setupStatus` is `complete`.
The create fuse intentionally remains as an audit note; canonical setup
state independently prevents a second create. If attachment fails, inspect
and rerun only `setup_existing_da.py attach` with the same logged identity.
Never run `create` again for this package.

For every non-created outcome (`pre-dispatch-failure`, `collision`,
`rejected`, `malformed-success`, or an uncertain response or transport
failure), do not retry automatically. Use the existing read-only `list`
and `setup_existing_da.py validate-agent`/`list-agents` commands to inspect
the target environment, following the fuse disposition matrix in
`src/reference/mos-starter-package.md`, before deciding with the maker how
to proceed.

## Hybrid follow-up

After attachment completes, if the maker's earlier product selection was
a hybrid ISV (Workday or ServiceNow) rather than the core ESS experience,
recommend running `/connect` afterward to wire that product's connection.
Never invoke `/connect`, install a connector, or configure Dataverse,
publishing, promotion, or telemetry from this skill yourself.
