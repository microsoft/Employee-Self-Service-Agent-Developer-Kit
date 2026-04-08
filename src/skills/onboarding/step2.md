# Step 2: Extract and Configure

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

You should already have these values from Step 1: ENV_URL, BOT_ID, BOT_NAME,
SCHEMA_NAME, IS_MANAGED.

---

## 2.1 — Fetch components and run setup

Run this single command in the terminal (substitute all values):

```
python scripts/fetch_and_setup.py --url "{ENV_URL}" --bot-id "{BOT_ID}" --name "{BOT_NAME}" --schema "{SCHEMA_NAME}" {--managed if IS_MANAGED is true}
```

The script authenticates to Dataverse via the browser (the user will see an
account picker), fetches all components and template configs via the REST API,
and runs setup.py automatically. No MCP queries needed.

If the script fails with an auth error, tell the user to check they selected
the correct account with access to the environment, and re-run the command.

## 2.2 — Finish

Update `my/onboarding/tasks.md` — change step 3 from `- [ ]` to `- [x]`.

Show this message, pasting the script's terminal output where indicated:

**Message:**

✅ Setup complete!

| # | Task | Status |
|---|------|--------|
| 1 | Dataverse MCP connected | ✅ |
| 2 | Agent discovered | ✅ |
| 3 | Setup complete | ✅ |

{paste the script's summary output here}

Here's what you can do next:

| Command | What it does |
|---------|-------------|
| `/scan` | Scan your agent for compile errors and fix them |
| `/create` | Create a new topic or workflow |
| `/menu` | See all available commands |

Or just describe what you need in plain English.

**End message.**

Stop here. Do not continue.
