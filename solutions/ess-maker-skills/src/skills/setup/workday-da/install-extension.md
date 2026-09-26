<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Phase 1 - Preflight

Run the controller authentication briefing once:

```powershell
python scripts/workday_connect.py auth-plan
```

Explain only credential stores that may prompt during this phase:

- Dataverse browser sign-in verifies the exact environment and maker account.
- PAC may use device-code sign-in to inspect or install the Workday package.
  PAC is a separate Microsoft credential store, so this can be one additional
  sign-in. The controller pins and verifies the resulting PAC account.

Then run:

```powershell
python scripts/workday_connect.py preflight
```

Use `--dataverse-url` only when canonical setup state has no exact Dataverse
URL. Use `--maker-username` only to pin an intended maker account or resolve
account ambiguity; never ask for it when the authenticated account is already
unambiguous.

The command performs the complete phase:

- verifies the selected setup-complete ESS HR agent;
- chooses the architecture-specific Workday package;
- verifies the exact Dataverse URL directly rather than relying on inventory
  visibility;
- verifies the authenticated account and Entra tenant;
- detects or installs the package through PAC; and
- rereads Dataverse to prove the package is installed.

On failure, show the controller's concise error and preserve its blocker. Do
not replace a precise PAC, authentication, or package error with a generic
manual-install instruction. On success, return to `SKILL.md`.
