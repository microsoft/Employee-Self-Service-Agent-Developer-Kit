# Step 1: Choose an Integration

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## 1.1 — Check what's already connected

Build a list of connected integrations (if any):

- **ServiceNow** — connected if `.local/connect/servicenow/steps.md` exists and
  all items are checked.
- **Workday** — connected only if
  `.local/connect/workday/agents/{active-agent-slug}/lifecycle.json` exists,
  its `agentSlug` exactly matches the active agent, and every phase is `done`.
  Shared provider setup state is not agent connection state and must not make
  a sibling or newly selected agent appear connected.

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

Read `.local/config.json` and resolve the active agent from `activeAgent` and
the matching `agents` entry, falling back to the legacy `agent` object only
when needed. Retain its slug, schema name, and release line. Never select the
first agent in a multi-agent workspace.

If no concrete active agent can be resolved, show:

**Message:**

Select the Employee Self-Service agent you want to connect, then run
`/connect workday` again.

**End message.**

Stop without creating integration state.

Treat these schema names as Declarative Agents:

- `gptagent_copilotforemployeeselfservicehr`
- `gptagent_copilotforemployeeselfserviceit`
- `msdyn_copilotforemployeeselfservicedahr`
- `msdyn_copilotforemployeeselfservicedait`

Also treat any other active agent with `releaseLine: "da"` as Declarative.
Never infer architecture from retired product inventory.

For a Declarative Agent, show:

**Message:**

Workday integration with an ESS Declarative Agent isn't supported in this
release. Please contact your administrator.

**End message.**

Stop immediately. Do not create CEA Workday lifecycle state or run its package
check. `WD-PKG-001` is a CEA package fingerprint and is not an architecture
discriminator. DA package discovery uses `WD-DA-PKG-001` only from an explicit
DA setup path.

For a CEA agent, check the currently installed Workday extension before
honoring lifecycle state:

```
python scripts/flightcheck/cli.py --checkpoint WD-PKG-001
```

Read the `WD-PKG-001` row from `workspace/flightcheck/results.json` and route
by both its status and detected flavor:

- **`Passed` + simplified-install result** — read
  `src/skills/connect/workday/SKILL.md` and follow it, whether or not a
  lifecycle state file already exists.
- **`Passed` + full / legacy result** — do not run the simplified V2 lifecycle.
  Explain that this installation requires the legacy CEA setup experience and
  stop without changing state.
- **`NotConfigured`** — fresh CEA Workday installation is not available from
  the current boundary. Stop without changing state.
- **`Failed`** — show the checkpoint remediation and stop; do not treat a
  partial install as a fresh environment.
- **`Warning` / `Skipped` / `Error`**, or a `Passed` result whose flavor cannot
  be determined — show the result and stop. Never start a lifecycle from an
  inconclusive package check.

### If the user said something else

**Message:**

I didn't catch that. Enter **1** for ServiceNow or **2** for Workday.

**End message.**

Wait for the user and try again.
