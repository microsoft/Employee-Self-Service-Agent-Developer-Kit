<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Phase 1 - Preflight

Explain only credential stores that may prompt during this phase:

- Dataverse authentication verifies the exact environment and maker account.
  A browser opens only when there is no valid cached session. If no browser
  appears, the controller still validates the cached token against Dataverse;
  silent reuse does not mean the checks were skipped.
- PAC may be used only to resolve the exact Dataverse organization when setup
  inventory does not contain its URL.

Run read-only preflight discovery:

```powershell
python scripts/workday_connect.py preflight
```

Fresh native-agent setup state identifies the exact environment ID but may not
contain a Dataverse organization URL. The controller first resolves that URL
from setup's cached environment inventory, then asks an existing PAC profile
for the organization whose environment ID exactly matches setup. Do not ask
the maker to re-enter or reselect the environment when either source proves an
exact ID match.

When the controller reports that no Dataverse URL can be resolved, explain
that refreshing Power Platform environment inventory uses its own Microsoft
sign-in, then run:

```powershell
python scripts/list_environments.py
```

Match the inventory result to `.local/config.json` `environmentId`. When there
is exactly one matching environment with a Dataverse URL, rerun preflight with
that URL automatically. Do not show a selection list or ask the maker to
choose again.

If the recorded environment ID is absent or has no linked Dataverse URL, stop
and explain the exact mismatch. Ask for an exact Dataverse URL only when the
maker confirms it belongs to the already recorded setup environment; never
silently select a different environment by display name. Once an exact URL is
known, direct Dataverse verification is authoritative even if a later
inventory call omits it.

Use `--maker-username` only to pin an intended maker account or resolve account
ambiguity. On resume, the controller reuses the previously verified maker
identity automatically.

The command verifies the target, selects the architecture-specific package,
and reports whether that package already exists. It never installs the package.
Do not request installation approval during Preflight or expose package
sequencing details in the customer-facing response.

Before Preflight completes, the controller reuses the setup-complete
environment selection and runs automatic live readiness checks for the
selected agent.
If that evaluation is not ready, show the controller's customer-safe blocker
and keep Preflight open. Do not ask the maker to run a separate readiness
command or expose internal validation identifiers.

The completed phase:

- verifies the selected setup-complete native ESS HR agent;
- chooses the architecture-specific Workday package;
- verifies the exact Dataverse URL directly rather than relying on inventory
  visibility;
- verifies the authenticated account and Entra tenant.

After success, show **Preflight checks completed** and render every
`verificationChecks` entry as a plain-language result. This evidence must make
clear that the environment and agent were queried even when authentication
reused a cached session and no browser appeared.

Preflight is read-only. The maker still performs any browser or device-code
sign-in and chooses the environment when discovery cannot resolve one exact
target.

On failure, show the controller's concise error and preserve its blocker. Do
not replace a precise authentication or target error with a generic
manual-install instruction. On success, return to `SKILL.md`.
