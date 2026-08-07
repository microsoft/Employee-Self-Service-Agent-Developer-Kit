# Step 1: Choose an Integration

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## 1.1 — Check what's already connected

Build a list of connected integrations (if any):

- **ServiceNow** — connected if `.local/connect/servicenow/config.json` exists and
  its `setupStatus` shows every applicable setup row (`S1.1` … `S7.2`, counting only
  the auth-path group that matches the captured `authType`) in state `done` (the
  ServiceNow setup orchestrator owns this state).
- **Workday** — connected if `.local/connect/workday/config.json` exists and its
  `setupStatus` shows every setup row (`S1.1` … `S6.2`) in state `done` (the
  setup orchestrator owns this state).

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

ServiceNow connection is handled by the **ServiceNow setup orchestrator**, which
provisions the Power Platform environment, installs the ESS base agent, captures the
instance/scope/sign-in method, provisions the Entra sign-in app (user or certificate
path), guides the ServiceNow-side OIDC registration (attested — never automated),
installs the extension pack, binds the connections, sets the Portal Base URL, turns
on the flows, and validates end to end. It is resume-aware: it renders a working
checklist to `.local/setup/servicenow/tasks.md`, persists `setupStatus` in
`.local/connect/servicenow/config.json`, picks up at the first unverified step, and
fast-forwards steps that are already done. Changing the sign-in method or reconnecting
is handled inside its first skill (capture-servicenow-config, S3.1); only `entra_user`
and `entra_certificate` are supported (the legacy oauth2/basic/graph paths were retired).

Now read `src/skills/setup/servicenow/SKILL.md` and follow it.

### If the user chose Workday (2 or "workday")

Workday connection is handled by the **setup orchestrator**, which provisions
the Power Platform environment, installs the ESS base agent, provisions the
Entra app, configures the Workday tenant, installs the extension pack, and
verifies the connection. It is resume-aware: if setup was already started it
picks up at the first unverified step, and it fast-forwards steps that are
already done.

Now read `src/skills/setup/SKILL.md` and follow it.

### If the user said something else

**Message:**

I didn't catch that. Enter **1** for ServiceNow or **2** for Workday.

**End message.**

Wait for the user and try again.
