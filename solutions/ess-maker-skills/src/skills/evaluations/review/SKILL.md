# Review Evaluation Test Sets

Handle reviewer, judge, or SME requests to review evaluation test sets that a
maker tagged with `review_requested`.

This is a workflow review, not a quality-validation request. Do not invoke the
evaluation validate subagent when entering this skill.

## Step 1: Discover tagged test sets

For configured agents, the reviewer must first have the latest Copilot Studio
data pulled through setup/refresh. The local working status alone is not proof
that the tag was pushed.

From the solution root, run:

```text
python scripts/evaluation_review.py --list --status review_requested
```

This command compares each configured-agent working set with its matching
`.baseline/evaluations/{set}/` snapshot from the latest pull or successful
push. It returns only sets whose `localStatus` and `deployedStatus` are both
`review_requested`.

Use the command's JSON output as the complete pending-review list. Do not
replace it with a broad file-search or glob. The command filters out local-only review requests that have not been pushed,
review completions waiting to be pushed, and `review_completed` sets. It
returns each set's source, folder, test-case count, local status, deployed
status, synchronization state, and next action.

## Step 2: List before reviewing

Before reading cases or running any validation, present the pending sets:

> | # | Test set | Source | Test cases | Review status |
> |---|---|---|---|---|
> | 1 | Compensation | Configured agent | 8 | Review requested |
> | 2 | Benefits | Workspace | 5 | Review requested |

If no tagged sets are available, say that no test sets from the latest pulled
Copilot Studio state are currently available for review. Do not treat a local
`review_requested` change with `nextAction=push_review_request` as reviewable,
and do not run the quality validator as a fallback.

Use the available structured question control (dropdown or choice buttons)
with one option per returned test set. Each option must include the test-set
name, source, and case count. Ask exactly:

> Which test set would you like to review?

Do not call the test sets "pending" in the user-facing question. The
`review_requested` status already communicates that internally.
Wait for the user to select before continuing.

## Step 3: Continue the review workflow

After the user selects a set, read
`src/skills/evaluations/update/SKILL.md` and follow **Flow R2 — Review assigned
test sets**, beginning with showing its prompts and expected responses.

The reviewer inspects prompts and expected responses and provides feedback,
suggestions, or recommendations for the maker. The reviewer does not edit
test-case source files in this flow, so quality validation is not invoked.
Never describe this workflow as "view-only"; it produces an actionable review
handoff.

Before ending, the reviewer must be offered a structured choice to **Provide
feedback or recommendations for the maker** or **Mark review complete without
feedback**. If recommendations are supplied, state that the maker owns the
official edits, validation, push, and subsequent evaluation run.
