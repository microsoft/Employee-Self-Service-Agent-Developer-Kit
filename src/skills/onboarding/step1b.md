# Step 1b: Discover Agent

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

You should already have ENV_URL from Step 1.

---

## 1.4 — Run the discovery script

Run this command in the terminal (substitute ENV_URL):

```
python scripts/discover.py --url "{ENV_URL}"
```

A browser window will open for sign-in. Wait for the script to finish.

**Check the terminal output:**

- **Script printed a table of agents → go to step 1.5.**
- **Script printed "No agents found" → go to step 1.8.**
- **Script failed with an auth/connection error → go to step 1.9.**

---

## 1.5 — Ask the user to pick an agent

**Message:**

Here are the agents in your environment:

{paste the agent table from the script output}

Which one do you want to customize? Enter the number.

**End message.**

Wait for the user to respond with a number.

---

## 1.6 — Confirm selection

Run the selection command in the terminal:

```
python scripts/discover.py --url "{ENV_URL}" --select {NUMBER}
```

Find the line starting with `SELECTED_AGENT_JSON:` in the output. Parse the
JSON after the colon to get BOT_ID (`botid`), BOT_NAME (`name`),
SCHEMA_NAME (`schemaname`), and IS_MANAGED (`ismanaged`).

Update `my/onboarding/tasks.md` — change both step 1 and step 2 from
`- [ ]` to `- [x]`.

**Message:**

✅ Selected **{BOT_NAME}**.

| # | Task | Status |
|---|------|--------|
| 1 | Dataverse configured | ✅ |
| 2 | Agent discovered | ✅ |
| 3 | Agent extracted | ⬜ |
| 4 | MCP server started | ⬜ |

Extracting your agent now. This takes a few seconds...

**End message.**

Now read `src/skills/onboarding/step2.md` and follow it.

---

## 1.8 — No agents found

**Message:**

✅ Connected to Dataverse, but no agents found in this environment. Make sure
your ESS agent is installed in Copilot Studio before running setup.

Once installed, run `/setup` again.

**End message.**

**STOP. Do not continue.**

---

## 1.9 — Script failed

**Message:**

The discovery script couldn't connect. Let's troubleshoot:

1. Check that the environment URL is correct
   (`https://yourorg.crm.dynamics.com`, not `.api.` or `make.powerapps.com`).
2. Confirm the admin steps: MCP feature flag **ON** in Power Platform admin
   center, and **Microsoft GitHub Copilot** client **enabled** in Advanced
   Settings.
3. Make sure your account has read access to the environment.

Type **retry** when ready, or run `/setup` again after fixing.

**End message.**

Wait for the user. When they say retry, go back to step 1.4 and re-run the
discovery script.
