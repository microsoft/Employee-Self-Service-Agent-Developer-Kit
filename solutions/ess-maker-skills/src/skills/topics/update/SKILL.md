# Update Topic Skill

This skill guides the user through modifying an existing Copilot Studio topic.
Updating means editing the local working copy AND pushing the change to the
live environment via push.

## CRITICAL — Local Files Are a Working Copy

The files in `my/agents/{slug}/` are a **working copy** of what's deployed in
Copilot Studio. Editing a local file is NOT the same as updating the live
topic. You MUST push the changes to Copilot Studio via `push.py` for them to
take effect. **NEVER stop after editing only the local file.**

## Rules

- ALWAYS read `my/config.json` to get the agent folder, slug, and schema name.
- ALWAYS read existing topic files in the user's agent folder as schema examples before editing any YAML.
- ALWAYS checkpoint before making changes.
- ALWAYS push changes to Copilot Studio after editing.
- NEVER modify system topics (`on-error`, `conversation-start`, etc.) without
  warning the user about potential side effects.
- **TRACK PROGRESS**: Use the todo list tool to track your progress.

## Step 1: Identify the Topic

Read `my/config.json` to get `agent.folder` and `agent.slug`.

If the user named a specific topic, find the matching file in
`{agent.folder}/topics/`. Match by filename, `componentName`, trigger phrases,
or `modelDescription`.

If the match is ambiguous, list available topics and ask the user to pick.

## Step 2: Understand the Change

Read the full topic file. Ask the user what they want to change if not
already clear. Common modifications:

| What the user says | What to change |
|-------------------|---------------|
| "Change the trigger phrases" | Update `triggerQueries` list |
| "Change the response message" | Update `SendActivity` → `text` |
| "Add a question/prompt" | Add a `Question` or `AdaptiveCardPrompt` action |
| "Add a condition" | Add a `ConditionGroup` action |
| "Change when the topic fires" | Update `modelDescription` and/or `triggerQueries` |
| "Call a different workflow" | Update `InvokeFlowAction` → `flowId` |
| "Add a step" | Insert a new action in the `actions` chain |
| "Remove a step" | Remove an action (update `nextActionId` chain) |

Show the user the relevant section of the current topic and propose the
specific edit. Explain what will change and why.

## Step 3: Checkpoint

Run in the terminal:

```
python scripts/checkpoint.py "pre-update-{TopicName}"
```

Tell the user: "Saved a backup of your current agent files."

## Step 4: Apply the Edit

Make the change to the topic file using file editing tools.

**Safe modification patterns:**
- Adding/removing trigger phrases: Edit the `triggerQueries` list
- Changing messages: Edit `text` fields in `SendActivity` actions
- Changing model description: Edit `modelDescription` (keep under 1024 chars)
- Adding actions: Insert in the `actions` list and update `nextActionId` links
- Removing actions: Remove from `actions` and fix `nextActionId` chain

**What NOT to change without warning:**
- `schemaName` — breaks references from other topics
- `componentName` — may affect display in Copilot Studio
- `kind` — system vs. general topic classification
- Action IDs referenced by other actions — breaks the flow chain

After editing, read the file back to verify the change looks correct.

## Step 5: Scan for Errors

Check for errors across the **full agent folder** using the diagnostics tool.

- If errors exist in the **edited file** → fix them before proceeding.
- If **pre-existing errors** exist in other files → mention briefly but do
  NOT block the push.

## Step 6: Dry Run

Run in the terminal:

```
python scripts/push.py --dry-run
```

Show the user the diff summary. It should show the topic as modified.

## Step 7: Push to Copilot Studio

Ask the user: "Ready to push this change to your environment?"

When confirmed, run:

```
python scripts/push.py --yes
```

**If the push fails:**
- Show the error output.
- Offer: **Retry** or **Revert** (`python scripts/checkpoint.py --revert`).

## Step 8: Verify

After a successful push, tell the user:

> ✅ **{TopicName}** has been updated in Copilot Studio.
>
> Remember to **Publish** your agent to make the change live.
>
> [Open Copilot Studio](https://copilotstudio.microsoft.com/)

## Step 9: Offer Next Steps

- "Would you like to make another change?"
- "Type `/scan` to check for errors."
- "Type `/menu` to see all available commands."
