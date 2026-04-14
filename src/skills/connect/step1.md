# Step 1: Choose an Integration

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## 1.1 — Check what's already connected

Check which folders exist under `my/connect/`. For each folder that has a
`tasks.md` where all items are checked, that integration is connected.

Build a list of connected integrations (if any).

---

## 1.2 — Ask which system

If there are connected integrations, show them first:

**Message:**

Currently connected: {list of connected integration names, e.g. "ServiceNow"}

Which system do you want to connect next?

1. **ServiceNow** — IT tickets, HR cases, service catalog
2. **Workday** — Payroll, time off, employee data

**End message.**

If nothing is connected yet:

**Message:**

Which system do you want to connect to your agent?

1. **ServiceNow** — IT tickets, HR cases, service catalog
2. **Workday** — Payroll, time off, employee data

**End message.**

Wait for the user to respond.

---

## 1.3 — Route by selection

### If the user chose ServiceNow (1 or "servicenow")

Check if `my/connect/servicenow/tasks.md` exists.

**If it exists and all items are checked:**

**Message:**

ServiceNow is already connected. Run `/create` to start building topics
that use ServiceNow, or choose a different integration.

**End message.**

Stop here.

**If it exists and some items are unchecked:**

Show the checklist from `my/connect/servicenow/tasks.md` (✅ for checked,
⬜ for unchecked) followed by "Picking up where we left off."

Read `my/connect/servicenow/config.json` to restore saved values
(INSTANCE_NAME, SNOW_USAGE, SNOW_AUTH, etc.). Then find the first unchecked
step and route as follows:

- **Step 1 unchecked** → read `src/skills/connect/servicenow/step1.md`
- **Step 2 unchecked** → check `authType` in config.json:
  - If `oauth2` → read `src/skills/connect/servicenow/step2-oauth2.md`
  - If `basic` → mark step 2 complete, then route to step 3
- **Step 3 unchecked** → check `authType` in config.json:
  - If `oauth2` → read `src/skills/connect/servicenow/step3-oauth2.md`
  - If `basic` → read `src/skills/connect/servicenow/step3-basic.md`
- **Step 4 unchecked** → read `src/skills/connect/servicenow/step4.md`

**If it does not exist:**

Copy `src/skills/connect/servicenow/tasks.md` to
`my/connect/servicenow/tasks.md`.

**Message:**

| # | Task | Status |
|---|------|--------|
| 1 | Instance configured | ⬜ |
| 2 | Connection secured | ⬜ |
| 3 | Extension installed | ⬜ |
| 4 | Connection verified | ⬜ |

Let's connect ServiceNow to your agent.

**End message.**

Now read `src/skills/connect/servicenow/step1.md` and follow it.

### If the user chose Workday (2 or "workday")

**Message:**

Workday integration is coming soon. For now, you can start with ServiceNow,
or type `/menu` to see other things you can do.

**End message.**

Stop here.

### If the user said something else

**Message:**

I didn't catch that. Enter **1** for ServiceNow or **2** for Workday.

**End message.**

Wait for the user and try again.
