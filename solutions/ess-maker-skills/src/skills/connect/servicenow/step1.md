# ServiceNow Step 1: Gather Instance Info & Set Up MCP

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "INSTANCE_NAME = dev352928" or "SNOW_USAGE = itsm" in
chat. The user should only see Message blocks and tool output tables.

---

## 1.1 — Collect instance info (single prompt)

Use the `vscode_askQuestions` tool with these four questions in one call:

```json
[
  {
    "header": "Instance URL",
    "question": "What's your ServiceNow instance URL? (e.g. https://yourcompany.service-now.com)"
  },
  {
    "header": "Connector",
    "question": "How are you connecting ServiceNow to your agent?",
    "options": [
      { "label": "Actions", "description": "Create tickets, get cases, take actions (Power Platform connector)", "recommended": true },
      { "label": "Knowledge search", "description": "Search ServiceNow KB articles via Microsoft 365 Graph connector" },
      { "label": "Both", "description": "Set up actions first, then knowledge search" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Usage",
    "question": "What do you use ServiceNow for?",
    "options": [
      { "label": "IT tickets", "description": "IT issues, hardware/software requests, ticket status" },
      { "label": "HR cases", "description": "HR cases, case status, HR policies" },
      { "label": "Both", "recommended": true }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Authentication",
    "question": "How do your employees sign into ServiceNow?",
    "options": [
      { "label": "Microsoft account (Entra ID)", "description": "Employees use their Microsoft work account" },
      { "label": "Certificate (service-to-service)", "description": "Non-interactive, uses Entra app certificate" },
      { "label": "ServiceNow username and password", "description": "Separate ServiceNow login" },
      { "label": "I'm not sure" },
      { "label": "Dev/test instance", "description": "Simplest setup" }
    ],
    "allowFreeformInput": false
  }
]
```

From the answers, extract:

**Instance URL** → Extract INSTANCE_NAME (the subdomain before `.service-now.com`):
- `https://dev347212.service-now.com` → `dev347212`
- `https://acme.service-now.com/` → `acme`
- `dev347212.service-now.com` → `dev347212`
- `dev347212` → `dev347212`

Strip trailing slashes and paths. Build canonical URL:
`https://{INSTANCE_NAME}.service-now.com`

**Connector** → Map to SNOW_CONNECTOR:
- "Actions" → `powerplatform`
- "Knowledge search" → `graph`
- "Both" → `both`

**Usage** → Map to SNOW_USAGE (only relevant for Power Platform connector):
- "IT tickets" → `itsm`
- "HR cases" → `hrsd`
- "Both" → `both`

If SNOW_CONNECTOR is `graph`, ignore the Usage answer — set SNOW_USAGE
to `none`.

**Authentication** → Map to SNOW_AUTH (only relevant for Power Platform connector):
- "Microsoft account (Entra ID)" → `entra`
- "Certificate (service-to-service)" → `certificate`
- "ServiceNow username and password" → `oauth2`
- "I'm not sure" → `entra`
- "Dev/test instance" → `basic`

If SNOW_CONNECTOR is `graph`, ignore the Authentication answer — set
SNOW_AUTH to `federated` (Graph connector uses Federated Auth).

---

## 1.2 — (Reserved)

No action needed. Proceed to 1.3.

---

## 1.3 — Save config

Write `my/connect/servicenow/config.json`:

```json
{
  "instanceName": "{INSTANCE_NAME}",
  "instanceUrl": "https://{INSTANCE_NAME}.service-now.com",
  "connectorType": "{SNOW_CONNECTOR}",
  "usage": "{SNOW_USAGE}",
  "authType": "{SNOW_AUTH}",
  "packs": {}
}
```

If SNOW_CONNECTOR is `powerplatform` or `both`:
  If SNOW_USAGE is `itsm` or `both`, add `"itsm": "pending"` to packs.
  If SNOW_USAGE is `hrsd` or `both`, add `"hrsd": "pending"` to packs.

---

## 1.4 — Set up the ServiceNow MCP server

Install the MCP server dependencies:

```
pip install -r src/mcp/servicenow/requirements.txt
```

If pip fails, show the error and suggest `python -m pip install ...` instead.

Read `.vscode/mcp.json`. If it exists, parse it. If it doesn't exist,
start with an empty `{ "servers": {} }` object.

Add a `ServiceNow` entry to the `servers` object. **Keep all existing
entries (like Dataverse) intact.**

Also ensure the top-level `inputs` array contains the ServiceNow input
definitions. If `inputs` doesn't exist yet, create it. If it exists,
append to it (don't overwrite existing inputs like Dataverse ones).

Write the merged result back to `.vscode/mcp.json`:

```json
{
  "inputs": [
    {
      "id": "servicenowUsername",
      "type": "promptString",
      "description": "ServiceNow admin username",
      "password": false
    },
    {
      "id": "servicenowPassword",
      "type": "promptString",
      "description": "ServiceNow admin password",
      "password": true
    }
  ],
  "servers": {
    "ServiceNow": {
      "command": "python",
      "args": ["server.py"],
      "cwd": "${workspaceFolder}/src/mcp/servicenow",
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://{INSTANCE_NAME}.service-now.com",
        "SERVICENOW_USERNAME": "${input:servicenowUsername}",
        "SERVICENOW_PASSWORD": "${input:servicenowPassword}"
      }
    }
  }
}
```

Replace `{INSTANCE_NAME}` with the actual instance name from step 1.1.

---

## 1.5 — Start the MCP server

**Message:**

I've configured the ServiceNow connector. Let's start it up:

1. Press **Ctrl+Shift+P** → type **MCP: List Servers** → select it
2. Find **ServiceNow** in the list → click the **Start** button
3. VS Code will prompt for your **ServiceNow admin username** and
   **password** at the top of the screen — type them in

Your credentials are only held in memory and never saved to disk.

Type **done** when the server is running.

**End message.**

Wait for the user.

---

## 1.6 — Verify connectivity

Use the ServiceNow MCP `query_table` tool to run a test:

```
query_table(table="sys_user", query="user_name=admin", fields="sys_id,user_name,name", limit=1)
```

**If the query succeeds** (returns at least one record):

Update `my/connect/servicenow/tasks.md` — change step 1 from
`- [ ]` to `- [x]`.

**Message:**

✅ Instance configured — connected to `{INSTANCE_NAME}`.

| # | Task | Status |
|---|------|--------|
| 1 | Instance configured | ✅ |
| 2 | Connection secured | ⬜ |
| 3 | Extension installed | ⬜ |
| 4 | Connection verified | ⬜ |

**End message.**

---

## 1.7 — Route by connector type and auth type

### If SNOW_CONNECTOR is `graph`:

Skip steps 2 and 3 for Power Platform. Go directly to the Graph
connector setup:

Read `src/skills/connect/servicenow/step2-graph.md` and follow it.

### If SNOW_CONNECTOR is `powerplatform` or `both`:

Route by SNOW_AUTH for the Power Platform connector:

- If SNOW_AUTH is `entra`:
  Read `src/skills/connect/servicenow/step2-entra.md` and follow it.

- If SNOW_AUTH is `certificate`:
  Read `src/skills/connect/servicenow/step2-certificate.md` and follow it.

- If SNOW_AUTH is `oauth2`:
  Read `src/skills/connect/servicenow/step2-oauth2.md` and follow it.

- If SNOW_AUTH is `basic`:
  Update step 2 from `- [ ]` to `- [x]` in `my/connect/servicenow/tasks.md`.
  Read `src/skills/connect/servicenow/step3-basic.md` and follow it.

When the Power Platform flow completes (step 4 finishes), check
SNOW_CONNECTOR. If it is `both`, continue to the Graph connector:

Read `src/skills/connect/servicenow/step2-graph.md` and follow it.

---

**If the query in 1.6 fails:**

**Message:**

I couldn't reach your ServiceNow instance. Common causes:

- **Wrong URL** — double-check the instance name (`{INSTANCE_NAME}`)
- **Wrong credentials** — the username/password need admin access
- **Instance is sleeping** — developer instances hibernate after inactivity;
  log in via browser first to wake it up

To retry: press **Ctrl+Shift+P** → **MCP: List Servers** → stop and
restart the **ServiceNow** server.

Type **retry** to test again, or **back** to re-enter the instance URL.

**End message.**

Wait for the user. If they say retry, go back to 1.6. If they say back,
go back to 1.1.
