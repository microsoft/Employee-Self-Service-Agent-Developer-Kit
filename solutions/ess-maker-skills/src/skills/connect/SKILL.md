# Connect Script

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling
or what files you are reading.

---

## Start

If the user specified an integration as an argument (e.g., the user said
"servicenow" or "workday", or the prompt was invoked as `/connect servicenow`),
pass it to step1 as PRE_SELECTED_INTEGRATION. Step1 will skip the
"which system" question and go directly to routing for that integration.

Read `.local/config.json`.

If the selected integration is ServiceNow and any entry in `agents` has
`releaseLine: da`,
record anonymous usage telemetry attributed to ServiceNow (best-effort,
non-blocking, and with no user-facing message):
`python scripts/emit_capability.py connect --connector servicenow`.
Then read `src/skills/connect/servicenow-da/SKILL.md` and follow it. This is
the shared DA-GA HRSD/ITSM workflow and it must not route through the retained
Preview-era ServiceNow steps.

Otherwise read `src/skills/connect/step1.md` and follow it. That file records
anonymous usage telemetry after routing knows which integration was chosen, so
the Connect capability event carries the correct `connector` attribution
(workday vs servicenow) rather than being a generic "connect" wedge.

(Step 1 asks which integration, detects existing state, and dispatches —
ServiceNow to its own step files; Workday first by agent architecture, then
DA to its package/Entra/tenant checklist or CEA to either the lightweight
already-installed lifecycle or the existing unsupported-install boundary.)

---

## Routing

Each integration routes differently — ServiceNow has its own step files;
Workday routes by architecture before package detection:

- **ServiceNow DA-GA HRSD/ITSM workflow**:
  `src/skills/connect/servicenow-da/SKILL.md`
  - State:
    `.local/connect/servicenow/agents/<agent-id>/state.json`
  - Uses MinimalBot Components and Power Platform Connectivity APIs.
  - Lists live ESS HR/IT agents and selects one for the current invocation
    without changing `activeAgent`.
  - Selects the explicit HRSD or ITSM product profile from the chosen agent
    schema.
  - Does not use Dataverse connection-reference or workflow operations.

- **ServiceNow retained Preview path**: `src/skills/connect/servicenow/`
  - Steps template: `src/skills/connect/servicenow/steps.md`
  - State file: `.local/connect/servicenow/steps.md`
  - Config file: `.local/connect/servicenow/config.json`
  - Step 1: `step1.md` — instance info, MCP setup, connectivity check
  - Step 2 (Entra): `step2-entra.md` — create Entra app registration for user login
  - Step 2 (Certificate): `step2-certificate.md` — create two Entra apps + OIDC + system user
  - Step 2 (OAuth2): `step2-oauth2.md` — create OAuth app via MCP
  - Step 3 (Entra): `step3-entra.md` — install extension pack (Entra fields)
  - Step 3 (Certificate): `step3-certificate.md` — install extension pack (Certificate fields)
  - Step 3 (OAuth2): `step3-oauth2.md` — install extension pack (OAuth2 fields)
  - Step 3 (Basic): `step3-basic.md` — install extension pack (Basic fields)
  - Step 4: `step4.md` — verify connection

- **Workday**:
  - **CEA simplified extension already installed** — use
    `src/skills/connect/workday/SKILL.md`, driven by the generic
    `src/skills/connect/shared/lifecycle-runner.md` and
    `src/skills/connect/workday/contract.json`.
  - **CEA full/legacy package or no package** — stop at the current unsupported
    installation boundary without changing state.
  - **DA HR agent** — use `src/skills/setup/workday-da/SKILL.md` for the
    resumable package, Entra, tenant, Power Platform, and runtime checklist.
  - **DA IT or another DA agent** — unsupported for Workday in this release;
    stop before creating state or entering a Workday lifecycle.

  CEA per-agent lifecycle state is stored at
  `.local/connect/workday/agents/{agent-slug}/lifecycle.json`. DA Workday state
  is stored in `.local/connect/workday-da/config.json` and
  `.local/setup/workday-da/tasks.md`.

Each integration's steps.md and config.json persist after completion.
Running `/connect` again lets the user add a different integration
without losing existing ones.
