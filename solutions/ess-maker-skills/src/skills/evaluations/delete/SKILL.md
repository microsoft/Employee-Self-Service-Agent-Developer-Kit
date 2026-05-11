# Delete Evaluation Skill

This skill guides the user through deleting evaluation test sets or individual
test cases from their Copilot Studio agent. Deleting means removing files
locally AND pushing the deletion to the live environment via push.

## CRITICAL — Local Files Are a Working Copy

The files in `workspace/agents/{slug}/evaluations/` are a **working copy**. Deleting
a local file is NOT the same as deleting the test case from the live agent.
You MUST push the deletion via `push.py`. **NEVER stop after deleting only
the local file.**

## CRITICAL — Delete Order for Test Sets

When deleting an entire test set (parent EvaluationSet + all child
EvaluationData files), you MUST delete all the children AND the parent in
a single push. The push script handles ordering automatically — it deletes
children first, then the parent. Do NOT push partial deletions.

## Rules

- ALWAYS read `.local/config.json` to get the agent folder, slug, and schema name.
- ALWAYS checkpoint before deleting anything.
- ALWAYS push the deletion to Copilot Studio after removing files.
- NEVER delete a file without confirming with the user first.
- **TRACK PROGRESS**: Use the todo list tool to track your progress.

## Step 1: Identify What to Delete

Read `.local/config.json` to get `agent.folder`.

List files in `{agent.folder}/evaluations/`. Read the `.component-map.json`
to understand parent→child relationships (entries with
`parentbotcomponentid` are children).

Determine whether the user wants to:
- **Delete a single test case** — remove one EvaluationData file
- **Delete an entire test set** — remove the EvaluationSet file AND all its
  child EvaluationData files

## Step 2: Confirm Deletion

Show the user what will be deleted:

For a **single test case**:
> I'll delete the test case "{input text}" from the **{Set Name}** evaluation
> set. Proceed?

For an **entire test set**:
> I'll delete the **{Set Name}** evaluation set and all **{N}** test cases
> in it. Proceed?

Wait for confirmation.

## Step 3: Checkpoint

```
python scripts/checkpoint.py "pre-delete-evaluation-{name}"
```

## Step 4: Delete Local Files

For a single test case: delete the one `.mcs.yml` file.

For an entire test set: delete the parent EvaluationSet file AND all child
EvaluationData files that reference it (check `parentbotcomponentid` in the
component map).

## Step 5: Dry Run

Run `python scripts/push.py --dry-run`. Confirm the expected files show as
deleted.

## Step 6: Push

Run `python scripts/push.py --yes`. The push script automatically orders
evaluation deletions — children are deleted before parents.

**If the push fails:** show the error and offer retry or revert.

## Step 7: Verify

> ✅ Evaluation test {case/set} deleted from Copilot Studio.
>
> Open the [Evaluation tab](https://copilotstudio.microsoft.com/) to confirm.
