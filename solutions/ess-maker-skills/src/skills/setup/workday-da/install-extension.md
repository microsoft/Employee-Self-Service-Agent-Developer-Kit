<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Phase 1 - Preflight

Explain only credential stores that may prompt during this phase:

- Dataverse browser sign-in verifies the exact environment and maker account.
- PAC may use device-code sign-in to inspect or install the Workday package.
  PAC is a separate Microsoft credential store, so this can be one additional
  sign-in. The controller pins and verifies the resulting PAC account.

Then run:

```powershell
python scripts/workday_connect.py preflight
```

Fresh native-agent setup state identifies the exact environment ID but may not
contain a Dataverse organization URL. The controller first resolves that URL
from setup's cached environment inventory. Do not ask the maker to re-enter or
reselect the environment when an exact ID match exists.

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

The command performs the complete phase:

- verifies the selected setup-complete native ESS HR agent;
- chooses the architecture-specific Workday package;
- verifies the exact Dataverse URL directly rather than relying on inventory
  visibility;
- verifies the authenticated account and Entra tenant;
- detects or installs the package through PAC; and
- rereads Dataverse to prove the package is installed.

This is a controller-owned automated change. It is accurate to say the package
was installed only when PAC succeeded and the Dataverse reread found the
expected solution. The maker still performs any browser or device-code sign-in
and chooses the environment when discovery cannot resolve one exact target.

On failure, show the controller's concise error and preserve its blocker. Do
not replace a precise PAC, authentication, or package error with a generic
manual-install instruction. On success, return to `SKILL.md`.
