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

Read `src/skills/connect/step1.md` and follow it.

(Step 1 asks which integration. It checks `my/connect/{integration}/tasks.md`
for existing state — completed, in-progress, or fresh. Then it dispatches to
the integration-specific step files.)

---

## Routing

Each integration has its own folder with its own tasks.md and step files:

- **ServiceNow**: `src/skills/connect/servicenow/`
  - Tasks template: `src/skills/connect/servicenow/tasks.md`
  - State file: `my/connect/servicenow/tasks.md`
  - Config file: `my/connect/servicenow/config.json`
  - Step 1: `step1.md` — instance info, MCP setup, connectivity check
  - Step 2 (Entra): `step2-entra.md` — create Entra app registration for user login
  - Step 2 (Certificate): `step2-certificate.md` — create two Entra apps + OIDC + system user
  - Step 2 (OAuth2): `step2-oauth2.md` — create OAuth app via MCP
  - Step 3 (Entra): `step3-entra.md` — install extension pack (Entra fields)
  - Step 3 (Certificate): `step3-certificate.md` — install extension pack (Certificate fields)
  - Step 3 (OAuth2): `step3-oauth2.md` — install extension pack (OAuth2 fields)
  - Step 3 (Basic): `step3-basic.md` — install extension pack (Basic fields)
  - Step 4: `step4.md` — verify connection

- **Workday**: `src/skills/connect/workday/`
  - Tasks template: `src/skills/connect/workday/tasks.md`
  - State file: `my/connect/workday/tasks.md`
  - Config file: `my/connect/workday/config.json`
  - Step 1: `step1.md` — gather info, MCP setup, connectivity check
  - Step 2: `step2.md` — guided admin setup (ISU accounts, security groups, permissions, report)
  - Step 3: `step3.md` — final verification, extension pack install, agent re-extraction

**Workday key principles:**
- **Verify before acting.** Step 2 runs a pre-flight sweep using MCP
  tools (test_connection, get_worker, get_time_off_balance, run_report)
  to detect what's already configured. Only portal-guide tasks that fail
  verification.
- **Two API client types.** Entra ID Integrated auth requires a
  "Register API Client" (first tab) with SAML Bearer Grant + "Use
  Configured IdPs." Basic auth uses "Register API Client for
  Integrations" (second tab) with Authorization Code Grant. These are
  completely different forms with different fields.
- **Check Workday SAML before creating Entra apps.** If a SAML Identity
  Provider already exists in Workday for the user's tenant, find the
  matching Entra app instead of creating a new one.
- **Extension pack install is part of step 3.** Verification alone is
  not enough — the Copilot Studio extension pack must be installed with
  correct connections, environment variables, and cloud flow activation.

Each integration's tasks.md and config.json persist after completion.
Running `/connect` again lets the user add a different integration
without losing existing ones.
