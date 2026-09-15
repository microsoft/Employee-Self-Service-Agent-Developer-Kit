# Connect Script

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling
or what files you are reading.

---

## Start

Record anonymous usage telemetry (best-effort, non-blocking — no user-facing
message, and it never fails the step): `python scripts/emit_capability.py connect`

If the user specified an integration as an argument (e.g., the user said
"servicenow", "workday", or "connect-workday", or the prompt was invoked as
`/connect servicenow`), pass it to step1 as PRE_SELECTED_INTEGRATION. Step1
will skip the "which system" question and go directly to routing for that
integration.

Read `src/skills/connect/step1.md` and follow it.

(Step 1 asks which integration, detects existing state, and dispatches —
ServiceNow to its own step files, Workday to the setup orchestrator
`src/skills/setup/SKILL.md`, Connect Workday to its own step files.)

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

- **Workday (full setup)**: handled by the **setup orchestrator**
  (`src/skills/setup/SKILL.md`), not a `connect/workday/` step sequence.
  `src/skills/connect/step1.md` routes the Workday branch straight there. The
  orchestrator sequences the six Workday setup skills (environment, ESS install,
  Entra app, tenant config, extension pack, topic) using the master checklist as
  a resume-aware spine, and persists state under `.local/setup/workday/tasks.md`
  + `setupStatus` in `.local/connect/workday/config.json`. Use this path when
  there is no Workday extension installed yet.

- **Connect Workday** (wire this agent to an existing extension):
  `src/skills/connect/connect-workday/` — confirms the Workday extension
  pack and connections are already healthy, wires this agent's user-context
  redirect so its Workday topics work, and verifies the connection.
  - Steps template: `src/skills/connect/connect-workday/steps.md`
  - State file: `.local/connect/connect-workday/steps.md`
  - Step 1: `step1.md` — verify the extension pack and connections
  - Step 2: `step2.md` — wire the user-context redirect topic
  - Step 3: `step3.md` — verify the connection
  Use this path only when a Workday extension already exists elsewhere in
  the environment and this agent just needs to be wired to it.

Each integration's steps.md and config.json persist after completion.
Running `/connect` again lets the user add a different integration
without losing existing ones.
