# Cleanup Skill

This skill scans a cloned ESS agent for compile errors and walks the user through fixing them.

Distinguish local fixes from changes pushed to the agent. Use the normal topic
update or delete owner for approved changes and the general Push prompt for
a selected batch. Carry scoped approval forward without repeating it.

## Rules

- Before proposing or applying topic-file fixes or deletions, read and apply **Authoring policy for this release** in [the shared topic contract](../topics/experience-contract.md). Carry protected or unresolved items into the report as unchanged with their reason, not as fixed; continue read-only scanning and independently eligible work.
- Do NOT run terminal commands or scripts EXCEPT the kit's own helper scripts under `scripts/`, including the selected topic owner's preview and approved execution commands. For everything else - file edits, validation, lookups - use your built-in file reading, writing, and editing tools only. Do NOT use Python, PowerShell, Node.js, or any other scripting language to do work the editing tools can do.
- Do NOT fix errors automatically without user confirmation. Present each group of errors and ask the user before making changes.
- Do NOT modify the source template files in `src/`. Only modify files inside the agent folder (the cloned agent at the workspace root).
- After fixing errors, re-scan to verify the fix worked. Show the updated error count.
- **Communication**: Follow the communication rules in `copilot-instructions.md`. Do NOT mention patches, deltas, diagnostics tools, stale caches, skill files, or any internal terminology. Speak in plain terms: "Fixing...", "Fixed.", "Scanning again...", "X errors remaining."
- **Pending verification**: Preserve a completed edit without repeatedly applying it when diagnostics have not refreshed. Report the edit and verification state separately; do not count an unconfirmed diagnostic result as resolved.
- **TRACK PROGRESS**: Use the todo list tool to track your progress through this skill's steps. Create a todo list at the start with all the steps, mark each in-progress as you start it, and mark completed when done.

## Step 1: Read Config

Read `.local/config.json` to get the agent details:

- `agent.folder` — the name of the cloned agent folder (e.g., `Employee Self-Service HR`)
- `agent.slug` — the slugified name (e.g., `employee-self-service-hr`)

If `.local/config.json` doesn't exist or doesn't have `agent.folder`, tell the user: "I can't find your agent configuration. Run `/setup` first." Then STOP.

## Step 2: Quick Scan (before checkpoint)

Before asking the user to checkpoint, do a **quick pre-scan** to see if
there are any errors at all. Gather errors from both sources described in
Step 3 below (VS Code Problems panel + agent folder scan), merge and
deduplicate.

If the error count is **zero**, skip the checkpoint entirely and jump
straight to Step 6 (Final Report) with 0 errors before / 0 fixed / 0
remaining. Do NOT ask the user to confirm a checkpoint — there's nothing
to fix.

If the error count is **greater than zero**, continue to Step 2b.

## Step 2b: Checkpoint

Tell the user:

> "I found {count} errors. Before making any changes, I'll save a checkpoint of your agent files. This way you can always restore them if needed. **Ready to proceed?**"

Wait for the user to confirm.

When confirmed:

- Run in the terminal: `python scripts/checkpoint.py "pre-scan-fixes"`
- This saves a full snapshot of all working files before any modifications.
- Record anonymous usage telemetry (best-effort, non-blocking — no user-facing
  message, and it never fails the step): `python scripts/emit_capability.py cleanup`
- Tell the user: "Checkpoint saved. Let me walk you through the fixes."

## Step 3: Scan for Errors (detailed categorization)

Gather errors from TWO sources and combine them into a single list:

1. **VS Code Problems panel** — Use the error/diagnostics tool with NO file path filter (get all errors across the workspace). Filter the results to only include errors from files inside `{agent.folder}/`.
2. **Agent folder scan** — Use the error/diagnostics tool specifically on `{agent.folder}/`.

Merge both lists and deduplicate (the same error may appear in both). Use the combined list for the rest of this flow.

After scanning, group the errors into these categories:

### Category 1: ModelDescription Too Long

**Error message**: `Property 'ModelDescription' exceeds maximum length of 1024 characters`
**What it means**: The topic's `modelDescription` field (under `beginDialog`) is longer than 1024 characters, which Copilot Studio doesn't allow.
**Fix**: Truncate or rewrite the `modelDescription` to fit within 1024 characters while preserving the key intent information.

### Category 2: Missing CloudFlow

**Error message**: `CloudFlow with id '{guid}' not found`
**What it means**: The topic references a Power Automate workflow (via `InvokeFlowAction` with a `flowId`) that wasn't included in the clone. This usually happens with add-on workflows (ADP, D365, password reset, catalog) that aren't part of the core ESS package.
**Fix options**:

- **Review topic deletion**: Use the delete owner to assess eligibility, effects and local-only versus pushed deletion. A missing workflow in local extraction does not establish its absence at runtime.
- **Skip**: Leave it unchanged and report the unresolved error and any known impact.

### Category 3: Missing Dialog Reference

**Error message**: `Dialog with id '{schema}.topic.{name}' not found`
**What it means**: The topic references another topic using a `BeginDialog` action, but the schema name in the reference is wrong. Common cause: truncated schema name (e.g., `msdyn_copilotforemployeeselfservice` instead of `msdyn_copilotforemployeeselfservicehr`).
**Fix**: Look at the incorrect dialog reference. Read `.local/config.json` to get the correct `agent.schemaName`. Replace the wrong schema prefix with the correct one. For example, if the error says `msdyn_copilotforemployeeselfservice.topic.WorkdayManagerCheck` and the correct schemaName is `msdyn_copilotforemployeeselfservicehr`, replace `msdyn_copilotforemployeeselfservice` with `msdyn_copilotforemployeeselfservicehr` in the file.

### Unknown Errors

If you find errors that don't match any of the above categories, list them separately and tell the user: "I found some errors I don't have an automatic fix for. Here's what they are:" Then list them and suggest the user check the Copilot Studio documentation.

## Step 4: Present Summary

Show the user a summary table:

```text
I found {total} errors across {file_count} files:

| Error Type | Files Affected | Fix |
|-----------|---------------|-----|
| ModelDescription too long | {count} topics | Truncate to fit 1024-char limit |
| Missing CloudFlow | {count} topics | Delete topic or skip |
| Missing Dialog reference | {count} topics | Correct the schema name |
```

Then say: "Let's walk through each file. I'll explain what's wrong and propose fixes for your approval before making any changes."

## Step 5: Fix Errors — File by File

Work through errors **one file at a time**. If a single file has multiple error types (e.g., both a ModelDescription issue AND a missing dialog reference), present ALL fixes for that file together so the user can approve them in one go.

For each file with errors:

1. Tell the user which topic has issues and list ALL errors in that file.
2. Read the full topic file.
3. For each error in the file, propose a fix:

### ModelDescription Too Long

- Find the `modelDescription` field under `beginDialog`.
- Rewrite it to be under 1024 characters. Keep the essential information:
  - What the topic does (1-2 sentences)
  - When to trigger it (valid scenarios)
  - When NOT to trigger it (invalid scenarios)
  - Remove redundant examples, excessive formatting, or verbose explanations.
- Show the user the proposed new description and its character count.

### Missing Dialog Reference

- Show the incorrect reference and what it should be (using `agent.schemaName` from config).
- If the file has multiple bad references, include all of them in the same proposal.

### Missing CloudFlow

- Tell the user the topic references a workflow that wasn't included in the clone. Include the topic's `componentName` and what it appears to do.
- Offer to review deletion or skip. A choice to review enters `src/skills/topics/delete/SKILL.md`; it is not destructive approval. Use that owner's policy, impact review, choices and scoped execution.
- If the file ALSO has other fixable errors (ModelDescription, Dialog), ask about the delete/skip decision first — if they choose delete, the other fixes are unnecessary.

4. After presenting all proposed fixes for the file, ask: "Apply these fixes?" (or "Apply this fix?" if only one).
5. If confirmed:
   - Apply all approved fixes to the file (checkpoint already saved all originals).
   - For deletions: follow the delete owner and preserve its actual local or remote outcome.
   - Report what changed and where. Count a diagnostic as fixed only after the relevant re-scan confirms it.
6. Move to the next file with errors.

After fixing all files, re-scan the agent folder to confirm the errors are resolved.

## Step 6: Final Report

After all groups are processed:

1. Re-scan the entire agent folder for errors.
2. Show a final summary:

```text
Scan complete!

- Errors before: {original_count}
- Errors fixed: {fixed_count}
- Errors remaining: {remaining_count}
```

3. If zero local errors remain, report that scope without claiming remote validation or completed Push.
4. If errors remain, report their known effects and unresolved evidence. Do not promise that skipped items cannot affect other topics.
5. After showing the results, add this note:

> Local changes have not been pushed to the agent. Use `/push` to review and approve them.

Show this note only for changes that remain local. If an owner already pushed
a change, retain its confirmed or uncertain outcome instead.

6. Ask the user: "Would you like me to **run the scan again** to make sure everything is clean, or are you good to go?"
   - If they want to scan again, go back to **Step 3** and repeat the full flow.
   - If they're done, tell the user: "Type `/menu` to see what else you can do, or just describe what you'd like to work on next."

**Do NOT ask additional questions beyond the re-scan offer. End the cleanup flow here.**
