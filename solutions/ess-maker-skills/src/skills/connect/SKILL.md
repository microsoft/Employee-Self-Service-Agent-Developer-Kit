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
  - Step 1: `step1.md` — gather info, MCP setup, connectivity check, detect existing state (Entra app, extension pack, RaaS report)
  - Step 2: `step2.md` — Entra SSO setup (mandatory), ISU accounts, security groups, auth policies, API client, domain permissions, RaaS report
  - Step 3: `step3.md` — extension pack install (or diagnose existing), connection setup (3 different auth types), post-install verification, topic redirect auto-push, end-to-end test

**Workday key principles:**
- **Entra SSO is MANDATORY.** The Workday extension pack's OAuthUser
  connection (`ff0df`) uses `runtimeSource: invoker` — it authenticates
  to Workday AS the employee via Entra SSO. Do NOT offer to skip SSO
  setup. Do NOT use Basic auth for all 3 connections.
- **Three connections, three configs.** The 3 Workday SOAP connections
  need DIFFERENT auth types:
  - `d6081` (Context Generic) = Basic auth with ISU_WQL credentials
  - `0786a` (Generic User) = Basic auth with ISU_GENERIC credentials
  - `ff0df` (OAuthUser) = Microsoft Entra ID Integrated (employee SSO)
- **Never skip tasks based on MCP pre-flight.** The Workday MCP uses
  the user's admin credentials. The Power Platform flows use ISU
  accounts. These have different permissions. A passing MCP check does
  NOT mean ISU accounts work at runtime.
- **Verify-then-create pattern.** Use idempotent creation (Add_Only=true,
  catch "already exists") to detect existing ISU accounts and security
  groups without asking the user to search the Workday UI.
- **Auto-push the topic redirect.** The `[Admin] - User Context - Setup`
  topic must redirect to `WorkdaySystemGetUserContext`. Push this via
  push.py automatically — do NOT leave as a manual portal step.
- **Post-install verification.** After extension pack install, verify
  ALL 7 items programmatically: 3 connection refs, 2 flows, 1 env var,
  1 topic redirect. Do NOT accept "done" without checking.

Each integration's tasks.md and config.json persist after completion.
Running `/connect` again lets the user add a different integration
without losing existing ones.
