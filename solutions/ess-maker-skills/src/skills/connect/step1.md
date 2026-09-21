# Step 1: Choose an Integration

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## 1.1 — Check what's already connected

Read `.local/config.json` when it exists and resolve `ACTIVE_AGENT_SLUG` from
`activeAgent`, falling back to `agent.slug`. Resolve the matching active agent
record and retain its `schemaName` / architecture. Use this identity for every
agent-specific integration state and validation below.

Build a list of connected integrations (if any):

- **ServiceNow** — connected if `.local/connect/servicenow/steps.md` exists and
  all items are checked.
- **Workday** — connected if either:
  - `.local/connect/workday/config.json` exists and its `setupStatus` shows
    every CEA setup row (`S1.1` … `S6.2`) in state `done` (the CEA setup
    orchestrator owns this state), or
  - `.local/connect/workday/agents/{ACTIVE_AGENT_SLUG}/lifecycle.json` exists
    and every phase is `done` (this specific CEA agent was wired to an
    extension already installed elsewhere — see 1.3 below), or
  - the active agent is the ESS DA HR Agent and
    `.local/connect/workday-da/config.json` has `status: "ready"` with every
    DA setup row through `DA5.1` in state `done`.

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

Resolve `activeAgent` against `.local/config.json` `agents`, falling back to
the legacy `agent` object only when needed. Do not consult the retired
`selected_products` field.

If no concrete active agent with architecture identity can be resolved, show:

**Message:**

Select the Employee Self-Service agent you want to connect, then run
`/connect servicenow` again.

**End message.**

Stop immediately without creating or updating ServiceNow state.

If the active agent is a Declarative Agent, show:

**Message:**

ServiceNow integration with an ESS Declarative Agent isn't supported in this
release. Please contact your administrator.

**End message.**

Stop immediately. Do not create ServiceNow state or enter the ServiceNow
lifecycle. Continue below only for a concrete active CEA agent.

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

First find out which ESS agent is active. Read `.local/config.json`, resolve
`activeAgent` against `agents`, and fall back to the legacy `agent` object only
when needed. For a DA agent, also read the canonical
`.local/setup/config.json` `agents` record keyed by the active `botId` and
require `connect_ready: true`.

- **No concrete active agent, missing schema/architecture identity, or a DA
  agent whose canonical setup is not connect-ready** — setup is incomplete.

  **Message:**

  I don't see a setup-complete Employee Self-Service agent selected in this
  workspace yet. Run `/setup` or select the intended agent first, then come
  back and run `/connect workday` again.

  **End message.**

  Stop here.

Route from the active agent's `releaseLine` and schema name
(`schemaName`/`schema_name`):

- active `msdyn_copilotforemployeeselfservicedahr` or
  `msdyn_copilotforemployeeselfservicedait` → use the DA rules below;
- another agent with `releaseLine: "da"` → use the DA unsupported-target
  rules below;
- active CEA agent → skip to **CEA agent** below.

Never infer the target from a retired `selected_products` field or from the
first installed agent in a multi-agent workspace.

### DA HR agent

Enter this branch only when the active agent is DA. Use its schema name to
determine the vertical.

**ESS DA IT is not supported in this release.** If the active agent is
`msdyn_copilotforemployeeselfservicedait`, show:

**Message:**

Workday integration with the ESS IT Agent isn't supported in this release.
Please contact your administrator.

**End message.**

Stop immediately. Do not create DA Workday state, run a Workday package
checkpoint, install a package, or enter any DA Workday lifecycle step.

**ESS DA Hub is not supported in this release.** If the active agent is the
ESS DA Hub, show:

**Message:**

Workday integration with the ESS Hub Agent isn't supported in this release.
Please select the ESS HR Agent or contact your administrator.

**End message.**

Stop immediately without creating or updating Workday state.

**ESS DA HR is supported.** Continue only when the active agent is
`msdyn_copilotforemployeeselfservicedahr`. Do not run `WD-PKG-001` or the CEA
lifecycle: DA packages share some Workday connection-reference names with CEA,
so that checkpoint is not an architecture discriminator.

Read `src/skills/setup/workday-da/SKILL.md` and follow it. That skill runs
`WD-DA-PKG-001`, installs or verifies the DA HR Workday child package, and
resumes the DA HR checklist through Entra, tenant, Power Platform connection,
bot-to-flow authorization, topic selection, and signed-in runtime validation.

### CEA agent

Enter this branch when the resolved active agent is CEA.

Check the current CEA Workday extension before honoring any existing lifecycle
state:

```
python scripts/flightcheck/cli.py --checkpoint WD-PKG-001
```

Read the `WD-PKG-001` row from `workspace/flightcheck/results.json` and route
by both its status and detected flavor:

- **`Passed` + simplified-install result** — the installed extension can use
  the lightweight per-agent lifecycle. Whether or not
  `.local/connect/workday/agents/{ACTIVE_AGENT_SLUG}/lifecycle.json` already
  exists, read
  `src/skills/connect/workday/SKILL.md` and follow it.
- **`Passed` + full / legacy result** — do not run the simplified V2 wiring
  lifecycle. Full/legacy CEA Workday setup is not available from the current
  hybrid setup boundary; explain that this existing installation needs the
  legacy CEA setup experience and stop without changing state.
- **`NotConfigured`** — no Workday package is installed. Fresh CEA Workday
  installation is not available from the current hybrid setup boundary;
  explain that this release supports the DA HR Workday path and stop without
  changing state.
- **`Failed`** — a partial or broken install was detected. Show the checkpoint
  remediation and stop; do not treat it as a fresh environment.
- **`Warning` / `Skipped` / `Error`**, or a `Passed` result whose flavor cannot
  be determined — package detection is inconclusive. Show the result and stop
  so the maker can remediate or retry. Never start setup from an inconclusive
  package check.

### If the user said something else

**Message:**

I didn't catch that. Enter **1** for ServiceNow or **2** for Workday.

**End message.**

Wait for the user and try again.
