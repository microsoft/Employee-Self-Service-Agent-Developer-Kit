# ServiceNow Step 4: Verify Connection

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "ENV_URL = ..." or "BOT_ID = ..." in chat.

Read `my/connect/servicenow/config.json` for INSTANCE_NAME, SNOW_USAGE, etc.
Read `my/config.json` for the agent details (dataverseEndpoint, agent.botId,
agent.name, agent.schemaName, agent.isManaged).

---

## 4.1 — Re-extract the agent

**Message (do NOT wait for user response — continue immediately):**

Re-extracting your agent to pull in the new ServiceNow components.
This takes about 10–20 seconds...

**End message.**

Read `my/config.json` to get the agent details. Set:
- ENV_URL = `dataverseEndpoint`
- BOT_ID = `agent.botId`
- BOT_NAME = `agent.name`
- SCHEMA_NAME = `agent.schemaName`
- IS_MANAGED = `agent.isManaged`

Run this command in the terminal:

```
python scripts/fetch_and_setup.py --url "{ENV_URL}" --bot-id "{BOT_ID}" --name "{BOT_NAME}" --schema "{SCHEMA_NAME}" {--managed if IS_MANAGED is true}
```

Wait for the script to complete. Check the output for:
- **Template configs fetched** — should be greater than 0
- **Topics** — should include new ServiceNow topics

---

## 4.2 — Evaluate the results

### If template configs > 0 AND new ServiceNow topics are visible

Update `my/connect/servicenow/tasks.md` — change step 4 from
`- [ ]` to `- [x]`.

Update `my/connect/servicenow/config.json` — set `"status": "connected"`.

Update `my/config.json` — add or update a `connections` object:

```json
{
  "connections": {
    "ServiceNow": {
      "instanceName": "{INSTANCE_NAME}",
      "instanceUrl": "https://{INSTANCE_NAME}.service-now.com",
      "usage": "{SNOW_USAGE}",
      "authType": "{SNOW_AUTH}",
      "connectedAt": "{current ISO date}"
    }
  }
}
```

Count the new ServiceNow-related topics from the script output.

**Message:**

✅ Connection verified!

| # | Task | Status |
|---|------|--------|
| 1 | Instance configured | ✅ |
| 2 | Connection secured | ✅ |
| 3 | Extension installed | ✅ |
| 4 | Connection verified | ✅ |

{paste the script's summary output here}

Your agent now has ServiceNow capabilities. Here's what you can do next:

| Command | What it does |
|---------|-------------|
| `/create` | Create a new topic that uses ServiceNow |
| `/scan` | Check your agent for any errors |
| `/menu` | See all available commands |

**End message.**

Stop here.

### If template configs = 0 OR no new topics

**Message:**

The extension pack installed, but I'm not seeing the expected ServiceNow
components yet. This can happen if the install is still processing.

Try these steps:

1. Go to [Copilot Studio](https://copilotstudio.microsoft.com/)
2. Open your ESS agent → **Settings** → **Customize**
3. Check that the ServiceNow extension shows as **Installed**
4. Wait a minute, then come back here and type **retry**

**End message.**

Wait for the user. When they say retry, go back to section 4.1 and
re-run the extraction.

If it fails a second time:

**Message:**

The ServiceNow components still aren't showing up. This might need
troubleshooting. Try:

1. In Copilot Studio, go to **Topics** and search for "ServiceNow" — do
   you see any ServiceNow topics listed?
2. If yes, the extension is installed but the extraction might need a
   different approach. Type `/scan` to check for issues.
3. If no, the extension pack may not have installed correctly. Try
   uninstalling and reinstalling it from **Settings → Customize**.

**End message.**

Stop here.
