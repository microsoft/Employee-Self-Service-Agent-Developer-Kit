# FlightCheck Skill

Pre-deployment readiness validation for ESS agents. Runs automated checks
against the live environment (licenses, Entra, Power Platform, Workday/
ServiceNow/SAP integrations) and validates extracted agent files on disk.

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## Start

Read `.local/config.json` to confirm setup is complete and get the agent context.

If setup is not complete, show:

**Message:**

You need to run `/setup` first before running a readiness check.

**End message.**

Stop here.

If setup is complete, proceed.

---

## Step 1: Ask scope (optional)

Use `vscode_askQuestions`:

```json
[
  {
    "header": "Scope",
    "question": "What would you like to check?",
    "options": [
      { "label": "Full check", "description": "All categories — licenses, environment, auth, integrations, agent files, publishing", "recommended": true },
      { "label": "Workday only", "description": "Workday connections, flows, env vars, and SOAP workflow tests" },
      { "label": "ServiceNow only", "description": "ServiceNow connections, flows, template configs, and local topics" },
      { "label": "Local files only", "description": "Validate extracted topic files, agent config, variables" },
      { "label": "Prerequisites only", "description": "Licenses, roles, capacity" }
    ],
    "allowFreeformInput": false
  }
]
```

Map the selection to a scope flag:
- "Full check" → `full`
- "Workday only" → `workday`
- "ServiceNow only" → `servicenow`
- "Local files only" → `local`
- "Prerequisites only" → `prerequisites`

---

## Step 2: Run the check

**Message:**

Running readiness checks — this takes 1–3 minutes depending on scope...

**End message.**

Run in the terminal:

```
python scripts/flightcheck/cli.py --scope {SCOPE}
```

Wait for the script to finish.

`cli.py` automatically opens the HTML report (`workspace/flightcheck/report.html`)
in the user's default browser when it finishes. **Do not open it yourself** — a
second `webbrowser.open` / `Start-Process` would launch a duplicate tab pointing
at the same file. If the report does not appear (Codespaces, headless box, or
the user passed `--no-open`), tell them to open it manually from the file
explorer rather than spawning another tab from this skill.

---

## Step 3: Read results and present findings

Read `workspace/flightcheck/results.json`. Build the output below using the data.
You MUST follow this exact format every time. Do not improvise, add prose
between sections, or skip any section.

### 3a — Summary banner

Always show this first:

```
{VERDICT_EMOJI} **{VERDICT_TEXT}**

| | Count |
|---|---|
| ✅ Passed | {passed} |
| ❌ Failed | {failed} |
| ⚠️ Warnings | {warnings} |
| ℹ️ Not Configured | {not_configured} |
| **Total** | **{total}** |

*Completed in {duration_secs}s — [View full report](workspace/flightcheck/report.html)*
```

Where VERDICT_EMOJI and VERDICT_TEXT are:
- READY → ✅ and "Your agent is ready for deployment"
- READY_WITH_WARNINGS → ⚠️ and "Ready with warnings"
- NOT_READY → ❌ and "Issues found — not ready for deployment"

### 3b — Detailed results table

Show ALL results from the JSON — not just failures. This mirrors the
HTML report exactly. One row per result. Sort by: Failed first, then
Warning, then NotConfigured, then Passed.

```
| Checkpoint | Category | Priority | Status | Result | Remediation |
|---|---|---|---|---|---|
| {checkpoint_id} | {category} | {priority} | {status_emoji} {status} | {result} | {remediation or "—"} |
| ... | | | | | |
```

Status emoji mapping:
- Passed → ✅
- Failed → ❌
- Warning → ⚠️
- NotConfigured → ℹ️
- Skipped → ⏭️
- Error → 💥

### 3c — Offer to fix

After the table, analyze the failed and warning results and build a list
of things you CAN fix automatically vs. things that need manual action.

**Auto-fixable** (offer to do these right now):
- Compile errors in topics → run `/scan` skill
- Missing Workday/ServiceNow connection → run `/connect` skill
- Workday env vars not set → run `/connect workday` skill
- Workday connections in Error state → run `/connect workday` skill
- Disabled Workday/ServiceNow flows → enable via Dataverse MCP

**Needs manual action** (the Remediation column already contains direct links):
- License issues → links to M365 admin center
- Agent instructions/starter prompts/topics → links to Copilot Studio
- DLP policies → links to Power Platform admin center
- Publishing items → links to deployment docs

The Remediation column in the detailed results table already contains these
links. Do NOT repeat them in a separate list. Instead, after the table, just
show the auto-fixable offer (if any) and a brief note about manual items.

**If overall is "READY":**

Show:

```
No action needed. Run `/flightcheck` again anytime before publishing.
```

Stop here.

**If there are auto-fixable issues:**

Show:

```
I can fix some of these automatically. Want me to?

| # | Fix | What I'll do |
|---|-----|-------------|
| 1 | {description} | {what the skill will do} |
| 2 | {description} | {what the skill will do} |
| ... | | |

**Manual steps** (need your action):
- {issue}: {link to portal/docs}
```

Then use `vscode_askQuestions` to ask:

```json
[
  {
    "header": "AutoFix",
    "question": "Want me to fix the auto-fixable issues listed above?",
    "options": [
      { "label": "Yes — fix what you can", "recommended": true },
      { "label": "No — I'll handle it myself" }
    ],
    "allowFreeformInput": false
  }
]
```

**If they say yes**, execute each fix by reading and following the
appropriate skill file:
- Connection issues → read `src/skills/connect/SKILL.md` and follow it
- Compile errors → read `src/skills/cleanup/SKILL.md` and follow it
- Flow enablement → use Dataverse MCP to update flow state

After all auto-fixes complete, re-run flightcheck:

```
python scripts/flightcheck/cli.py --scope {SCOPE}
```

`cli.py` reopens the updated report in the browser automatically — **do not run
`Start-Process` or `webbrowser.open` yourself**, or the user will end up with
two tabs of the same report.

Then present the new results using the same format (3a → 3b → 3c).

**If they say no**, show:

```
No problem. Run `/flightcheck` again after making fixes.
```

**If there are NO auto-fixable issues (only manual):**

Show:

```
The issues above need manual action — follow the links in the Remediation column.

Run `/flightcheck` again after making changes.
```

**End of output. Stop here. Do not add commentary after this.**
