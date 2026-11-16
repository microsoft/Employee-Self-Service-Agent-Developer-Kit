# Cleanup Skill

<!-- markdownlint-disable MD001 -->

This skill scans a cloned ESS agent for compile errors and walks the user through fixing them.

Distinguish local fixes from changes pushed to the agent. Use the normal topic
update or delete owner for approved changes and the general Push prompt for
a selected batch. Carry scoped approval forward without repeating it.

## Rules

- Before proposing or applying topic-file fixes or deletions, read and apply **Authoring policy for this release** in [the shared topic contract](../topics/experience-contract.md). Carry template-protected deletions and independently blocked operations into the report as unchanged with their specific reason, not as fixed; continue read-only scanning and independently eligible work.
- Do NOT run terminal commands or scripts EXCEPT the kit's own helper scripts under `scripts/`, including the selected topic owner's preview and approved execution commands. For everything else - file edits, validation, lookups - use your built-in file reading, writing, and editing tools only. Do NOT use Python, PowerShell, Node.js, or any other scripting language to do work the editing tools can do.
- Do NOT fix errors automatically without user confirmation. Present each group of errors and ask the user before making changes.
- Do NOT modify the source template files in `src/`. Only modify files inside the agent folder (the cloned agent at the workspace root).
- After fixing errors, re-scan to verify the fix worked. Show the updated error count.
- **Communication**: Follow the communication rules in `copilot-instructions.md`. Use the status definitions below for observed results. Keep internal tooling terms out of maker-facing messages.
- **Pending verification**: Preserve a completed edit without repeatedly applying it when diagnostics have not refreshed. Report the edit and verification state separately; do not count an unconfirmed diagnostic result as resolved.

## Cleanup status updates

Read the [shared foundation](../topics/experience-contract.md), including Status update markers and Presentation and scope, before scanning. Use the local definitions below, not a native todo list or progress checklist. Bind counts to the current deduplicated local scan. Delegated topic edits and deletions emit through their performing owners; cleanup does not repeat their updates.

| Reporting point        | Completion condition                                                                                              | Completion message                                                       |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `cleanup-scan`         | Both local error sources have been read for the selected agent and their current results merged and deduplicated. | ✅ Checked the local agent files: **{Error count}** errors found.        |
| `cleanup-checkpoint`   | The checkpoint operation confirms a saved snapshot before any approved edit.                                      | ✅ Saved a checkpoint of your agent files.                               |
| `cleanup-verification` | A fresh combined scan reflects the post-change files and establishes the remaining local error count.             | ✅ Rechecked the local agent files: **{Remaining count}** errors remain. |

For missing, failed or stale scan evidence, state what remains unverified rather than claiming zero errors or resolved findings. Preserve confirmed edits and remote outcomes separately. A failed checkpoint leaves fixes unstarted. For partial work, name completed changes and the remaining issue in the [Final Report](#step-6-final-report). A local scan does not verify remote behavior.

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

{EMIT_STATUS_UPDATE: cleanup-scan}

If the error count is **zero**, skip the checkpoint entirely and jump
straight to Step 6 (Final Report) with 0 errors before / 0 fixed / 0
remaining. Do NOT ask the user to confirm a checkpoint — there's nothing
to fix.

If the error count is **greater than zero**, continue to Step 2b.

## Step 2b: Checkpoint

Tell the user:

> I found {count} errors. Before making any changes, I'll save a checkpoint of your agent files. This lets you restore the local files if needed; it does not restore changes already pushed to the agent.
>
> ##### YOUR CHOICES
>
> | Choice          | What happens                                                                                     |
> | --------------- | ------------------------------------------------------------------------------------------------ |
> | Save checkpoint | Save a local snapshot, then review proposed fixes. This does not approve edits or a remote Push. |
> | Not now         | Leave files unchanged and stop before fixing errors.                                             |

Use the shared native-question conventions. Call `ask_user`:

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "action": {
        "type": "string",
        "title": "Cleanup checkpoint",
        "description": "How would you like to continue?",
        "enum": ["Save checkpoint", "Not now"]
      }
    }
  }
}
```

Wait for Save checkpoint before continuing. Not now stops without edits.

When confirmed:

- Run in the terminal: `python scripts/checkpoint.py "pre-scan-fixes"`
- This saves a full snapshot of all working files before any modifications.

{EMIT_STATUS_UPDATE: cleanup-checkpoint}

Continue only after the checkpoint is confirmed.

- Record anonymous usage telemetry (best-effort, non-blocking — no user-facing
  message, and it never fails the step): `python scripts/emit_capability.py cleanup`

## Step 3: Scan for Errors (detailed categorization)

Gather errors from TWO sources and combine them into a single list:

1. **VS Code Problems panel** — Use the error/diagnostics tool with NO file path filter (get all errors across the workspace). Filter the results to only include errors from files inside `{agent.folder}/`.
2. **Agent folder scan** — Use the error/diagnostics tool specifically on `{agent.folder}/`.

Merge both lists and deduplicate (the same error may appear in both). Use the combined list for the rest of this flow. Reuse the quick scan while still current; report only a new scan assessment here.

{EMIT_STATUS_UPDATE: cleanup-scan}

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

> ##### SCAN RESULTS
>
> I found {total} errors across {file_count} files:
>
> | Error Type                | Files Affected | Fix                             |
> | ------------------------- | -------------- | ------------------------------- |
> | ModelDescription too long | {count} topics | Truncate to fit 1024-char limit |
> | Missing CloudFlow         | {count} topics | Review topic deletion or skip   |
> | Missing Dialog reference  | {count} topics | Correct the schema name         |

Then say: "Let's walk through each file. I'll explain what's wrong and propose fixes for your approval before making any changes."

## Step 5: Fix Errors — File by File

Work through errors **one file at a time**. If a single file has multiple error types (e.g., both a ModelDescription issue AND a missing dialog reference), present ALL fixes for that file together so the user can approve them in one go.

For each file with errors:

1. Read the full topic file.
2. Name the topic under an H5 TOPIC heading and list all its errors under H5 ERRORS.
3. Propose fixes under H5 PROPOSED FIXES using the applicable guidance below, then show the corresponding choice explanations and native control.

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
- If the file also has other fixable errors, use this review/skip decision first. Skip the other fixes only after the delete owner confirms removal; selecting a deletion review alone does not remove anything.

> ##### YOUR CHOICES
>
> | Choice                | What happens                                                                                                        |
> | --------------------- | ------------------------------------------------------------------------------------------------------------------- |
> | Review topic deletion | Inspect deletion eligibility and effects, then review the available removal options. This does not approve removal. |
> | Skip                  | Leave this issue unchanged and continue to other proposed fixes.                                                    |

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "action": {
        "type": "string",
        "title": "Missing workflow reference",
        "description": "How would you like to continue?",
        "enum": ["Review topic deletion", "Skip"]
      }
    }
  }
}
```

After presenting all remaining proposed fixes for the file, explain the choices and call `ask_user`:

> ##### YOUR CHOICES
>
> | Choice               | What happens                                                                                          |
> | -------------------- | ----------------------------------------------------------------------------------------------------- |
> | Apply proposed fixes | Apply only the displayed local changes, then check their effect. This does not approve a remote Push. |
> | Skip                 | Leave these proposed changes unapplied and continue.                                                  |

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "action": {
        "type": "string",
        "title": "Topic fixes",
        "description": "How would you like to continue?",
        "enum": ["Apply proposed fixes", "Skip"]
      }
    }
  }
}
```

If confirmed:

- Use the normal topic update owner for the approved fixes. Carry the local-only edit scope and existing checkpoint; do not infer remote-save approval. If no checkpoint has been saved for these files, return to Step 2b before editing.
- For deletions, follow the delete owner and preserve its actual local or remote outcome.
- Reuse the owner's update for what changed and where. Count a diagnostic as fixed only after the relevant re-scan confirms it.

Move to the next file with errors.

After processing all files, proceed to the final combined scan below.

## Step 6: Final Report

After all groups are processed, re-scan both error sources for the entire agent folder and deduplicate. For the initial zero-error path, reuse the still-current quick scan and proceed directly to the report without another status update.

After a new final scan assessment, before the report:

{EMIT_STATUS_UPDATE: cleanup-verification}

Show a final summary:

> ##### CLEANUP RESULTS
>
> ##### ERRORS BEFORE
>
> {original_count}
>
> ##### ERRORS FIXED
>
> {fixed_count}
>
> ##### ERRORS REMAINING
>
> {remaining_count}

Use only observed counts; if verification is unavailable or stale, replace the affected count with the actual unresolved state rather than a guessed number. Include actual owner save outcomes separately when any changes were pushed.

If zero local errors remain, report that scope without claiming remote validation or completed Push. If errors remain, report their known effects and unresolved evidence. Do not promise that skipped items cannot affect other topics.

After showing the results, add this note:

> Local changes have not been pushed to the agent. Use `/push` to review and approve them.

Show this note only for changes that remain local. If an owner already pushed
a change, retain its confirmed or uncertain outcome instead.

Explain these choices and use the native control:

> ##### YOUR CHOICES
>
> | Choice         | What happens                                                                                  |
> | -------------- | --------------------------------------------------------------------------------------------- |
> | Run scan again | Inspect the local files again. Any additional fixes still need their own review and approval. |
> | Done           | Finish cleanup with the reported changes and unresolved issues unchanged.                     |

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "action": {
        "type": "string",
        "title": "Cleanup follow-up",
        "description": "How would you like to continue?",
        "enum": ["Run scan again", "Done"]
      }
    }
  }
}
```

- If they want to scan again, go back to **Step 3** and repeat the full flow.
- If they're done, tell the user: "Type `/menu` to see what else you can do, or just describe what you'd like to work on next."

**Do NOT ask additional questions beyond the re-scan offer. End the cleanup flow here.**
