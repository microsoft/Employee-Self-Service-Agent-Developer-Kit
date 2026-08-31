# Step 1: Connect to Dataverse

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## 0.9 — Reuse the foundation environment

Run:

```text
python scripts/setup_state.py show --view report
```

Parse the printed state. If `connect_ready` is true and `environment.locked` is
true:

1. Set ENV_URL to `environment.tenant_endpoint`, stripping any trailing slash.
2. Do not list environments, ask how to provide an environment, or ask the
   maker to select it again.
3. Set FOUNDATION_REUSED to true.
4. Continue directly to section 1.2.

Only continue to section 1.0 when no completed foundation state with a locked
environment exists.

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

- **Script printed a table of environments → go to step 1.1a.**
- **Script failed with an auth/permission error → go to step 1.1c.**

---

## 1.1a — Ask the user to pick an environment

Build options from the script's environment table. Each row becomes an option
with `{environment name} — {URL}` as the label and the environment type as the
description. Including the URL in the label keeps duplicate display names
unambiguous.

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Select environment",
    "question": "Which environment is your ESS agent deployed in?",
    "options": [
      { "label": "{env 1 name} — {URL}", "description": "{type}" },
      { "label": "{env 2 name} — {URL}", "description": "{type}" }
    ],
    "allowFreeformInput": false
  }
]
```

Map the selected URL to the unique matching `instanceUrl` in
`ENVIRONMENT_LIST_JSON:` from the same script output.

---

## 1.1b — Use selection

Read the selected object's `instanceUrl` field. Save it as ENV_URL.
**Strip any trailing slash** from ENV_URL before using it (e.g.,
`https://org.crm.dynamics.com/` becomes `https://org.crm.dynamics.com`).

Go to step 1.2.

---

## 1.1c — Manual URL entry (fallback)

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Environment URL",
    "question": "What's your Power Platform environment URL? Example: `https://yourorg.crm.dynamics.com`. Find it in the Power Platform admin center."
  }
]
```

Save their answer as ENV_URL. **Strip any trailing
slash** from ENV_URL before using it (e.g., `https://org.crm.dynamics.com/`
becomes `https://org.crm.dynamics.com`).

## 1.2 — Configure MCP servers

Build the MCP URL by appending `/api/mcp` to ENV_URL. Double-check the
result has exactly ONE slash between the domain and `api` — for example
`https://org.crm.dynamics.com/api/mcp`, NOT `https://org.crm.dynamics.com//api/mcp`.

Run this command in the terminal without showing it to the user:

```powershell
python -m pip install -r src/mcp/agentconfig_landing_page/requirements.txt
```

If installation fails, show the error and stop.

Run:

```text
python scripts/mcp_config.py configure dataverse --environment-url "{ENV_URL}"
```

If configuration fails, show the exact error and stop. The command preserves
every other server, input, and top-level field in `.vscode/mcp.json`.

If FOUNDATION_REUSED is true, do not rerun the Allowed MCP Client prerequisite;
it already passed in foundation `SETUP-02.2`. Continue directly to section 1.3.

Check the server-side Allowed MCP Client record:

```text
python scripts/check_dataverse_mcp.py --url "{ENV_URL}"
```

Parse `DATAVERSE_MCP_STATUS_JSON:`:

- If `status` is `enabled`, continue immediately to section 1.3 without asking
  the user.
- If `status` is `disabled` or `missing`, show the Power Platform admin center
  steps below and ask only whether to **Check again**:
  1. Open [Power Platform admin center](https://admin.powerplatform.microsoft.com/environments).
  2. Select the `{ENVIRONMENT_NAME}` environment.
  3. Open `Settings` → `Product` → `Features`.
  4. Turn on **Allow MCP clients to interact with Dataverse MCP server**.
  5. Open `Advanced Settings`.
  6. Open **Microsoft GitHub Copilot** and set `Is Enabled` to `Yes`.
  7. Choose `Save & Close`, then select **Check again** here.
- If the command fails, show its exact error and stop. Do not ask the user to
  attest that the setting is enabled.

## 1.3 — Proceed to agent discovery

The MCP config file is written and admin steps are done. The Dataverse MCP
server will be started later — it's not needed for discovery or setup.

Read `src/skills/onboarding/step1b.md` and follow it.
