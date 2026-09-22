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
3. If neither exists, show the environments available to the
   signed-in account and ask the maker to choose one. Do not ask them to type or
   copy a URL when a selectable environment is available. Persist the selected
   Dataverse URL as `sidecarDataverseEndpoint`.

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
python scripts/install_workday_da_extension.py --url "{WORKDAY_DATAVERSE_URL}" --vertical "hr" --package-flavor "{PACKAGE_FLAVOR}" --ring "{RING}"
```

Read `RING` from canonical setup state `environment.ring`; use `prod` only for
legacy state with no recorded ring. Run the command once. The installer selects
or creates a PAC profile for that ring and PAC polls AppSource installation
internally.

Parse the script's JSON marker line:

- **`INSTALLED_WORKDAY_DA_EXTENSION_JSON:`** → the HR package installed (or was
  already installed and the script confirmed it). Re-run
`--checkpoint WD-DA-PKG-001` with the same `--connect-config`; proceed only
when it reports `PASSED`.
- **`WORKDAY_PACKAGE_INSTALL_FAILED_JSON:`** → show its concise `error` value
  and stop with DA1.1 `in-progress`. Do not claim the package needs a manual
  AppSource installation. PAC's output is the source of truth:
  - If PAC CLI is missing, ask whether the maker wants the kit to install the
    current-user managed copy. If approved, run:

    ```powershell
    dotnet tool install --tool-path "$env:LOCALAPPDATA\InternalTools\pac" --interactive --verbosity n --configfile "scripts\managed-pac.nuget.config" Microsoft.PowerApps.CLI.Tool
    ```

    If the tool is already present but needs repair or update, run the same
    command with `update` instead of `install`. Then rerun P1.1.
  - If PAC starts device-code authentication, wait for it to finish.
  - If multiple profiles exist for the required ring, ask the maker to select
    the intended profile with `pac auth select`, then retry.
  - For permission or package-availability errors, show PAC's output and ask
    the maker to correct that exact issue before retrying.

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
