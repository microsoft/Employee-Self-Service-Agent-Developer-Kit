# Delete Workflow Skill

This skill guides the user through deleting a Power Automate cloud flow
(workflow) from their Copilot Studio agent. Deleting means removing the
workflow both locally AND from the live environment via push.

## CRITICAL — Local Files Are a Working Copy

The files in `workspace/agents/{slug}/` are a **working copy** of what's deployed in
Copilot Studio. Deleting local files is NOT the same as deleting the workflow
from the live agent. You MUST push the deletion to Copilot Studio via
`push.py` for it to take effect. **NEVER stop after deleting only the local
files.**

## Rules

- ALWAYS read `.local/config.json` to get the agent folder, slug, and schema name.
- ALWAYS checkpoint before deleting anything.
- ALWAYS push the deletion to Copilot Studio after removing local files.
- NEVER delete without confirming with the user first.
- NEVER delete the shared ESS orchestrator flows (ServiceNow/Workday shared
  flows) unless the user explicitly insists after a strong warning.
- **TRACK PROGRESS**: Use the todo list tool to track your progress.

## Step 1: Identify the Workflow

Read `.local/config.json` to get `agent.folder` and `agent.slug`.

List the workflow folders in `{agent.folder}/workflows/`. Each workflow is a
folder containing `metadata.yml` and `workflow.json`.

If the user named a specific workflow, find the matching folder by:
- Folder name
- Display name in `metadata.yml` (`name` field)

If the match is ambiguous or no match is found, list the available workflows
and ask the user to pick one.

## Step 2: Check for Topic References

Before deleting, check if any topics reference this workflow's ID. Search
all topic files in `{agent.folder}/topics/` for the workflow's GUID (from
`metadata.yml` → `workflowId`).

If topics reference this workflow, warn the user:

> ⚠️ The following topics call this workflow:
> - {TopicName1}
> - {TopicName2}
>
> Deleting the workflow will break these topics. Would you like to delete
> the referencing topics as well, or just the workflow?

## Step 3: Confirm Deletion

Show the user:

- **Workflow name** (from `metadata.yml`)
- **What it does** (from `description` in `metadata.yml`)
- **Topics that reference it** (if any, from Step 2)

Confirm:

> I'll delete the workflow **{WorkflowName}** from your agent and push the
> deletion to Copilot Studio. This will remove it from the live environment.
> Proceed?

Wait for the user to confirm.

## Step 4: Checkpoint

Run in the terminal:

```
python scripts/checkpoint.py "pre-delete-{WorkflowName}"
```

Tell the user: "Saved a backup of your current agent files."

## Step 5: Delete the Local Files

Delete the entire workflow folder: `{agent.folder}/workflows/{folder-name}/`

If the user also chose to delete referencing topics (from Step 2), delete
those topic files as well.

Verify the files are gone.

## Step 6: Dry Run

Run in the terminal:

```
python scripts/push.py --dry-run
```

Show the user the diff summary.

## Step 7: Push to Copilot Studio

Ask the user: "Ready to push this deletion to your environment?"

When confirmed, run:

```
python scripts/push.py --yes
```

**If the push fails:**
- Show the error output.
- Offer: **Retry** or **Revert** (`python scripts/checkpoint.py --revert`).

## Step 8: Verify

After a successful push, tell the user:

> ✅ **{WorkflowName}** has been deleted from your agent.
>
> Remember to **Publish** your agent to make the change live.
>
> [Open Copilot Studio](https://copilotstudio.microsoft.com/)

## Step 9: Offer Next Steps

- "Would you like to delete anything else?"
- "Type `/scan` to check for broken references."
- "Type `/menu` to see all available commands."
