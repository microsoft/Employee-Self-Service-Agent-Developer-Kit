# Step 1: Connect to Dataverse

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## 1.0 — Ask how to provide the environment

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Environment setup",
    "question": "Would you like me to list all the Power Platform environments in your tenant so you can pick one?",
    "options": [
      { "label": "Yes, list my environments", "description": "Sign in and browse available environments" },
      { "label": "No, I'll enter the URL manually", "description": "I already know my environment URL" }
    ],
    "allowFreeformInput": false
  }
]
```

- If the user chose **"Yes, list my environments"** → go to step 1.1.
- If the user chose **"No, I'll enter the URL manually"** → go to step 1.1c.

---

## 1.1 — List environments and let the user pick

**Message (do NOT wait for user response — continue immediately):**

Let me find the Power Platform environments available in your tenant. A
browser window will open for sign-in...

**End message.**

Run this command in the terminal:

```
python scripts/discover.py --list-environments
```

A browser window will open for sign-in. Wait for the script to finish.

**Check the terminal output:**

- **Script printed `ENV_TABLE_MARKDOWN:<path>` → go to step 1.1a.**
- **Script failed with an auth/permission error → go to step 1.1c.**

---

## 1.1a — Show the table and ask the user to pick

Read the Markdown file at the path printed after `ENV_TABLE_MARKDOWN:`
(it is `workspace/onboarding/environments.md`). It contains a complete,
numbered table of environments. Do NOT rebuild it from the terminal
output — read it from the file so no rows are lost.

Show the user this Message, with `{TABLE}` replaced by the **entire**
contents of that Markdown file rendered as-is:

**Message:**

Here are the Power Platform environments in your tenant:

{TABLE}

Reply with the **number** of the environment your ESS agent is deployed
in (for example, `2`).

**End message.**

Wait for the user to reply with a number. Save it as NUMBER and go to
step 1.1b.

---

## 1.1b — Confirm selection

Run the selection command in the terminal:

```
python scripts/discover.py --list-environments --select {NUMBER}
```

Find the line starting with `SELECTED_ENV_JSON:` in the output. Parse the
JSON after the colon to get the `instanceUrl` field. Save it as ENV_URL.
**Strip any trailing slash** from ENV_URL before using it (e.g.,
`https://org.crm.dynamics.com/` becomes `https://org.crm.dynamics.com`).

If the command instead prints an `ERROR: Invalid selection` line, show the
table again (step 1.1a) and ask for a valid number.

Go to step 1.2.

---

## 1.1c — Manual URL entry (fallback)

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Environment URL",
    "question": "What's your Power Platform environment URL? (e.g. https://yourorg.crm.dynamics.com — find it in the Power Platform admin center)"
  }
]
```

Save their answer as ENV_URL. **Strip any trailing
slash** from ENV_URL before using it (e.g., `https://org.crm.dynamics.com/`
becomes `https://org.crm.dynamics.com`).

## 1.2 — Write the MCP config file

Build the MCP URL by appending `/api/mcp` to ENV_URL. Double-check the
result has exactly ONE slash between the domain and `api` — for example
`https://org.crm.dynamics.com/api/mcp`, NOT `https://org.crm.dynamics.com//api/mcp`.

Create `.vscode/mcp.json` with this exact content (replace the entire
`url` value with the MCP URL you just built):

```json
{
  "servers": {
    "Dataverse": {
      "type": "http",
      "url": "https://org.crm.dynamics.com/api/mcp"
    }
  }
}
```

Then immediately show:

**Message:**

Done. Now there's a one-time admin step to enable the Dataverse connector:

1. Go to [Power Platform admin center](https://admin.powerplatform.microsoft.com/environments)
   → your environment → **Settings** → **Product** → **Features**
2. Turn on **"Allow MCP clients to interact with Dataverse MCP server
   (GA version)"** and click **Save**
3. Click **"Go to Advanced Settings"** → find **"Microsoft GitHub Copilot"**
   → set **Is Enabled** to **Yes** → **Save & Close**

Type **done** when that's set up, or **skip** if it's already enabled.

**End message.**

Wait for the user.

## 1.3 — Proceed to agent discovery

The MCP config file is written and admin steps are done. The Dataverse MCP
server will be started later — it's not needed for discovery or setup.

Read `src/skills/onboarding/step1b.md` and follow it.
