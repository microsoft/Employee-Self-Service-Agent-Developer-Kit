# Update Evaluation Skill

This skill guides the user through modifying existing evaluation test cases
in their Copilot Studio agent. Updating means editing the local `.mcs.yml`
files AND pushing changes to Copilot Studio via push.

## CRITICAL — Local Files Are a Working Copy

The files in `workspace/agents/{slug}/evaluations/` are a **working copy** of the
evaluation test sets deployed in Copilot Studio. Editing a local file is NOT
the same as updating the live test case. You MUST push the changes via
`push.py` for them to take effect. **NEVER stop after editing only the local
file.**

## Rules

- ALWAYS read `.local/config.json` to get the agent folder, slug, and schema name.
- ALWAYS checkpoint before making changes.
- ALWAYS push changes to Copilot Studio after editing.
- **TRACK PROGRESS**: Use the todo list tool to track your progress.

## Step 1: Identify the Test Set / Test Cases

Read `.local/config.json` to get `agent.folder`.

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

## Step 4: Dry Run

Run `python scripts/push.py --dry-run` to preview changes. Show the user the
output confirming modified/new/deleted evaluation files.

## Step 5: Push

Run `python scripts/push.py --yes` to push changes to Copilot Studio.

**If the push fails:** show the error and offer retry or revert
(`python scripts/checkpoint.py --revert`).

## Step 6: Verify

> ✅ Evaluation test cases updated in Copilot Studio.
>
> Open the [Evaluation tab](https://copilotstudio.microsoft.com/) to review
> and run your updated tests.
