# Delete Topic Skill

This skill guides the user through deleting a topic from their Copilot Studio
agent. Deleting means removing the topic both locally AND from the live
environment via push.

## CRITICAL — Local Files Are a Working Copy

The files in `workspace/agents/{slug}/` are a **working copy** of what's deployed in
Copilot Studio. Deleting a local file is NOT the same as deleting the topic
from the live agent. You MUST push the deletion to Copilot Studio via
`push.py` for it to take effect. **NEVER stop after deleting only the local
file.**

## Rules

- ALWAYS read `.local/config.json` to get the agent folder, slug, and schema name.
- ALWAYS checkpoint before deleting anything.
- ALWAYS push the deletion to Copilot Studio after removing the local file.
- NEVER delete a file without confirming with the user first.
- NEVER delete system topics unless the user explicitly insists after a warning.
- **TRACK PROGRESS**: Use the todo list tool to track your progress.

## Step 1: Identify the Topic

Read `.local/config.json` to get `agent.folder` and `agent.slug`.

If the user named a specific topic, find the matching file in
`{agent.folder}/topics/`. Match by:
- Filename (e.g., "submit it support ticket" → `submititsupportticket.mcs.yml`)
- Display name inside the file (`componentName` field)
- Trigger phrases (`triggerQueries`)

If the match is ambiguous or no match is found, list the available topics
from the folder and ask the user to pick one.

## Step 2: Confirm Deletion

Read the topic file to understand what it does. Show the user:

- **Topic name** (from `componentName`)
- **What it does** (from `modelDescription` or trigger phrases)
- **Whether it's a system topic** (filenames like `on-error`, `conversation-start`,
  `reset-conversation`, etc. are system topics)

If it's a **system topic**, warn:

> ⚠️ This is a system topic that handles core agent behavior. Deleting it
> may break your agent. Are you sure you want to proceed?

For all topics, confirm:

> I'll delete **{TopicName}** from your agent and push the deletion to
> Copilot Studio. This will remove it from the live environment. Proceed?

Wait for the user to confirm before continuing.

## Step 3: Checkpoint

Save a backup before making changes. Run in the terminal:

```
python scripts/checkpoint.py "pre-delete-{TopicName}"
```

Tell the user: "Saved a backup of your current agent files."

## Step 4: Delete the Local File

Delete the topic file from `{agent.folder}/topics/{filename}.mcs.yml`.

Verify the file is gone by listing the topics directory.

## Step 5: Dry Run

Run in the terminal:

```
python scripts/push.py --dry-run
```

Show the user the diff summary. It should show the topic as deleted. Example:

> Here's what will be pushed:
>
> | Action | File |
> |--------|------|
> | ❌ Delete | topics/submititsupportticket.mcs.yml |

## Step 6: Push to Copilot Studio

Ask the user: "Ready to push this deletion to your environment?"

When confirmed, run in the terminal:

```
python scripts/push.py --yes
```

This authenticates to Dataverse, deletes the bot component record, and
updates the local baseline.

**If the push fails:**
- Show the error output to the user.
- Offer two options:
  - **Retry** — run push again
  - **Revert** — `python scripts/checkpoint.py --revert` to restore the
    backup from Step 3

## Step 7: Verify

After a successful push, tell the user:

> ✅ **{TopicName}** has been deleted from your agent in Copilot Studio.
>
> Remember to **Publish** your agent in the portal to make the change live
> for end users.
>
> [Open Copilot Studio](https://copilotstudio.microsoft.com/)

If the deleted topic was referenced by other topics (via `BeginDialog`),
mention:

> ⚠️ Other topics may reference this one. Run `/scan` to check for broken
> references.

## Step 8: Offer Next Steps

- "Would you like to delete another topic, or do something else?"
- "Type `/scan` to check for any broken references."
- "Type `/menu` to see all available commands."
