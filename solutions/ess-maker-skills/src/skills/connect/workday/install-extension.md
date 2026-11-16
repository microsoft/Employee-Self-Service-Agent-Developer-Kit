<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Phase 1 - Preflight

## Foundation-only scope

This guide and its recovery apply only to Setup's initial Development
foundation, including retries for that same foundation target. Before every
`preflight` invocation or retry, read controller status. For an existing
target, require `activeTargetRealm: dev` and the same agent and environment
recorded by canonical Setup. With no captured Connect target, use Setup's
verified Development selection.

If the active realm is `test` or `prod`, or the existing target cannot be
verified as that Development foundation, do not run `preflight`. Preserve the
active realm, scope, and phase evidence; return to `SKILL.md` for promoted-target
discovery or the current phase's supported recovery. If no target-preserving
recovery is available, show the exact blocker and stop. Do not switch or reset
the active target to enter this guide.

`preflight` resolves the Setup foundation; it is not an active-target-preserving
recheck across realms. It may invalidate saved progress when the resolved
foundation target or maker changes. The handoff-preservation guidance below
applies only while that Development foundation target and maker are unchanged.

Explain only credential stores that may prompt during this phase:

- Dataverse authentication verifies the exact environment and maker account.
  A browser opens only when there is no valid cached session. If no browser
  appears, the controller still validates the cached token against Dataverse;
  silent reuse does not mean the checks were skipped.
- PAC may be used only to resolve the exact Dataverse organization when setup
  inventory does not contain its URL. Local PAC help/version probes do not sign in.
- Read-only Power Platform connection access reuses the selected maker and
  tenant. Explain any additional Microsoft consent/sign-in required for this
  API audience before running; do not ask the maker to choose the known
  environment or account again. Local compatibility checks never authenticate.

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
- checks the exact PAC executable and command options used later, rather than
  assuming every installed version supports them;
- checks PowerShell script parsing without executing authorization changes;
- verifies that PowerShell resolves the same Python as Connect and can import
  the authentication helpers;
- loads the existing Python.NET, architecture-matched .NET runtime, and pinned
  Microsoft Object Model assemblies through the shared validator;
- verifies required local runtime topic mappings and YAML for this agent;
- checks read-only connection API access and reports whether PAC fallback
  capability is available. An empty connection inventory is valid at this
  stage and does not mean connection creation has failed.

Package-install capability is required only when the supported package is
absent. An unavailable PAC discovery fallback is a warning when the primary API
works. If neither API discovery nor a compatible fallback is available, keep
Preflight blocked. A compatible fallback does not prove PAC service access:
that live verification still runs during Connections. Do not claim that these
probes prove installation privileges, runtime write permissions, or employee
Workday sign-in.

After success, show **Preflight checks completed** and render every
`verificationChecks` entry as a plain-language result. This evidence must make
clear that the environment and agent were queried even when authentication
reused a cached session and no browser appeared.

Preflight is read-only. The maker still performs any browser or device-code
sign-in and chooses the environment when discovery cannot resolve one exact
target.

## Guided recovery

On failure, read `details.verificationChecks` from the structured error or the
saved current-phase blocker. Results also persist in Preflight's
`prerequisiteChecks`. For the unchanged Development foundation target and
maker, a tooling failure blocks the current unfinished phase
without reopening completed administrator phases. Show each blocked check's observed `detail`, the
later operation affected in `impact`, and its specific `remediation.steps`.
Keep warnings distinct from blockers. Never say only that a prerequisite is
broken or tell the maker to start setup again.

Use `vscode_askQuestions` with these choices, all initially unset:

```json
[
  {
    "header": "Prerequisites",
    "question": "How would you like to resolve these prerequisite checks?",
    "options": [
      { "label": "Help me fix it" },
      { "label": "Check again" },
      { "label": "Not now" }
    ],
    "allowFreeformInput": false
  }
]
```

- **Help me fix it:** work through the blocked checks, using their returned
  repair steps and existing supported installers. Explain the exact repair
  and request explicit approval before executing any installation, update,
  dependency restoration, or file replacement. Selecting help alone is not
  approval to change the machine. Never install an unrelated dependency.
  For a workspace repair, preserve local edits and offer a separate `/setup`
  repair for the same agent only when needed and explicitly requested. Never
  invoke Setup automatically between Workday phases. Obtain separate approval
  before replacing customized files.
- For `service` remediation, use the actual returned API/consent/network
  error to prepare an environment-administrator handoff. Do not infer missing
  privileges, request passwords, or offer Python/PAC reinstall as a permission
  fix. For `sign-in`, retain the Step 1 maker and tenant and explain the
  observed mismatch before retrying that identity.
- **Check again:** recheck the foundation-only boundary before every retry,
  then rerun `preflight` for the same Development foundation target and maker.
  After an approved repair, do this automatically only within that boundary.
  Reuse cached sign-ins;
  do not clear credential caches, restart the lifecycle, or repeat completed
  administrator handoffs. Local prerequisite results are persisted separately
  so repairing tooling does not discard those handoffs.
- **Not now** or a dismissed question: leave the recorded blocker and saved
  progress intact and finish.

For errors without per-check details, preserve the precise authentication,
target, or readiness error and its supported remediation. Offer the same
recovery choices; do not substitute a generic reinstall instruction.

Offer repair help for non-blocking warnings without requiring the maker to
repair an unused fallback before continuing. After all required checks and
live agent readiness pass, return to `SKILL.md` and continue the saved
lifecycle at its next incomplete step.
