# Step 2: Extract, Configure, and Start MCP

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

You should already have these values from Step 1: ENV_URL, BOT_ID, BOT_NAME,
SCHEMA_NAME, IS_MANAGED.

---

## 2.1 — Fetch components and run setup

**Message (do NOT wait for user response — continue immediately):**

Extracting your agent — this usually takes 10–20 seconds...

**End message.**

Run this single command in the terminal (substitute all values):

```
python scripts/fetch_and_setup.py --url "{ENV_URL}" --bot-id "{BOT_ID}" --name "{BOT_NAME}" --schema "{SCHEMA_NAME}" {--managed if IS_MANAGED is true}
```

The script authenticates to Dataverse via the browser (the user will see an
account picker), fetches all components and template configs via the REST API,
and runs setup.py automatically. No MCP queries needed.

If the script fails with an auth error, tell the user to check they selected
the correct account with access to the environment, and re-run the command.

When the script completes successfully, update `my/onboarding/tasks.md` —
change step 3 from `- [ ]` to `- [x]`.

**Message:**

✅ Agent extracted.

{paste the script's summary output here}

One more step — we need to start the Dataverse MCP server so the kit can
work with your environment going forward.

| # | Task | Status |
|---|------|--------|
| 1 | Dataverse configured | ✅ |
| 2 | Agent discovered | ✅ |
| 3 | Agent extracted | ✅ |
| 4 | MCP server started | ⬜ |

**End message.**

---

## 2.2 — Start the Dataverse MCP server

**Message:**

Start the Dataverse MCP server:

1. Press **Ctrl+Shift+P** → type **MCP: List Servers** → select it
2. Click **Dataverse** → click **Start**
3. Sign in with your Microsoft account when the browser opens

Type **done** when Dataverse shows as Running.

**End message.**

Wait for the user to respond.

---

## 2.3 — Finish

Update `my/onboarding/tasks.md` — change step 4 from `- [ ]` to `- [x]`.

**Message:**

✅ Setup complete!

| # | Task | Status |
|---|------|--------|
| 1 | Dataverse configured | ✅ |
| 2 | Agent discovered | ✅ |
| 3 | Agent extracted | ✅ |
| 4 | MCP server started | ✅ |

Here's what you can do next:

| Command | What it does |
|---------|-------------|
| `/scan` | Scan your agent for compile errors and fix them |
| `/create` | Create a new topic or workflow |
| `/menu` | See all available commands |

Or just describe what you need in plain English.

**End message.**

Stop here. Do not continue.
