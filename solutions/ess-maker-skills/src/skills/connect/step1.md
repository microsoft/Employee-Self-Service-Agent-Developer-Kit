# Step 1: Choose an Integration

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## 1.1 — Check what's already connected

Build a list of connected integrations (if any):

- **ServiceNow** — connected if `.local/connect/servicenow/steps.md` exists and
  all items are checked.
- **Workday** — connected if either:
  - `.local/connect/workday/config.json` exists and its `setupStatus` shows
    every setup row (`S1.1` … `S6.2`) in state `done` (full setup completed), or
  - `.local/connect/workday-link/steps.md` exists and all items are checked
    (this agent was wired to an already-installed extension).

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

Check if `.local/connect/servicenow/steps.md` exists.

**If it exists and all items are checked:**

Read `.local/connect/servicenow/config.json` to get the current `authType`.
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

Update `.local/connect/servicenow/config.json` — set `authType` to the new
value. Set `status` to `"in-progress"`. Reset all pack statuses in
`packs` from `"installed"` to `"pending"`.

Update `.local/connect/servicenow/steps.md` — reset steps 2, 3, and 4 from
`- [x]` to `- [ ]`.

Update `.local/config.json` — remove the `connections.ServiceNow` entry (it
will be re-created by step 4 with the new auth type after verification).

**Message:**

| # | Step | Status |
|---|------|--------|
| 1 | Instance configured | ✅ |
| 2 | Connection secured | ⬜ |
| 3 | Extension installed | ⬜ |
| 4 | Connection verified | ⬜ |

Switching to **{new auth display name}**. Picking up from step 2.

**End message.**

Read `.local/connect/servicenow/config.json` to restore INSTANCE_NAME and
other values. Then route by the new SNOW_AUTH:

- If `entra` → read `src/skills/connect/servicenow/step2-entra.md`
- If `certificate` → read `src/skills/connect/servicenow/step2-certificate.md`
- If `oauth2` → read `src/skills/connect/servicenow/step2-oauth2.md`
- If `federated` → read `src/skills/connect/servicenow/step2-graph.md`
- If `basic` → mark step 2 complete, read `src/skills/connect/servicenow/step3-basic.md`

**If the user chose 3 (reconnect from scratch):**

Reset `.local/connect/servicenow/steps.md` — all steps to `- [ ]`.

Delete `.local/connect/servicenow/config.json`.

Copy `src/skills/connect/servicenow/steps.md` to
`.local/connect/servicenow/steps.md`.

**Message:**

| # | Step | Status |
|---|------|--------|
| 1 | Instance configured | ⬜ |
| 2 | Connection secured | ⬜ |
| 3 | Extension installed | ⬜ |
| 4 | Connection verified | ⬜ |

Starting fresh. Let's reconnect ServiceNow to your agent.

**End message.**

Now read `src/skills/connect/servicenow/step1.md` and follow it.

**If it exists and some items are unchecked:**

Show the checklist from `.local/connect/servicenow/steps.md` (✅ for checked,
⬜ for unchecked) followed by "Picking up where we left off."

Read `.local/connect/servicenow/config.json` to restore saved values
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

Copy `src/skills/connect/servicenow/steps.md` to
`.local/connect/servicenow/steps.md`.

**Message:**

| # | Step | Status |
|---|------|--------|
| 1 | Instance configured | ⬜ |
| 2 | Connection secured | ⬜ |
| 3 | Extension installed | ⬜ |
| 4 | Connection verified | ⬜ |

Let's connect ServiceNow to your agent.

**End message.**

Now read `src/skills/connect/servicenow/step1.md` and follow it.

### If the user chose Workday (2 or "workday")

**If this agent is already connected to Workday** (per the check in 1.1,
either full setup done or already wired to an extension): show the current
state and stop.

**Message:**

Workday is already connected to this agent.

**End message.**

Stop here.

**If `.local/connect/workday-link/steps.md` exists but some items are
unchecked** (a wiring flow was started but not finished): read
`src/skills/connect/workday-link/step1.md` and follow it — it re-checks
each item and picks up from the first incomplete one.

**If `.local/connect/workday/config.json` exists with `setupStatus` rows
still in progress** (full setup was started but not finished): read
`src/skills/setup/SKILL.md` and follow it — it resumes from the first
unverified step.

**Otherwise** (nothing started yet), check whether a Workday extension
already exists somewhere in this environment:

```
python scripts/flightcheck/cli.py --checkpoint WD-PKG-001
```

**If `PASSED`** (an extension pack is already installed and its connections
are present):

**Message:**

I found a Workday extension already installed in this environment.

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Workday",
    "question": "How do you want to connect this agent to Workday?",
    "options": [
      { "label": "Wire this agent to the existing extension", "description": "Faster — reuses what's already installed", "recommended": true },
      { "label": "Set up Workday from scratch for this agent", "description": "Provisions a new environment, tenant config, and extension pack" }
    ],
    "allowFreeformInput": false
  }
]
```

- If the user picked **wire to the existing extension**: read
  `src/skills/connect/workday-link/step1.md` and follow it.
- If the user picked **set up from scratch**: read
  `src/skills/setup/SKILL.md` and follow it.

**If `FAILED` or `WARNING`** (Workday connection references exist but don't
match a known install shape — partial or unrecognized install):

**Message:**

I found some Workday connection references in this environment, but they
don't match a complete install. Setup may have been started and not
finished, or the shape is one I don't recognize.

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Workday",
    "question": "How do you want to proceed?",
    "options": [
      { "label": "Try wiring this agent to it anyway", "description": "Runs the same checks again — falls back to full setup if it's not usable", "recommended": true },
      { "label": "Set up Workday from scratch for this agent", "description": "Provisions a new environment, tenant config, and extension pack" }
    ],
    "allowFreeformInput": false
  }
]
```

- If the user picked **try wiring it anyway**: read
  `src/skills/connect/workday-link/step1.md` and follow it. It re-runs
  `WD-PKG-001` itself and redirects to full setup if the extension still
  isn't usable.
- If the user picked **set up from scratch**: read
  `src/skills/setup/SKILL.md` and follow it.

**If `NotConfigured` or `Skipped`** (no extension found):

Workday connection is handled by the **setup orchestrator**, which provisions
the Power Platform environment, installs the ESS base agent, provisions the
Entra app, configures the Workday tenant, installs the extension pack, and
verifies the connection. It is resume-aware: if setup was already started it
picks up at the first unverified step, and it fast-forwards steps that are
already done.

Read `src/skills/setup/SKILL.md` and follow it.

### If the user said something else

**Message:**

I didn't catch that. Enter **1** for ServiceNow or **2** for Workday.

**End message.**

Wait for the user and try again.
