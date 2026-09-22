<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# DA-1 — Install the Workday Extension Package

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading.

This step completes **DA1.1** on the Workday connect checklist. It confirms the
ESS HR agent is available, then installs its Workday package. The router must
stop DA IT agents before this file is read.

---

## P1.0 — Check for the DA base agent, and install the extension if it's missing

Resolve the target environment automatically:

1. Use `.local/config.json` `dataverseEndpoint` when present (legacy
   Dataverse-backed workspace).
2. Otherwise read `.local/connect/workday-da/config.json`
   `sidecarDataverseEndpoint`.
3. If neither exists, read `.local/config.json` `environmentId` and run:

   ```
   python scripts/install_workday_da_extension.py --environment-id "{ENVIRONMENT_ID}" --vertical "hr" --resolve-only
   ```

   Parse `WORKDAY_DA_ENVIRONMENT_JSON:` and persist its `environmentUrl` as
   `sidecarDataverseEndpoint`.
4. Only if automatic discovery fails, show the environments available to the
   signed-in account and ask the maker to choose one. Do not ask them to type or
   copy a URL when a selectable environment is available.

Call the resolved value `WORKDAY_DATAVERSE_URL`. Never copy it into
`.local/config.json`; that file's native `powerPlatformApiEndpoint` remains the
agent identity boundary. If `.local/connect/workday-da/config.json` does not
yet exist, create it as an empty JSON object before the first checkpoint; if it
exists, preserve all current fields.

Resolve the package flavor from the active agent schema:

- `gptagent_copilotforemployeeselfservicehr` → `runtime`
- `msdyn_copilotforemployeeselfservicedahr` → `legacy-da`

Call this value `PACKAGE_FLAVOR`. Stop if the active agent does not match one
of these supported HR schemas.

Run the checkpoint that reports both facts at once — whether a DA base agent
exists, and whether Workday is already installed against it:

```
python scripts/flightcheck/cli.py --checkpoint WD-DA-PKG-001 --connect-config ".local/connect/workday-da/config.json"
```

Read the checkpoint result from `workspace/flightcheck/results.json`. The only
supported target is `hr`. An IT base agent or IT Workday package in the same
environment is outside this lifecycle and must not affect DA1.1.

- **`PASSED`** → the required HR Workday extension package is already installed.
  Show the result, record `verticals: ["hr"]` into
  `.local/connect/workday-da/config.json`, and go to **record DA1.1** below.
- **`FAILED`** with "No ESS DA HR agent was found in this environment" or
  "An ESS DA IT agent is installed, but no ESS DA HR agent was found" → the
  supported HR base agent isn't installed. Stop here — this skill doesn't
  install the base agent.

  **Message:**

  I don't see a DA Employee Self-Service agent installed in this environment
  yet. Run `/setup` first to install it, then come back and run
  `/connect workday` again.

  **End message.**

  Halt this skill entirely — do not proceed to DA-2 or DA-3.

- **`FAILED`** with "The Workday package required by the ESS HR agent is not
  installed" → the HR base agent is present but Workday isn't installed yet.
  Continue to **P1.1**.
- Any other **`FAILED`** result → show the result and stop. Do not guess
  whether installation is safe from an unrecognized failure reason.
- **`WARNING` / `SKIPPED`** (Dataverse verification could not run, e.g.
  authentication, permissions, endpoint initialization, or a transient error)
  → show the result verbatim, keep DA1.1 `in-progress`, and stop; ask the user
  to resolve the underlying issue and re-run this step. Never attempt package
  installation from an inconclusive result.

---

## P1.1 — Attempt an automated install

```
python scripts/install_workday_da_extension.py --environment-id "{ENVIRONMENT_ID}" --vertical "hr" --package-flavor "{PACKAGE_FLAVOR}"
```

Use the `--environment-id` form only when
`WORKDAY_DATAVERSE_URL` was resolved from that setup environment ID during
this run. If the URL came from `dataverseEndpoint` or a previously saved
`sidecarDataverseEndpoint`, run:

```
python scripts/install_workday_da_extension.py --url "{WORKDAY_DATAVERSE_URL}" --vertical "hr" --package-flavor "{PACKAGE_FLAVOR}"
```

Run the selected command once.

Parse the script's JSON marker line:

- **`INSTALLED_WORKDAY_DA_EXTENSION_JSON:`** → the HR package installed (or was
  already installed and the script confirmed it). Re-run
`--checkpoint WD-DA-PKG-001` with the same `--connect-config`; proceed only
when it reports `PASSED`.
- **`WORKDAY_DA_EXTENSION_NOT_LISTED_JSON:`** → the Workday package is not
  available to the signed-in account through the environment's application
  catalog. Continue to **P1.2**.
- **`WORKDAY_DA_EXTENSION_INSTALL_TIMEOUT_JSON:`** → the install was started
  but didn't finish within the wait window.

  **Message:**

  The Workday extension package install is still in progress in Power
  Platform — this can take a few minutes. Check back shortly and I'll
  re-verify it.

  **End message.**

  Wait for the user to confirm, then re-run `--checkpoint WD-DA-PKG-001` with
  the same `--connect-config`.
  Loop until it passes, or fall back to **P1.2** if the user reports the
  install failed in the portal.
- Any other exit / error → show the error verbatim and continue to **P1.2**
  (manual install) so the user isn't blocked by an automation failure.

---

## P1.2 — Guided manual install (fallback)

If `PACKAGE_FLAVOR` is `runtime`:

**Message:**

The Workday package could not be installed automatically. Ask a Power Platform
administrator to install **ESS Workday Runtime** from AppSource in this
environment. Tell me when the installation finishes and I'll verify it.

**End message.**

If `PACKAGE_FLAVOR` is `legacy-da`:

**Message:**

The Workday package could not be installed automatically. Ask a Power Platform
administrator to install **Workday HCM DA Connector (HR)** from AppSource in
this environment. Tell me when the installation finishes and I'll verify it.

**End message.**

Wait for the user to confirm, then re-run `--checkpoint WD-DA-PKG-001` with the
same `--connect-config`. Loop until it passes. While it is not yet passing,
keep DA1.1 `in-progress`.

---

## Record DA1.1

When `WD-DA-PKG-001` is `PASSED`:

1. Merge `verticals: ["hr"]` and `vertical: "hr"` into
   `.local/connect/workday-da/config.json` (round-trip merge — never drop other
   keys). Remove any stale `it` entry written by a pre-release version.
2. Call [`shared/checklist-updater.md`](./shared/checklist-updater.md) with
   `STEP_ID = "DA1.1"`, `CHECKPOINT_RESULT = "PASSED"`, `GATE = "prog"`.

**Message:**

The Workday extension package is installed for the **ESS HR Agent**.

**End message.**

Return to the DA orchestrator (`src/skills/setup/workday-da/SKILL.md`,
**Start**) to resume at the next unverified row.
