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

If the user wants to delete a single test case but hasn't specified which one,
show a table of all test cases in the relevant category:

> Here are the test cases in **{Category Name}** ({N} total):
>
> | # | Input | Expected Output | File |
> |---|-------|----------------|------|
> | 1 | "What is my employee ID?" | "The agent should display..." | `topic-triggering-employee-id.mcs.yml` |
> | 2 | "empolyee ID" | "The agent should display..." | `topic-triggering-employee-id-boundary.mcs.yml` |
> | ... | ... | ... | ... |
>
> Which test case do you want to delete? (enter a number or describe what you're looking for)

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

## Step 5: Quality Validation (single test case deletion only)

**Skip this step if deleting an entire test set** — there are no remaining
cases to validate.

**Also skip if this was the last test case in the category** — zero remaining
cases means there is nothing to validate. In this situation, prompt the user:

> This was the last test case in **{category}**. The parent EvaluationSet
> file still exists but the set is now empty. Would you like to delete the
> entire set as well?

- If yes: follow the "entire test set" deletion path (Step 4) for the parent
  EvaluationSet file, then proceed to Step 7 (dry run).
- If no: proceed to Step 6 with a note that the set is empty.

When deleting a single test case and cases remain, run quality validation on
the remaining cases in the affected category. Removing a case can cause
dimension scores to drop — for example, deleting the only negative case drops
Failure Mode Coverage, or removing a keyword input shifts Diversity.

Invoke the validate subagent on **all remaining** `.mcs.yml` files in the
affected category (not just the deleted file). After it returns, paste its
full quality report output verbatim to the user (do not summarize). Then
follow the quality gate + fix flow defined in
`src/skills/evaluations/quality-fix-flow.md`. The “review step” referred to
there is Step 6 of this skill.

**Do not proceed to Step 6 until quality validation has returned results and
any fixes are complete.**

---

## Step 6: Review before push

Show the user a summary of what will be deleted and ask for final confirmation:

> Here's what will be removed:
>
> | # | File | Input |
> |---|------|-------|
> | 1 | `topic-triggering-salary.mcs.yml` | "Show my salary" |
> | ... | ... | ... |
>
> This will delete **{N}** file(s) from Copilot Studio. Proceed?

- **If user confirms**: Proceed to dry run.
- **If user cancels**: Revert local deletions via `python scripts/checkpoint.py --revert`.

## Step 7: Dry Run

Run `python scripts/push.py --dry-run`. Confirm the expected files show as
deleted.

## Step 8: Push

Run `python scripts/push.py`. The push script automatically orders
evaluation deletions — children are deleted before parents.

**If the push fails:** show the error and offer retry or revert.

## Step 9: Verify

> ✅ Evaluation test {case/set} deleted from Copilot Studio.
>
> Open the [Evaluation tab](https://copilotstudio.microsoft.com/) to confirm.
