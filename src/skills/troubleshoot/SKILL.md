# Troubleshoot Connectivity and Authentication Issues

Diagnostic skill for resolving ESS agent connectivity failures with external
systems (Workday, ServiceNow, SAP). Read-only — no file mutations, no
checkpoint required.

## Rules

- This skill is **read-only diagnostic guidance**. Do NOT modify agent files,
  run scripts, or create checkpoints.
- Do NOT narrate your internal process. Say "Let me help you diagnose this"
  not "I'm loading the troubleshooting reference doc."
- **Before starting diagnosis**, suggest running `/flightcheck` first if the
  user hasn't recently. FlightCheck's automated checks often surface the root
  cause faster than manual walkthrough. If the user says they already ran it,
  ask them to share the results from `my/flightcheck/results.json`.
- Track progress with todos if the diagnosis spans multiple configs.
- Always read the relevant reference doc BEFORE presenting guidance — do not
  guess or paraphrase from memory.
- Present one config at a time. Ask the user to confirm pass/fail before
  moving to the next config.
- If the user pastes an error message, match it against the Error String table
  first to narrow the search.

---

## Step 1: Identify the Integration and Read Config

Read `my/config.json` to determine:
- Which agent is active (the `agent.folder` field)
- Which integrations are configured

Ask the user which integration is failing if it's not obvious from their
message. Currently supported troubleshooting guides:

| Integration | Reference Doc |
|-------------|--------------|
| Workday | `src/reference/ess-docs/integrations/workday-isu-debugging.md` |

If the integration doesn't have a dedicated debugging guide, fall back to:
- `src/reference/ess-docs/integrations/{integration}.md` (general setup doc)
- `src/reference/ess-docs/operations/known-issues-limitations.md` (known platform issues)

---

## Step 2: Gather the Symptom

Ask the user to describe the problem. Specifically ask:

1. **What error message do you see?** (exact text if possible)
2. **Who is affected?** (makers only, end users only, or everyone)
3. **When did it start?** (always broken, worked before, intermittent)
4. **Did anything change recently?** (password rotation, config update, new environment)

If the user provides an error string, proceed directly to Step 3.
If the user describes a symptom without an error string, use the
**Symptom → Config Mapping** table from the reference doc to identify
which configs to check.

---

## Step 3: Read the Reference Doc and Match

Read the debugging reference doc identified in Step 1. For Workday:

```
src/reference/ess-docs/integrations/workday-isu-debugging.md
```

Use the **Quick Reference** section at the top of the doc to match:

1. **Error String → Config Mapping table**: If user provided an error string,
   find the matching row. Note the "Configs to Check" column.
2. **Symptom → Config Mapping table**: If user described a symptom, find the
   matching row. Note the "Start Here" column.
3. **Diagnostic Decision Tree**: If neither table matches clearly, walk through
   the numbered decision tree with the user.

---

## Step 4: Walk Through Configs One at a Time

For each config identified in Step 3, present to the user:

1. **Config name and what it is** (one sentence)
2. **The check steps** (numbered list from the config's "Check" section)
3. **Expected values** (from the "Values" table)

Then ask: **"Does this check pass or fail?"**

- If **fail** → present the **Fix** steps. Then ask if they want to proceed
  to the Auth Reset Guide (to clear caches after the fix).
- If **pass** → move to the next config in the list.
- If **all pass** → proceed to Step 5.

---

## Step 5: Auth Reset or Escalation

If the user found and fixed a config issue:

1. Read the **Authentication Reset Guide** section of the reference doc
2. Walk the user through the 7-step layer-by-layer reset checklist
3. Emphasize: **test with a non-maker user** in BizChat, not just Copilot
   Studio test pane

If all configs pass and the issue persists:

1. Read the **Collecting Traces for Escalation** section
2. Guide the user through the **Postman Verification Tests** first — these
   isolate whether the issue is in credentials/config or in the Power Platform
   connector
3. If Postman tests pass, guide collection of the full escalation package
   (HAR trace, flow run details, SAML assertion, etc.)
4. Present the **Escalation Package Checklist** and help the user compile all
   12 items before contacting support

---

## Step 6: Summary

After diagnosis is complete (whether fixed or escalated), summarize:

- **Root cause** (or "unable to determine — escalation package prepared")
- **What was changed** (if anything)
- **What was verified** (which configs passed/failed)
- **Next steps** (test with end users, contact support, monitor for recurrence)
