# Step 1: Choose an Integration

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## 1.1 — Check what's already connected

Read `.local/config.json` when it exists and resolve `ACTIVE_AGENT_SLUG` from
`activeAgent`, falling back to `agent.slug`. Use this identity for every
agent-specific Workday state and validation below.

Build a list of connected integrations (if any):

- **ServiceNow** — connected if `.local/connect/servicenow/steps.md` exists and
  all items are checked.
- **Workday** — connected if either:
  - `.local/connect/workday/config.json` exists and its `setupStatus` shows
    every CEA setup row (`S1.1` … `S6.2`) in state `done` (the CEA setup
    orchestrator owns this state), or
  - `.local/connect/workday/agents/{ACTIVE_AGENT_SLUG}/lifecycle.json` exists
    and every phase is `done` (this specific CEA agent was wired to an
    extension already installed elsewhere — see 1.3 below).

The DA checklist deliberately does not count as "connected" yet. It confirms
package, Entra, and tenant configuration, but DA-scoped live connection
binding and agent-path validation are still deferred.

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

First find out which kind of ESS agent is in this environment. Read
`.local/setup/config.json` and look at
`selected_products` (each entry is one of `da.esshr` / `da.essit` / `da.esshub`
/ `cea.esshr` / `cea.essit` / `cea.esshub`):

- **No `.local/setup/config.json`, or `selected_products` is empty** — no ESS
  agent has been installed in this environment yet.

  **Message:**

  I don't see an Employee Self-Service agent installed in this environment yet.
  Run `/setup` first, then come back and run `/connect workday` again.

  **End message.**

  Stop here.

### DA agent

**If any `selected_products` entry starts with `da.`**, use only the DA path.
Do not run `WD-PKG-001` or the CEA lifecycle: DA packages share some Workday
connection-reference names with CEA, so that checkpoint is not an
architecture discriminator.

Read `src/skills/setup/workday-da/SKILL.md` and follow it. That skill runs
`WD-DA-PKG-001`, installs any missing DA Workday child package, and resumes
the DA Entra and tenant checklist from live state.

### CEA agent

**Otherwise, only `cea.*` entries are present.**

If `.local/connect/workday/agents/{ACTIVE_AGENT_SLUG}/lifecycle.json` already
exists, read `src/skills/connect/workday/SKILL.md` and follow it. It
re-verifies the active agent live before reporting "connected."

Otherwise, check whether a CEA Workday extension already exists in this
environment:

```
python scripts/flightcheck/cli.py --checkpoint WD-PKG-001
```

**If `Passed`:** a Workday extension is already installed in this
environment — this agent likely just needs to be wired to it, not a full
install. Read `src/skills/connect/workday/SKILL.md` and follow it; it shows
the user what it will check before doing anything, and only makes changes
once they confirm.

**If anything other than `Passed`**, read `src/skills/setup/SKILL.md` and
follow it. This path provisions the Power Platform environment, installs the
ESS base agent, provisions the Entra app, configures the Workday tenant,
installs the extension pack, and verifies the connection. It is resume-aware.

### If the user said something else

**Message:**

I didn't catch that. Enter **1** for ServiceNow or **2** for Workday.

**End message.**

Wait for the user and try again.
