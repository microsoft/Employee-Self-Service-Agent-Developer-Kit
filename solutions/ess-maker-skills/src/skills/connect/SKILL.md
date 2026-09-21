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
ServiceNow to its own step files; Workday first by agent architecture, then
DA to its package/Entra/tenant checklist or CEA to either the lightweight
already-installed lifecycle or the full setup orchestrator.)

---

## Routing

Each integration routes differently — ServiceNow has its own step files;
Workday routes by architecture before package detection:

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

- **Workday**:
  - **CEA extension already installed elsewhere** — a lightweight lifecycle that
    confirms the extension and its connections, wires this agent's Workday
    topics, and validates the connection end to end:
    `src/skills/connect/workday/SKILL.md`, driven by the generic
    `src/skills/connect/shared/lifecycle-runner.md` against
    `src/skills/connect/workday/contract.json`. State:
    `.local/connect/workday/agents/{agent-slug}/lifecycle.json`. This same runner + contract
    pattern is what a future integration reuses — a new ISV only needs its
    own contract file and action fragments, not a new runner.
  - **CEA full/legacy package or nothing installed yet** — unsupported from
    the current hybrid boundary. The router explains the limitation and stops
    without reading `src/skills/setup/SKILL.md` or changing state.
  - **DA HR agent** — the **DA Workday connect skill**
    (`src/skills/setup/workday-da/SKILL.md`). It sequences five steps
    (extension package, Entra app, tenant config, Power Platform/agent
    integration, and signed-in runtime validation) the same resume-aware way.
    State: `.local/setup/workday-da/tasks.md` + `setupStatus` in
    `.local/connect/workday-da/config.json`. DA-scoped settings that cannot be
    queried reliably remain explicit manual/attestation gates; the provider is
    not marked ready until a signed-in Workday scenario succeeds.
  - **DA IT agent** — unsupported for Workday in this release. The router
    stops before creating state or running any Workday lifecycle step and
    directs the maker to contact their administrator.

  `src/skills/connect/step1.md` resolves the active agent from
  `.local/config.json` and its canonical materialization record from
  `.local/setup/config.json`; it never routes from retired product inventory.

Each integration's steps.md and config.json persist after completion.
Running `/connect` again lets the user add a different integration
without losing existing ones.
