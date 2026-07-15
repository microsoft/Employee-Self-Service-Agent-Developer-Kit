# Connect Script

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling
or what files you are reading.

---

## Start

Record anonymous usage telemetry (best-effort, non-blocking — no user-facing
message, and it never fails the step): `python scripts/emit_capability.py connect`

Set the FlightCheck invocation source for this session so any readiness check
run during connector setup is attributed to `connect` (not `cli`) on the
dashboards. Best-effort — if the shell can't set it, continue anyway:

- bash/zsh: `export ESS_FLIGHTCHECK_INVOCATION_SOURCE=connect`
- PowerShell: `$env:ESS_FLIGHTCHECK_INVOCATION_SOURCE = "connect"`

`scripts/flightcheck/cli.py` reads this env var as the default
`--invocation-source`, so every FlightCheck the connect flow triggers inherits
it without passing the flag explicitly.

If the user specified an integration as an argument (e.g., the user said
"servicenow" or "workday", or the prompt was invoked as `/connect servicenow`),
pass it to step1 as PRE_SELECTED_INTEGRATION. Step1 will skip the
"which system" question and go directly to routing for that integration.

Read `src/skills/connect/step1.md` and follow it.

(Step 1 asks which integration. It checks `.local/connect/{integration}/tasks.md`
for existing state — completed, in-progress, or fresh. Then it dispatches to
the integration-specific step files.)

---

## Routing

Each integration has its own folder with its own tasks.md and step files:

- **ServiceNow**: `src/skills/connect/servicenow/`
  - Tasks template: `src/skills/connect/servicenow/tasks.md`
  - State file: `.local/connect/servicenow/tasks.md`
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

- **Workday**: `src/skills/connect/workday/`
  - Tasks template: `src/skills/connect/workday/tasks.md`
  - State file: `.local/connect/workday/tasks.md`
  - Config file: `.local/connect/workday/config.json`
  - Step 1: `step1.md` — gather info, MCP setup, connectivity check, detect existing state (Entra app, extension pack, RaaS report) and classify the install path (simplified vs legacy)
  - Step 2: `step2.md` — admin setup. Simplified path = Entra SSO + register the Workday API client (the `ff0df` connection's `oauthClientId`). Legacy path = Entra SSO + ISU accounts, security groups, auth policies, API client, domain permissions, RaaS report
  - Step 3: `step3.md` — extension pack install (or diagnose existing), connection setup (simplified: 2 connections; legacy: 4 connections / 3 auth types), post-install verification, topic redirect auto-push, end-to-end test

**Workday key principles:**
- **Two supported install paths.** Detect which one applies in step 1
  and branch:
  - **Simplified** (Microsoft's current default for new installs) —
    only the OAuthUser connection (`ff0df`) + Dataverse. No ISU service
    accounts, no security groups, no RaaS report. User context comes
    from the Workday REST `/workers/me` endpoint via the V2 user-context
    topic. The OAuthUser connection requires a **Workday REST base URL**
    field in addition to the SOAP base URL, and signs in with a
    customer-registered **Workday API client** whose Client ID
    (`oauthClientId`) is captured during admin setup.
  - **Legacy** — the older 4-connection install (`d6081`, `0786a`,
    `ff0df`, Dataverse) with ISU accounts, security groups, and the
    `WD_User_Context` RaaS report. Still fully supported; keep existing
    installs on this path. Fresh installs DEFAULT to simplified.
- **Entra SSO is MANDATORY on BOTH paths.** The Workday extension pack's
  OAuthUser connection (`ff0df`) uses `runtimeSource: invoker` — it
  authenticates to Workday AS the employee via Entra SSO. Do NOT offer
  to skip SSO setup.
- **Legacy path: three connections, three configs.** The 3 Workday SOAP
  connections need DIFFERENT auth types:
  - `d6081` (Context Generic) = Basic auth with ISU_WQL credentials
  - `0786a` (Generic User) = Basic auth with ISU_GENERIC credentials
  - `ff0df` (OAuthUser) = Microsoft Entra ID Integrated (employee SSO)
- **Never skip tasks based on MCP pre-flight.** The Workday MCP uses
  the user's admin credentials. The Power Platform flows use ISU
  accounts (legacy) or the employee's Entra identity (simplified).
  These have different permissions. A passing MCP check does NOT
  mean the runtime connections work.
- **Verify-then-create pattern (legacy).** Use idempotent creation
  (Add_Only=true, catch "already exists") to detect existing ISU
  accounts and security groups without asking the user to search the
  Workday UI.
- **Auto-push the topic redirect.** The `[Admin] - User Context - Setup`
  topic must redirect to the Workday user-context system topic
  (`WorkdaySystemGetUserContext` on legacy, the V2 REST topic on
  simplified). Push this via push.py automatically — do NOT leave it as
  a manual portal step.
- **Post-install verification.** After extension pack install, verify
  programmatically: connection refs (2 for simplified, 3 for legacy),
  2 flows, the topic redirect, plus the env var on legacy. Do NOT
  accept "done" without checking.

Each integration's tasks.md and config.json persist after completion.
Running `/connect` again lets the user add a different integration
without losing existing ones.
