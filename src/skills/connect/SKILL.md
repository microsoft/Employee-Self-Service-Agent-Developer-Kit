# Connect Script

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling
or what files you are reading.

---

## Start

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
  - Step 2 (OAuth2): `step2-oauth2.md` — create OAuth app via MCP
  - Step 3 (OAuth2): `step3-oauth2.md` — install extension pack (OAuth2 fields)
  - Step 3 (Basic): `step3-basic.md` — install extension pack (Basic fields)
  - Step 4: `step4.md` — verify connection

Each integration's tasks.md and config.json persist after completion.
Running `/connect` again lets the user add a different integration
without losing existing ones.
