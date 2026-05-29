# Update Evaluation Skill

This skill guides the user through modifying existing evaluation test cases
in their Copilot Studio agent. Updating means editing the local `.mcs.yml`
files AND pushing changes to Copilot Studio via push.

## CRITICAL — Local Files Are a Working Copy

The files in `my/agents/{slug}/evaluations/` are a **working copy** of the
evaluation test sets deployed in Copilot Studio. Editing a local file is NOT
the same as updating the live test case. You MUST push the changes via
`push.py` for them to take effect. **NEVER stop after editing only the local
file.**

## Rules

- ALWAYS read `my/config.json` to get the agent folder, slug, and schema name.
- ALWAYS checkpoint before making changes.
- ALWAYS push changes to Copilot Studio after editing.
- **TRACK PROGRESS**: Use the todo list tool to track your progress.

## Step 1: Identify the Test Set / Test Cases

Read `my/config.json` to get `agent.folder`.

List all files in `{agent.folder}/evaluations/`. Two kinds exist:

- **EvaluationSet** files contain `kind: EvaluationSet` — these are parent
  records that define the test set and grader.
- **EvaluationData** files contain `kind: EvaluationData` — these are
  individual test cases with `input` and `expectedOutput`.

Show the user what test sets exist and ask what they want to change. Common
modifications:

| What the user says | What to change |
|-------------------|---------------|
| "Change a test case prompt" | Update `input` in the EvaluationData file |
| "Change the expected response" | Update `expectedOutput` in the EvaluationData file |
| "Add more test cases" | Create new EvaluationData `.mcs.yml` files |
| "Remove a test case" | Delete the EvaluationData file (use delete skill) |
| "Replace placeholder values" | Update `<placeholder>` tokens in `expectedOutput` |

Once the user picks a category (or if they're not sure which test case), show
a table of all test cases in that category so they can identify the one to update:

> Here are the test cases in **{Category Name}** ({N} total):
>
> | # | Type | Input | Expected Output | File |
> |---|------|-------|----------------|------|
> | 1 | Positive | "What is my employee ID?" | "The agent should display..." | `topic-triggering-employee-id.mcs.yml` |
> | 2 | Boundary | "empolyee ID" | "The agent should display..." | `topic-triggering-employee-id-boundary.mcs.yml` |
> | ... | ... | ... | ... | ... |
>
> Which test case do you want to update? (enter a number or describe what you're looking for)

## Step 2: Checkpoint

Run in the terminal:

```
python scripts/checkpoint.py "pre-update-evaluation"
```

## Step 3: Make the Changes

Edit the relevant `.mcs.yml` files. The YAML format is:

```yaml
kind: EvaluationData
rows:
  - source: Imported
    expectedOutput: "The expected response text"
    input: "The user's test prompt"

extensionData:
  displayOrder: "{timestamp}"
```

For new test cases, create new `.mcs.yml` files following the naming convention:
`{set-name}-{short-slug}.mcs.yml`.

## Step 4: Review before push

Show the user a summary of what changed and ask for confirmation:

> Here's what I changed:
>
> | # | File | Field | Before | After |
> |---|------|-------|--------|-------|
> | 1 | `topic-triggering-salary.mcs.yml` | input | "Show my salary" | "What is my base salary?" |
> | ... | ... | ... | ... | ... |
>
> Want to **review the full file** before pushing, or **push now**?

- **If user says review**: Show the full YAML of the changed file(s).
- **If user says push**: Proceed to dry run.

## Step 5: Dry Run

Run `python scripts/push.py --dry-run` to preview changes. Show the user the
output confirming modified/new/deleted evaluation files.

## Step 6: Push

Run `python scripts/push.py` to push changes to Copilot Studio.

**If the push fails:** show the error and offer retry or revert
(`python scripts/checkpoint.py --revert`).

## Step 6: Verify

> ✅ Evaluation test cases updated in Copilot Studio.
>
> Open the [Evaluation tab](https://copilotstudio.microsoft.com/) to review
> and run your updated tests.
