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

**If PRE_SELECTED_INTEGRATION was passed from SKILL.md** (the user already
specified "servicenow" or "workday"): skip this question entirely. Set the
selection to the pre-selected value and go directly to section 1.3.

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

Read `my/connect/servicenow/config.json` to get the current `authType`.
Map it to a display name:
- `entra` → "Entra ID (interactive sign-in)"
- `certificate` → "Certificate (service-to-service)"
- `oauth2` → "OAuth2 (ServiceNow credentials)"
- `basic` → "Basic auth"

**Message:**

ServiceNow is already connected using **{display name}**.

1. **Keep current setup** — run `/create` to start building topics
2. **Change authentication** — switch to a different auth method
3. **Reconnect from scratch** — reset everything and start over

**End message.**

Wait for the user.

**If the user chose 1 (keep):** Stop here.

**If the user chose 2 (change auth):**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Authentication",
    "question": "Which authentication method do you want to switch to?",
    "options": [
      { "label": "Microsoft account (Entra ID)", "description": "Employees use their Microsoft work account" },
      { "label": "Certificate (service-to-service)", "description": "Non-interactive, uses Entra app certificate" },
      { "label": "ServiceNow username and password", "description": "Separate ServiceNow login" },
      { "label": "Dev/test instance", "description": "Simplest setup" }
    ],
    "allowFreeformInput": false
  }
]
```

Map the answer to SNOW_AUTH using the same rules as
`src/skills/connect/servicenow/step1.md` section 1.1 (the per-product
step1, NOT this top-level routing file).

Update `my/connect/servicenow/config.json` — set `authType` to the new
value. Set `status` to `"in-progress"`. Reset all pack statuses in
`packs` from `"installed"` to `"pending"`.

Update `my/connect/servicenow/tasks.md` — reset steps 2, 3, and 4 from
`- [x]` to `- [ ]`.

Update `my/config.json` — remove the `connections.ServiceNow` entry (it
will be re-created by step 4 with the new auth type after verification).

**Message:**

| # | Task | Status |
|---|------|--------|
| 1 | Instance configured | ✅ |
| 2 | Connection secured | ⬜ |
| 3 | Extension installed | ⬜ |
| 4 | Connection verified | ⬜ |

Switching to **{new auth display name}**. Picking up from step 2.

**End message.**

Read `my/connect/servicenow/config.json` to restore INSTANCE_NAME and
other values. Then route by the new SNOW_AUTH:

- If `entra` → read `src/skills/connect/servicenow/step2-entra.md`
- If `certificate` → read `src/skills/connect/servicenow/step2-certificate.md`
- If `oauth2` → read `src/skills/connect/servicenow/step2-oauth2.md`
- If `federated` → read `src/skills/connect/servicenow/step2-graph.md`
- If `basic` → mark step 2 complete, read `src/skills/connect/servicenow/step3-basic.md`

**If the user chose 3 (reconnect from scratch):**

Reset `my/connect/servicenow/tasks.md` — all steps to `- [ ]`.

Delete `my/connect/servicenow/config.json`.

Copy `src/skills/connect/servicenow/tasks.md` to
`my/connect/servicenow/tasks.md`.

**Message:**

| # | Task | Status |
|---|------|--------|
| 1 | Instance configured | ⬜ |
| 2 | Connection secured | ⬜ |
| 3 | Extension installed | ⬜ |
| 4 | Connection verified | ⬜ |

Starting fresh. Let's reconnect ServiceNow to your agent.

**End message.**

Now read `src/skills/connect/servicenow/step1.md` and follow it.

**If it exists and some items are unchecked:**

Show the checklist from `my/connect/servicenow/tasks.md` (✅ for checked,
⬜ for unchecked) followed by "Picking up where we left off."

Read `my/connect/servicenow/config.json` to restore saved values
(INSTANCE_NAME, SNOW_USAGE, SNOW_AUTH, etc.). Then find the first unchecked
step and route as follows:

- **Step 1 unchecked** → read `src/skills/connect/servicenow/step1.md`
- **Step 2 unchecked** → check `authType` in config.json:
  - If `entra` → read `src/skills/connect/servicenow/step2-entra.md`
  - If `certificate` → read `src/skills/connect/servicenow/step2-certificate.md`
  - If `oauth2` → read `src/skills/connect/servicenow/step2-oauth2.md`
  - If `federated` → read `src/skills/connect/servicenow/step2-graph.md`
  - If `basic` → mark step 2 complete, then route to step 3
- **Step 3 unchecked** → check `authType` in config.json:
  - If `entra` → read `src/skills/connect/servicenow/step3-entra.md`
  - If `certificate` → read `src/skills/connect/servicenow/step3-certificate.md`
  - If `oauth2` → read `src/skills/connect/servicenow/step3-oauth2.md`
  - If `federated` → read `src/skills/connect/servicenow/step3-graph.md`
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

Check if `my/connect/workday/tasks.md` exists.

**If it exists and all items are checked:**

Read `my/connect/workday/config.json` to get the current tenant name.

**Message:**

Workday is already connected (tenant: **{tenant}**).

1. **Keep current setup** — run `/create` to start building topics
2. **Reconnect from scratch** — reset everything and start over

**End message.**

Wait for the user.

**If the user chose 1 (keep):** Stop here.

**If the user chose 2 (reconnect):**

Reset `my/connect/workday/tasks.md` — all steps to `- [ ]`.

Delete `my/connect/workday/config.json`.

Copy `src/skills/connect/workday/tasks.md` to
`my/connect/workday/tasks.md`.

**Message:**

| # | Task | Status |
|---|------|--------|
| 1 | Environment configured | ⬜ |
| 2 | Admin setup complete | ⬜ |
| 3 | Connection verified | ⬜ |

Starting fresh. Let's reconnect Workday to your agent.

**End message.**

Now read `src/skills/connect/workday/step1.md` and follow it.

**If it exists and some items are unchecked:**

Show the checklist from `my/connect/workday/tasks.md` (✅ for checked,
⬜ for unchecked) followed by "Picking up where we left off."

Read `my/connect/workday/config.json` to restore saved values. Then
find the first unchecked step and route:

- **Step 1 unchecked** → read `src/skills/connect/workday/step1.md`
- **Step 2 unchecked** → read `src/skills/connect/workday/step2.md`
- **Step 3 unchecked** → read `src/skills/connect/workday/step3.md`

**If it does not exist:**

Copy `src/skills/connect/workday/tasks.md` to
`my/connect/workday/tasks.md`.

**Message:**

| # | Task | Status |
|---|------|--------|
| 1 | Environment configured | ⬜ |
| 2 | Admin setup complete | ⬜ |
| 3 | Connection verified | ⬜ |

Let's connect Workday to your agent.

**End message.**

Now read `src/skills/connect/workday/step1.md` and follow it.

### If the user said something else

**Message:**

I didn't catch that. Enter **1** for ServiceNow or **2** for Workday.

**End message.**

Wait for the user and try again.
