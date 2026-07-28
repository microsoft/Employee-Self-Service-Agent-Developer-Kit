# Update Workflow Skill

This skill guides the user through modifying an existing Power Automate cloud
flow (workflow) in their Copilot Studio agent. Updating means editing the
local working copy AND pushing the change to the live environment via push.

## CRITICAL — Local Files Are a Working Copy

The files in `workspace/agents/{slug}/` are a **working copy** of what's deployed in
Copilot Studio. Editing a local file is NOT the same as updating the live
workflow. You MUST push the changes to Copilot Studio via `push.py` for them
to take effect. **NEVER stop after editing only the local file.**

## Rules

- ALWAYS read `.local/config.json` to get the agent folder, slug, and schema name.
- ALWAYS read existing workflow files in the user's agent folder as schema examples before editing JSON.
- ALWAYS read the agent's `connectionreferences.mcs.yml` to verify connectors.
- ALWAYS checkpoint before making changes.
- ALWAYS push changes to Copilot Studio after editing.
- **TRACK PROGRESS**: Use the todo list tool to track your progress.

## Step 1: Identify the Workflow

Read `.local/config.json` to get `agent.folder` and `agent.slug`.

List workflow folders in `{agent.folder}/workflows/`. Each contains
`metadata.yml` and `workflow.json`.

Match the user's request to a workflow by folder name or display name in
`metadata.yml`.

If ambiguous, list available workflows and ask.

## Step 2: Understand the Change

Read both `metadata.yml` and `workflow.json` for the workflow. Ask the user
what they want to change if not already clear. Common modifications:

| What the user says | What to change |
|-------------------|---------------|
| "Change the connector call" | Update the action's `operationId` or parameters |
| "Add a new action/step" | Insert an action in `workflow.json` |
| "Change what data is returned" | Update `Respond_to_Copilot` outputs |
| "Change the inputs" | Update trigger input definitions |
| "Add error handling" | Add `runAfter` conditions or scope actions |
| "Change the connection" | Update `connectionReferences` |

Show the relevant section and propose the edit.

## Step 3: Checkpoint

Run in the terminal:

```
python scripts/checkpoint.py "pre-update-{WorkflowName}"
python scripts/emit_capability.py workflow_update
```

The `emit_capability.py` line records anonymous usage telemetry (best-effort,
non-blocking); it needs no user-facing message and never fails the step.

## Step 4: Apply the Edit

Make the change using file editing tools.

**Safe modification patterns:**
- Changing action parameters (query strings, field mappings, etc.)
- Adding/removing actions in the flow definition
- Updating `Respond_to_Copilot` output schema
- Changing input parameter definitions in the trigger

**What NOT to change without warning:**
- `workflowId` in `metadata.yml` — breaks topic references
- Connection reference logical names — must match what's configured in the env
- The trigger type — topics expect a specific trigger shape

After editing, read the file back to verify.

## Step 5: Scan for Errors

Check the edited files for errors using the diagnostics tool.

## Step 6: Dry Run

Run:

```
python scripts/push.py --dry-run
```

Show the diff summary.

## Step 7: Push to Copilot Studio

Ask: "Ready to push this change to your environment?"

When confirmed:

```
python scripts/push.py --yes
```

**If the push fails**, offer **Retry** or **Revert**.

## Step 8: Verify

> ✅ **{WorkflowName}** has been updated in Copilot Studio.
>
> Remember to **Publish** your agent to make the change live.
>
> [Open Copilot Studio](https://copilotstudio.microsoft.com/)

## Step 9: Offer Next Steps

- "Would you like to make another change?"
- "Type `/menu` to see all available commands."
