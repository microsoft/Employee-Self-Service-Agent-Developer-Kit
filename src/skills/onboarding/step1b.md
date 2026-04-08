# Step 1b: Verify Connection and Discover Agent

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

You should already have ENV_URL from Step 1.

**IMPORTANT — Do NOT give up.** This step verifies the Dataverse MCP
connection. You have THREE different ways to confirm it works (Attempt A,
B, and C below). Try ALL of them before telling the user there's a problem.
The server IS likely running — tool discovery is what fails on some models.

---

## FIRST ACTION — DO THIS NOW

**Before reading anything else, execute this tool call RIGHT NOW:**

Call `tool_search_tool_regex` with `pattern` = `dataverse` and `limit` = `10`.

Read the result. If it returned tools whose names start with `mcp_dataverse_`,
the tools are loaded — skip to step 1.4b (smoke test) below.

If it returned nothing or errored, continue reading the guardrails and
Attempt B / C below.

---

## 1.4b — Smoke test (run immediately after ANY successful attempt)

Call `mcp_dataverse_describe_table` with `tablename` = `bot`.

Did it return column definitions (like `botid`, `name`, `schemaname`)?
- **Yes → go to step 1.5.**
- **Error about authentication/permissions → go to step 1.9.**
- **Error saying "tool not found" → tools didn't actually load. Continue to Attempt B.**

---

## GUARDRAILS — Read these BEFORE executing any remaining steps

**MANDATORY: You MUST follow Attempts A → B → C in exact order.**

1. **NEVER skip Attempt A.** Attempt A calls `tool_search_tool_regex` — this
   is what LOADS the deferred MCP tools into your session. Without it, later
   tool calls may fail. You MUST call it even if you think tools are already
   available.

2. **NEVER call a tool that is not listed in your available tools.** The ONLY
   tools you may call in this file are:
   - `tool_search_tool_regex` (Attempts A and B)
   - `mcp_dataverse_describe_table` (Step 1.4b smoke test and Attempt C)
   - `mcp_dataverse_read_query` (Step 1.5 — only after an attempt succeeds)
   If a tool name is not in that list, DO NOT call it. Do NOT invent tool
   names. Do NOT call tools like `activate_*`, `enable_*`, or any name you
   have not seen returned by a previous tool call.

3. **NEVER use fallback paths that are not in this file.** Do NOT call Azure
   CLI (`az`), PAC CLI (`pac`), `Invoke-RestMethod`, `curl`, or any other
   terminal command to verify or query Dataverse. The ONLY verification paths
   are Attempts A, B, and C below.

4. **When an attempt SUCCEEDS, go to step 1.5 IMMEDIATELY.** Do not run
   additional checks. Do not try "just to be sure." If `describe_table`
   returns column definitions, the server works — proceed to 1.5.

5. **If you are unsure whether a tool call succeeded, re-read its output.**
   A response containing column names like `botid`, `name`, `schemaname` is
   SUCCESS. An error message containing "not found" or "unknown tool" is
   FAILURE. Do not confuse the two.

---

## 1.4 — Confirm Dataverse tools are available

Try each attempt in order. Stop as soon as ONE succeeds.

### Attempt A — Search for tools (MANDATORY FIRST STEP)

**You MUST start here. Do NOT skip to Attempt B or C.**

If you already ran `tool_search_tool_regex` in the FIRST ACTION block above
and it returned `mcp_dataverse_` tools, you already completed Attempt A.
Go to step 1.4b (smoke test) if you haven't run it yet, or step 1.5 if
the smoke test passed.

Otherwise, call `tool_search_tool_regex` with these EXACT parameters:
- `pattern`: `dataverse`
- `limit`: `10`

Did it return ANY tools with names starting with `mcp_dataverse_`?
- **Yes → go to step 1.4b (smoke test).** Do NOT skip the smoke test.
- **No or error → try Attempt B.**

### Attempt B — Search with a broader pattern

Call `tool_search_tool_regex` with these EXACT parameters:
- `pattern`: `mcp_dataverse`
- `limit`: `10`

Did it return tools?
- **Yes → go to step 1.5.**
- **No or error → try Attempt C.**

### Attempt C — Call Dataverse directly (skip search)

The tools may already be loaded even if search failed. Try calling one.

Call `mcp_dataverse_describe_table` with this EXACT parameter:
- `tablename`: `bot`

Did it return column definitions (like `botid`, `name`, `schemaname`)?
- **Yes → the server IS connected. Go to step 1.5.**
- **Error saying "tool not found" or "unknown tool" → go to step 1.6** (tools genuinely not loaded).
- **Error about authentication/permissions → go to step 1.9** (tools loaded but server has an issue).

> **Note:** If you already ran this same call as the 1.4b smoke test above
> and it succeeded, go directly to step 1.5. Do NOT re-run it.

---

## 1.5 — Query for agents

Dataverse tools are confirmed available. Now query for agents.

Call `mcp_dataverse_read_query` with this EXACT parameter:
- `querytext`: `SELECT TOP 20 botid, name, ismanaged, schemaname FROM bot`

Do NOT pass `tablename`. Do NOT pass `item`. Only `querytext`.

**Check the result:**

- **Got agent rows → go to step 1.7.**
- **Got rows but the list is empty → go to step 1.8.**
- **Got an error → go to step 1.9.**

---

## 1.6 — Tools not available (ONLY after Attempts A, B, AND C all failed)

**Message:**

I couldn't detect the Dataverse MCP tools after multiple checks. The server
may not be registered with VS Code yet. Let's verify:

1. Press **Ctrl+Shift+P** → **MCP: List Servers** → check Dataverse shows
   as **Running**. If it shows Running, try **Stop** then **Start** again.
2. Check the **Output** panel → select **Dataverse** from the dropdown.
   Look for errors.
3. Verify `.vscode/mcp.json` has the correct URL
   (`https://yourorg.crm.dynamics.com`, not `.api.` or `make.powerapps.com`).

Type **retry** when ready, or run `/setup` again after fixing.

**End message.**

Wait for the user to respond. Then **go back to step 1.4** (starting from
the FIRST ACTION block) and try all three attempts again. If ANY attempt
succeeds, continue to step 1.5.

If ALL attempts fail again, show the same troubleshooting message above
and wait for the user. **There is no hard limit on retries.** Every time
the user says "retry", "try again", or asks to continue, go back to
step 1.4 and run all three attempts again. The user may need time to
restart the MCP server or fix admin settings between attempts.

---

## 1.7 — Agents found (success)

Update `my/onboarding/tasks.md` — change BOTH step 1 and step 2 from
`- [ ]` to `- [x]`. Then show:

**Message:**

✅ Connected to Dataverse.

Here are the agents in your environment:

| # | Agent Name | Schema Name |
|---|-----------|-------------|
{one numbered row per result}

Which one do you want to customize? Enter the number.

**End message.**

Wait for the user to pick. Save the selected agent's botid (BOT_ID), name
(BOT_NAME), schemaname (SCHEMA_NAME), and ismanaged flag (IS_MANAGED).

Then show:

**Message:**

✅ Selected **{BOT_NAME}**.

| # | Task | Status |
|---|------|--------|
| 1 | Dataverse MCP connected | ✅ |
| 2 | Agent discovered | ✅ |
| 3 | Setup complete | ⬜ |

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

## 1.9 — Query failed (tools loaded but query errored)

**Message:**

The Dataverse server is connected but the query failed. Let's troubleshoot:

1. Check the **Output** panel → select **Dataverse** from the dropdown.
   Look for error details.
2. Confirm the admin steps: MCP feature flag **ON** in Power Platform admin
   center, and **Microsoft GitHub Copilot** client **enabled** in Advanced
   Settings.
3. Make sure your account has read access to the environment.

Type **retry** when ready, or run `/setup` again after fixing.

**End message.**

Wait for the user to respond. Then **go back to step 1.5** (try the query
again). If it succeeds, go to step 1.7.

If the query fails again on this second attempt, show:

**Message:**

Still getting query errors. See `src/reference/ess-docs/operations/known-issues-limitations.md` for detailed
troubleshooting steps. Run `/setup` again after fixing the issue.

**End message.**

**STOP. Do not continue.**
