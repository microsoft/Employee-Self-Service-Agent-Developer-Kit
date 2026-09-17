<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# DA-1 — Install the Workday Extension Package

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading.

This step completes **DA1.1** on the Workday connect checklist. It confirms your
DA Employee Self-Service base agent is installed, then installs the Workday
extension package against it — attempting an automated install first and
falling back to guided manual steps only if this tenant's Marketplace catalog
doesn't support it.

---

## P1.0 — Check for the DA base agent, and install the extension if it's missing

Run the checkpoint that reports both facts at once — whether a DA base agent
exists, and whether Workday is already installed against it:

```
python scripts/flightcheck/cli.py --checkpoint WD-DA-PKG-001
```

Read the checkpoint result from `workspace/flightcheck/results.json`. Build
`TARGET_VERTICALS` from the live `Detected DA base agent editions` value:

- `HR` → `hr`
- `IT` → `it`

An environment may contain both HR and IT. Treat each target vertical
independently; DA1.1 completes only when every target has its corresponding
Workday child package. Do not derive this list from `selected_products`; that
records setup intent and can differ from the packages currently installed in
the environment.

- **`PASSED`** → every required Workday extension package is already installed.
  Show the result, record `verticals` (the `TARGET_VERTICALS` array) into
  `.local/connect/workday-da/config.json`, and go to **record DA1.1** below.
- **`FAILED`** with "No DA Employee Self-Service base agent … was found" →
  your DA base agent isn't installed yet. Stop here — this skill doesn't
  install the base agent.

  **Message:**

  I don't see a DA Employee Self-Service agent installed in this environment
  yet. Run `/setup` first to install it, then come back and run
  `/connect workday` again.

  **End message.**

  Halt this skill entirely — do not proceed to DA-2 or DA-3.

- **`FAILED`** with "The Workday extension package is not installed for the
  {edition} edition" → the base agent is present but Workday isn't installed
  yet. Continue to **P1.1**.
- **`WARNING`** (Dataverse call failed, e.g. permissions or a transient error)
  → show the result verbatim and stop; ask the user to resolve the underlying
  issue (commonly a missing Dataverse role) and re-run this step.

---

## P1.1 — Attempt an automated install

```
python scripts/install_workday_da_extension.py --url "{ENVIRONMENT_URL}" --vertical "{vertical}"
```

Run the command once for each target vertical that the checkpoint reported
missing. `ENVIRONMENT_URL` is the Dataverse endpoint from `.local/config.json`.

Parse the script's JSON marker line:

- **`INSTALLED_WORKDAY_DA_EXTENSION_JSON:`** → that vertical installed (or was
  already installed and the script confirmed it). Continue with the next
  missing vertical. After all installs, re-run `--checkpoint WD-DA-PKG-001`;
  proceed only when it reports `PASSED`.
- **`WORKDAY_DA_EXTENSION_NOT_LISTED_JSON:`** → this tenant's Marketplace
  catalog doesn't list the Workday extension package for the DA agent, so it
  can't be installed automatically here. This is expected in some tenants —
  it is not a failure. Continue to **P1.2** (manual install).
- **`WORKDAY_DA_EXTENSION_INSTALL_TIMEOUT_JSON:`** → the install was started
  but didn't finish within the wait window.

  **Message:**

  The Workday extension package install is still in progress in Power
  Platform — this can take a few minutes. Check back shortly and I'll
  re-verify it.

  **End message.**

  Wait for the user to confirm, then re-run `--checkpoint WD-DA-PKG-001`.
  Loop until it passes, or fall back to **P1.2** if the user reports the
  install failed in the portal.
- Any other exit / error → show the error verbatim and continue to **P1.2**
  (manual install) so the user isn't blocked by an automation failure.

---

## P1.2 — Guided manual install (fallback)

**Message:**

I couldn't install the Workday extension package automatically in this
environment, so let's do it from the admin center — the same place you
installed the base Employee Self-Service agent:

1. Open the [Microsoft 365 admin center](https://admin.microsoft.com) (or
   AppSource, if that's where you installed the base agent).
2. Find the **Workday extension for Employee Self-Service** package for each
   missing edition: **{missing editions}**.
3. Deploy each missing package to this environment.
4. Wait for the deployment to finish, then tell me it's done and I'll verify
   it.

**End message.**

Wait for the user to confirm, then re-run `--checkpoint WD-DA-PKG-001`. Loop
until it passes. While it is not yet passing, keep DA1.1 `in-progress`.

---

## Record DA1.1

When `WD-DA-PKG-001` is `PASSED`:

1. Merge `verticals` (array containing every installed target: `hr`, `it`, or
   both) into `.local/connect/workday-da/config.json` (round-trip merge —
   never drop other keys). For backward compatibility, also write `vertical`
   only when exactly one target is present; remove a stale singular
   `vertical` when both are present.
2. Call [`shared/checklist-updater.md`](./shared/checklist-updater.md) with
   `STEP_ID = "DA1.1"`, `CHECKPOINT_RESULT = "PASSED"`, `GATE = "prog"`.

**Message:**

The Workday extension package is installed for **{installed editions}**.

**End message.**

Return to the DA orchestrator (`src/skills/setup/workday-da/SKILL.md`,
**Start**) to resume at the next unverified row.
