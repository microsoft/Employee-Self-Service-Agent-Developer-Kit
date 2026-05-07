# ServiceNow Step 2: OAuth2 Setup

**This file is ONLY for OAuth2 authentication. Do not use for Basic or Entra.**

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "REDIRECT_URL = ..." or "CLIENT_SECRET = ..." in chat.

Read `my/connect/servicenow/config.json` for INSTANCE_NAME.

---

## 2.1 — Ask Power Platform region

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Power Platform region",
    "question": "Which Power Platform region is your environment in? Check in the Power Platform admin center → your environment → details.",
    "options": [
      { "label": "United States", "recommended": true },
      { "label": "Europe" },
      { "label": "Asia Pacific" },
      { "label": "Australia" },
      { "label": "United Kingdom" },
      { "label": "Japan" },
      { "label": "Canada" },
      { "label": "India" },
      { "label": "I'm not sure" }
    ],
    "allowFreeformInput": false
  }
]
```

Map their choice to a redirect URL:

| Choice | Redirect URL |
|--------|-------------|
| 1 (US) | `https://unitedstates-002.consent.azure-apim.net/redirect` |
| 2 (Europe) | `https://europe-002.consent.azure-apim.net/redirect` |
| 3 (Asia) | `https://asia-002.consent.azure-apim.net/redirect` |
| 4 (Australia) | `https://australia-002.consent.azure-apim.net/redirect` |
| 5 (UK) | `https://unitedkingdom-002.consent.azure-apim.net/redirect` |
| 6 (Japan) | `https://japan-002.consent.azure-apim.net/redirect` |
| 7 (Canada) | `https://canada-002.consent.azure-apim.net/redirect` |
| 8 (India) | `https://india-002.consent.azure-apim.net/redirect` |
| 9 (Not sure) | `https://unitedstates-002.consent.azure-apim.net/redirect` |

Save the redirect URL as REDIRECT_URL.

If the user chose 9 ("Not sure"), note that we're defaulting to US. If
it turns out wrong, step 3 has a fallback to fix the redirect URL
from the error page.

---

## 2.2 — Generate a client secret

Generate a 32-character random hex string by running this in the terminal
(do not show this command or its output to the user):

```
python -c "import secrets; print(secrets.token_hex(16))"
```

Save the output as CLIENT_SECRET.

**Pre-step:** Write the generated value to an environment variable so
the ServiceNow MCP server can read it without the secret crossing the
MCP tool boundary. In the SAME VS Code terminal where the ServiceNow
MCP server runs (or restart the MCP after setting it):

```
$env:SERVICENOW_OAUTH_CLIENT_SECRET = "{CLIENT_SECRET}"
```

**Why pre-generate?** The ServiceNow API masks auto-generated secrets
(returns encrypted gibberish). By passing a known value during creation,
we avoid a manual step where the user has to open the ServiceNow UI to
reveal the secret. The user will copy this value directly from chat
into Copilot Studio.

**Why env var?** The ServiceNow MCP server takes the env var NAME, not
the secret value, so the secret never appears in MCP logs or LLM context.

---

## 2.3 — Create the OAuth application via MCP

**Message:**

I'm going to create an OAuth application called **ESS Copilot** in your
ServiceNow instance. This enables the Power Platform connector to
authenticate users when they interact with the agent.

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Create OAuth app",
    "question": "OK to create the OAuth application in ServiceNow?",
    "options": [
      { "label": "Create it", "recommended": true },
      { "label": "I'll do it manually" }
    ],
    "allowFreeformInput": false
  }
]
```

**If the user chose "I'll do it manually":**

**Message:**

No problem. In ServiceNow:

1. Go to **System OAuth** → **Application Registry**
2. Click **New** → **Create an OAuth API endpoint for external clients**
3. Set:
   - **Name**: `ESS Copilot`
   - **Redirect URL**: `{REDIRECT_URL}`
   - **Client Secret**: `{CLIENT_SECRET}`
4. Click **Submit**

Copy the **Client ID** from the new record and paste it here.

**End message.**

Wait for the user to provide CLIENT_ID. Save the value and skip to 2.4.

**If the user chose "Create it":**

**Message (do NOT wait for user response — continue immediately):**

Creating the OAuth application...

**End message.**

Call the ServiceNow MCP `register_oauth_application` tool:

- `name`: `"ESS Copilot"`
- `client_id`: `""` (empty — ServiceNow auto-generates)
- `client_secret_env_var`: `"SERVICENOW_OAUTH_CLIENT_SECRET"` (the env var you set in 2.2)
- `redirect_url`: `"{REDIRECT_URL}"` (the value from 2.1)
- `grant_type`: `"authorization_code"`
- `comments`: `"OAuth endpoint for ESS Copilot agent — Power Platform connector"`

The response contains the auto-generated `client_id` and the `sys_id` of
the new record. Save:
- CLIENT_ID = the `client_id` from the response
- OAUTH_SYS_ID = the `sys_id` from the response

**If the call fails:**

**Message:**

Something went wrong creating the OAuth application:

{paste the error message}

Common causes:
- The ServiceNow MCP server isn't running — check with
  **Ctrl+Shift+P** → **MCP: List Servers**
- The admin account doesn't have permission to create OAuth apps
- The instance may have API restrictions

Type **retry** to try again.

**End message.**

Wait for the user and retry from 2.3.

---

## 2.4 — Update token lifespans

Call the ServiceNow MCP `update_record` tool:

- `table`: `"oauth_entity"`
- `sys_id`: `"{OAUTH_SYS_ID}"`
- `data`: `"{\"access_token_lifespan\": \"43200\", \"refresh_token_lifespan\": \"31536000\"}"`

This sets:
- Access token: 43,200 seconds (12 hours) — default is 1,800 (30 min)
- Refresh token: 31,536,000 seconds (1 year) — default is 8,640,000 (100 days)

If this call fails, log the error but continue — it's not blocking.

---

## 2.5 — Save config and display results

Update `my/connect/servicenow/config.json` — add an `oauth` object:

```json
{
  "oauth": {
    "clientId": "{CLIENT_ID}",
    "sysId": "{OAUTH_SYS_ID}",
    "redirectUrl": "{REDIRECT_URL}"
  }
}
```

Do NOT store the client secret in config.json.

Update `my/connect/servicenow/tasks.md` — change step 2 from
`- [ ]` to `- [x]`.

**Message:**

✅ OAuth application created in ServiceNow.

| # | Task | Status |
|---|------|--------|
| 1 | Instance configured | ✅ |
| 2 | Connection secured | ✅ |
| 3 | Extension installed | ⬜ |
| 4 | Connection verified | ⬜ |

Here are the values you'll need for the next step:

| Field | Value |
|-------|-------|
| **Authentication Type** | `OAuth2` |
| **Instance Name** | `{INSTANCE_NAME}` |
| **Client ID** | `{CLIENT_ID}` |
| **Client Secret** | `{CLIENT_SECRET}` |

Ready to install the integration in Copilot Studio? Type **go** to continue.

**End message.**

Wait for the user. Then read `src/skills/connect/servicenow/step3-oauth2.md`
and follow it.
