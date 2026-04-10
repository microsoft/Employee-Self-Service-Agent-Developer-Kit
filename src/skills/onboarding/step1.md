# Step 1: Connect to Dataverse

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## 1.1 — Ask for the environment URL

**Message:**

What's the URL of your Power Platform environment?

It looks like `https://yourorg.crm.dynamics.com`. You can find it in the
[Power Platform admin center](https://admin.powerplatform.microsoft.com)
under your environment's details.

**End message.**

Wait for the user to respond. Save their URL as ENV_URL. **Strip any trailing
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
