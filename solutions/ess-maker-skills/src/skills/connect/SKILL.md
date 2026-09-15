# Connect Script

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling
or what files you are reading.

---

## Start

Record anonymous usage telemetry (best-effort, non-blocking — no user-facing
message, and it never fails the step): `python scripts/emit_capability.py connect`

If the user specified an integration as an argument (e.g., the user said
"servicenow" or "workday", or the prompt was invoked as `/connect servicenow`),
pass it to step1 as PRE_SELECTED_INTEGRATION. Step1 will skip the
"which system" question and go directly to routing for that integration.

Read `src/skills/connect/step1.md` and follow it.

(Step 1 asks which integration, detects existing state, and dispatches —
ServiceNow to its own step files; Workday to either the lightweight
already-installed lifecycle or the full setup orchestrator, depending on
what's already in the environment.)

---

## Routing

Each integration routes differently — ServiceNow has its own step files;
Workday delegates to the setup orchestrator:

- **ServiceNow**: `src/skills/connect/servicenow/`
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

- **Workday**: two paths, chosen automatically by `step1.md`:
  - **Extension already installed elsewhere** — a lightweight lifecycle that
    confirms the extension and its connections, wires this agent's Workday
    topics, and validates the connection end to end:
    `src/skills/connect/workday/SKILL.md`, driven by the generic
    `src/skills/connect/shared/lifecycle-runner.md` against
    `src/skills/connect/workday/contract.json`. State:
    `.local/connect/workday/lifecycle.json`. This same runner + contract
    pattern is what a future integration reuses — a new ISV only needs its
    own contract file and action fragments, not a new runner.
  - **Nothing installed yet** — the full **setup orchestrator**
    (`src/skills/setup/SKILL.md`), which provisions the Power Platform
    environment, installs the ESS base agent, provisions the Entra app,
    configures the Workday tenant, installs the extension pack, and verifies
    the connection. It is resume-aware: if setup was already started it picks
    up at the first unverified step, and it fast-forwards steps that are
    already done. State: `setupStatus` in `.local/connect/workday/config.json`
    + `.local/setup/workday/tasks.md`.

Each integration's steps.md and config.json persist after completion.
Running `/connect` again lets the user add a different integration
without losing existing ones.
