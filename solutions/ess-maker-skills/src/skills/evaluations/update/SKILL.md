# Update Evaluation Skill

Update evaluation test sets from either the workspace-level catalogue output or
a configured agent. Keep `.mcs.yml` and CSV representations synchronized.
Any updated set can be offered for push; a workspace-level set is copied into
the configured agent only after the user confirms the push. After a successful
push, the temporary workspace-level source is removed so the configured-agent
copy becomes the single local source of truth.

## Evaluation locations

| Source | Evaluation sets | CSV exports | Push behavior |
|---|---|---|---|
| Workspace | `workspace/evaluations/{set}/` | `workspace/evaluations/exports/` | Local only |
| Configured agent | `{agent.folder}/evaluations/{set}/` | `{agent.folder}/evaluations/exports/` | Eligible for push |

## Rules

- Always discover sets from both locations when they are available.
- Do not require setup to update a workspace-level set.
- Require a complete `.local/config.json` only for discovering or pushing
  configured-agent sets.
- Ignore `exports/` when looking for EvaluationSet folders.
- Show sets with the same name as separate entries when they come from
  different sources.
- Update `.mcs.yml` first, then regenerate the matching CSV from the final YAML.
- Never ask whether to update YAML, CSV, or both. YAML and CSV synchronization
  is automatic and mandatory for every change.
- Run quality validation before completing either a local update or an
  agent-owned update.
- Never push until the user explicitly chooses to push.
- Promote a workspace-level set only after the user chooses to push it. Promotion
  stages a copy under the configured agent. Remove the workspace source and its
  matching workspace CSV only after the push succeeds; preserve both if
  promotion or push fails.
- Track progress with the todo list tool.
- Never ask a user to type `review_requested` or `review_completed`; the skill
  owns review status values.
- Store local review state in `review.json` beside the parent EvaluationSet.
- Preserve the human-authored Dataverse description when adding or changing
  the ADK review marker.
- Whenever test sets or test cases are shown for user selection, use the
  available structured question control with named choices (dropdown, buttons,
  or multi-select as appropriate). Do not rely on an open-text question when
  the choices are already known.
- Never finish immediately after displaying test cases. Makers must receive an
  explicit choice to edit the set themselves, send it to a judge or SME for
  feedback, or keep it unchanged. Reviewers must receive an explicit choice to
  provide feedback, suggestions, or recommendations, or complete review
  without feedback.

## Review-intent routing

Before the normal update flow, inspect the user's intent:

- **Tag for review / send for review** → follow **Flow R1** below.
- **Review assigned test sets / act as judge or SME** → follow **Flow R2**.
- Otherwise continue with Step 1.

Review state and review activity are separate:

- `review_requested` means the set is tagged to become available for review
  after a successful push.
- It does not prove that another user has received, opened, or reviewed the
  set.
- `review_completed` is valid only after the user explicitly enters Flow R2,
  reviews the set, and chooses **Mark review complete**, or explicitly asks to
  complete an active review.

Never route a normal or resumed push into review completion merely because its
local `review.json` contains `review_requested`.

### Review-state reconciliation

Before showing any review-related next action, run
`evaluation_review.py --list-all` and use both:

- `localStatus` - the desired working change.
- `deployedStatus` - the latest pulled or successfully pushed Copilot Studio
  status from the configured agent baseline.

Use `nextAction` from the command:

| Next action | Meaning | User-facing action |
|---|---|---|
| `push_review_request` | Local tag is requested, but Copilot Studio is untagged or the set is not deployed | Offer to push the review request |
| `review` | Local and deployed status are both `review_requested` | Offer the reviewer feedback/completion workflow |
| `push_review_completion` | Review was completed locally but Copilot Studio still has the requested tag | Offer to push the completed-review marker |
| `run_or_view_results` | Local and deployed status are both `review_completed` | Offer run or result-history actions |

Never derive these actions from `localStatus` alone. If another user may have
changed the set since the last pull, refresh first; the baseline must represent
the latest retrieved Copilot Studio state before entering Flow R2.

### Flow R1 — Tag selected test sets for review

Before asking the user to tag a set, explain:

> **Mark for review** indicates that the test set is ready for another
> reviewer, judge, or SME to inspect and provide feedback, suggestions, or
> recommendations. The maker remains responsible for editing the test set. The
> tag must be pushed to Copilot Studio before it is shared with other users.

1. For a generic request such as **"tag testsets for review"**, run:

   ```text
   python scripts/evaluation_review.py --list-all
   ```

   Display every returned workspace and configured-agent test set, including
   its source, test-case count, and current review status.
2. Use the available structured choice control to ask which test set or sets
   should be tagged. Each option must contain the set name and source.
3. Wait for an explicit selection.
4. Do not infer a selection from the previous conversation, the most recently
   generated set, or the active agent. A set is preselected only when the user
   explicitly names it (for example, "tag Compensation") or answers the
   create flow's scoped question about the generated sets.
5. For each selected set, run:

   ```text
   python scripts/evaluation_review.py --set-folder "{set-folder}" --status review_requested
   ```

6. Explain that the tag is local until pushed. Continue through the normal
   configuration check, promotion when needed, dry run, and push flow.

The pushed parent description contains:

```text
[ADK-REVIEW status=review_requested]
```

### Flow R2 — Review assigned test sets

Setup continues to pull all evaluation test sets. When a user asks to review
test sets, run:

```text
python scripts/evaluation_review.py --list --status review_requested
```

Use its JSON output to list pending sets from both workspace-level evaluations
and every configured agent. Do not substitute an ad hoc `review.json` glob.

**Hard entry gate:** display the tagged-set table and wait for the user to
select a set before reading all category files or invoking quality validation.
The word "review" alone never means "run the evaluation quality validator."
Use the available structured choice control with one option per returned set.
Ask: **"Which test set would you like to review?"** Do not use "Which pending
test set..." in the user-facing question.

For each selected set:

1. Regenerate the current CSV from the authoritative YAML, then show its
   downloadable link before displaying any prompts or expected responses.
   Immediately below the link, state:

   > The CSV file is for preview purposes only. Tell me which prompts,
   > scenarios, or rows you want to modify; changes are made to the source
   > evaluation files and automatically reflected in the CSV.

2. Show all prompts and expected responses.
3. Use a structured choice question:

   > How would you like to provide your review?

   Offer:

   - **Provide feedback or recommendations for the maker**
   - **Mark review complete without feedback**

   The reviewer does not edit the test-case source files in this flow. Capture
   and clearly summarize proposed prompt or expected-response changes in the
   conversation. State that the maker remains responsible for applying the
   official changes, validating them, pushing the set, and running it. Do not
   claim that conversational recommendations were automatically written to the
   test-set description or source files.
4. Follow **Step 6a: Review completion gate**. Do not ask about pushing before
   this gate is resolved.
5. When the user confirms completion, run:

   ```text
   python scripts/evaluation_review.py --set-folder "{set-folder}" --status review_completed
   ```

6. Show the dry run, ask for push confirmation, and push. A completed review
   is not visible to the maker until the description change is pushed.

The push replaces only the ADK marker with:

```text
[ADK-REVIEW status=review_completed]
```

The human-authored description remains unchanged. Completed sets no longer
appear in the pending-review list.

## Step 1: Discover all evaluation sets

If the user explicitly names a test set, run:

```text
python scripts/evaluation_review.py --list-all --query "{user text}"
```

Display the returned name matches with their source and use the available
structured choice control to ask the user to select or confirm the intended
set. Do not silently choose a fuzzy match.

If the user does not name a test set, run
`python scripts/evaluation_review.py --list-all`, display every set, and use a
structured choice control to ask which one or ones to update.

### Workspace-level sets

Scan `workspace/evaluations/` when it exists. For every child folder except
`exports/`, find a parent file containing `kind: EvaluationSet`. Count its
`EvaluationData` child files.

### Configured-agent sets

Read `.local/config.json` when it exists. If `setup` is `"complete"` and
`agent.folder` exists, scan `{agent.folder}/evaluations/` using the same rules.

Present one combined table:

> | # | Test set | Source | Test cases | Result after update |
> |---|---|---|---|---|
> | 1 | Compensation | Workspace | 8 | Local YAML + CSV; push offered after update |
> | 2 | Topic Triggering | Configured agent | 24 | YAML + CSV; push offered after update |

If the same set name exists in both locations, include both rows and their full
source labels. If no sets are found, explain that there is nothing to update and
suggest creating an evaluation set first.

Ask which set or sets the user wants to update using the structured choice
control. Each option must include the test-set name, source, and case count.

## Step 2: Identify the requested changes

For each selected set, regenerate its CSV from the authoritative YAML and show
the downloadable CSV link first:

> Here's the current evaluation set for **{set name}**:
>
> [{YYYYMMDD}_{Evaluation_Set_Display_Name}.csv]({csv-path})
>
> The CSV file is for preview purposes only. Tell me which prompts, scenarios,
> or rows you want to modify; changes are made to the source evaluation files
> and automatically reflected in the CSV.

Then continue with the existing detailed edit experience and show its cases:

> | # | Input | Expected output | File |
> |---|---|---|---|
> | 1 | "What is my employee ID?" | "The agent should display..." | `employee-id.mcs.yml` |

Read both `input` and `expectedOutput` from every EvaluationData file before
presenting the cases. The expected response is required context, not optional.

Unless the user already supplied a specific edit, follow the case display with
this mandatory structured question:

> How would you like to continue with **{set name}**?

Offer:

1. **Edit the test set myself**
2. **Send it to a judge or SME for feedback**
3. **Keep it unchanged**

If the maker chooses to edit, continue with the normal update flow. If they
choose judge or SME feedback, enter Flow R1 and explain that the set must be
pushed before another user can review it. If they keep it unchanged, do not
mutate or push anything without a separate explicit request.

When using a checkbox or multiple-choice UI, every case option must use this
shape:

```text
{Case label}
Prompt: "{input}"
Expected: "{expectedOutput}"
```

Never show a case-selection option containing only its prompt. If an expected
response is long, show a concise preview in the option and display the complete
value in the table immediately above it.

Support:

| Request | Change |
|---|---|
| Change a prompt | Update `input` |
| Change expected behavior | Update `expectedOutput` |
| Add a case | Create a new `EvaluationData` `.mcs.yml` file |
| Replace placeholders | Update `<placeholder>` values |
| Remove a case | Delegate to the evaluation delete skill |

Keep selection and editing as separate questions:

1. Ask which case or cases the user wants to change.
2. After selection, ask whether to change the prompt, expected response, or
   both.
3. Ask for each new value separately, always repeating the current value in the
   question:

   ```text
   Current expected response:
   "{existing expectedOutput}"

   What should the new expected response be for "{case label}"?
   ```

   For prompt edits, use the equivalent form:

   ```text
   Current prompt:
   "{existing input}"

   What should the new prompt be for "{case label}"?
   ```

Do not combine case selection and replacement values into one question.

## Step 3: Checkpoint and telemetry

If any selected set belongs to the configured agent, run:

```text
python scripts/checkpoint.py "pre-update-evaluation"
```

For workspace-only updates, do not require an agent checkpoint.

Record anonymous usage telemetry on a best-effort basis:

```text
python scripts/emit_capability.py evaluations
```

Telemetry failure must not block the update.

## Step 4: Update YAML and CSV

Edit the relevant `.mcs.yml` files. EvaluationData files use:

```yaml
kind: EvaluationData
rows:
  - source: Imported
    expectedOutput: "The expected response text"
    input: "The user's test prompt"

extensionData:
  displayOrder: "{timestamp}"
```

For a new case, create `{set-name}-{short-slug}.mcs.yml` in the selected set
folder and assign a new epoch-milliseconds `displayOrder`.

After all YAML edits, regenerate that set's CSV from its complete final
EvaluationData list:

- Workspace set: `workspace/evaluations/exports/`.
- Agent set: `{agent.folder}/evaluations/exports/`.
- Write `{YYYYMMDD}_{Evaluation_Set_Display_Name}.csv`, with spaces and
  punctuation in the display name replaced by underscores. Overwrite that
  day's file and remove an older export for the same set so the user sees one
  current preview file.
- Use the grader and threshold from the parent EvaluationSet.
- Use an RFC-4180 CSV writer.
- Prefix cells beginning with `=`, `+`, `-`, or `@` with an apostrophe.

The YAML files are authoritative. Never update a CSV independently.
Do not ask for confirmation before synchronizing the CSV; perform it as part of
the same edit operation.

## Step 5: Quality validation

Invoke the evaluation validate subagent with every `.mcs.yml` file in each
affected set, plus the set name and source folder.

Display the complete quality report directly to the user. Follow
`src/skills/evaluations/quality-fix-flow.md`; the "review step" referenced
there is Step 6 below.

If validation fixes change YAML, regenerate the matching CSV again before
continuing.

## Step 6: Review

Show a source-aware summary:

> | Set | Source | File | Field | Before | After |
> |---|---|---|---|---|---|
> | Compensation | Workspace | `base-pay.mcs.yml` | input | "salary" | "What is my base compensation?" |

Ask whether the user wants to review the complete files or apply the update.

## Step 6a: Review completion gate

Enter this gate only when the current interaction originated from **Flow R2**
or the user explicitly asked to complete an active review. Do not enter it
during Flow R1, a normal update, a normal push, or a resumed push.

In an active Flow R2 review, require `nextAction=review`. Then inspect the
selected set's `review.json`. If its status is `review_requested`, ask:

> This test set is currently marked for review. What would you like to do?

Offer:

1. **Mark review complete** — confirms the review is finished and no further
   reviewer feedback is needed.
2. **Provide feedback or recommendations for the maker** — keeps the review
   open while the reviewer prepares a written handoff. The reviewer does not
   edit the source files.

Explain these meanings before waiting for the user's choice. Marking review
complete closes the review state; it is not the same as initially marking a set
for review.

Do not show or ask the push question until the user resolves this review gate.

### Mark review complete

Run:

```text
python scripts/evaluation_review.py --set-folder "{set-folder}" --status review_completed
```

Confirm the local status is now `review_completed`, then continue to Step 7 and
ask whether to push the updated files and completed-review marker together.

### Provide feedback or recommendations for the maker

Capture the recommendations and present them back as a concise checklist tied
to the relevant prompts or expected responses. End with this mandatory
statement:

> Your recommendations are ready to hand back to the maker. The maker should apply the official test-case changes, push the updated set, and then run the evaluation. Recommendations alone do not modify the test-set files.

Then return to the completion gate. Do not silently mark the review complete.

Outside Flow R2, preserve `review_requested` and skip this gate. If a workspace
set was tagged and the user cancelled before promotion or push, a later
**"push {set name}"** request must resume promotion/push with the existing tag.
Say:

> **{set name}** is already marked for review locally. I’ll keep that status
> and continue the push so it becomes available to reviewers.

Do not offer **Mark review complete** in that resumed-maker flow.

If `review.json` is absent or already has `review_completed`, skip this gate and
continue normally. Never infer completion merely because edits passed quality
validation; completion requires the user's explicit choice in an active review.

## Step 7: Ask whether to push

Only after the update, CSV synchronization, validation, file review, and any
required Step 6a review-completion gate are complete, ask for every selected
set:

> The **{set name}** evaluation set is updated locally. Would you like to
> **push it to Copilot Studio now**?

Ask this even for workspace-level sets and even when no agent is currently
configured. Do not inspect or report agent configuration until the user answers.

### If the user declines

Confirm the local locations and finish without checking setup:

- `.mcs.yml`: the selected set folder.
- CSV: that source's `evaluations/exports/` folder.

### If the user chooses push

Only now read `.local/config.json` and check that:

1. `setup` is `"complete"`;
2. `agent.folder` exists;
3. the agent folder has a `.baseline`; and
4. the required agent identity fields are present.

If configuration is missing or incomplete, do not attempt a push. Say:

> This test set is updated and saved locally, but an agent is not configured
> yet. Run `/setup` to connect the target agent, then ask me to push the
> **{set name}** evaluation set.

Keep all generated files unchanged so the user can resume after setup.

Before preparing the push, ask:

> Would you like to tag any selected test sets for review?

If yes, run the Flow R1 metadata command for each selected set before the dry
run. If the current request already followed Flow R1 or the selected set is
already `review_requested`, do not ask again. Preserve its existing status and
continue the push.

## Step 8: Prepare the selected set for push

### Set already owned by the configured agent

Continue with its existing `{agent.folder}/evaluations/{set}/` files.

### Workspace-level set

Promote it using copy-then-cleanup:

1. Run `python scripts/checkpoint.py "pre-push-workspace-evaluation"`.
2. Check both:
   - `{agent.folder}/evaluations/{set}/`
   - `{agent.folder}/.baseline/evaluations/{set}/`

   If either exists, explain that the set already exists locally or in the
   deployed baseline. Show any baseline case files that are absent from the
   workspace set; pushing a replacement will delete those cases from Copilot
   Studio. Ask whether to replace the existing set or cancel. Never overwrite
   or delete existing cases silently.
3. Promote with:

   ```text
   python scripts/evaluation_promotion.py promote --set-name "{set}" --agent-folder "{agent.folder}"
   ```

   After explicit replacement approval, add `--replace`. This script copies
   the YAML and `review.json`, regenerates the agent CSV, and deliberately
   preserves the workspace source until the push succeeds.

If the same workspace source and an identical configured-agent staging copy
already exist while no deployed baseline exists, treat this as a resumed
promotion from a cancelled or failed push. Run the same
`evaluation_promotion.py promote` command; it returns `"resumed": true` and
reuses the staged copy. Continue to the scoped dry run; do not ask to mark the
review complete and do not describe the staging copy as proof that review
occurred.

The agent-folder copy becomes the source for `push.py`. Keep the workspace set
unchanged until the push reports full success.

## Step 9: Dry run and push

Build one scope argument for every selected set:

```text
--only "evaluations/{set}/*"
```

Run the scoped preview:

```text
python scripts/push.py --only "evaluations/{set}/*" --dry-run
```

For multiple selected sets, repeat `--only` once per set. Never use an unscoped
`push.py` command from the evaluation update, tagging, review, or promotion
flow. Unscoped push can include unrelated pending topic or workflow changes.

Show the output and get confirmation. Clearly identify any deletions within
the selected evaluation set as replacement of deployed cases.

If the scoped preview contains deletions, require one explicit confirmation:

> Replacing **{set name}** will delete these deployed test cases: {files}.
> Continue with the replacement?

The replacement choice in Step 8 counts as this confirmation only when it
listed the same files. After confirmation, run the scoped push with
`--force-delete` so `push.py` does not ask for the same deletion approval
again:

```text
python scripts/push.py --only "evaluations/{set}/*" --yes --force-delete
```

If the scoped preview has no deletions, omit `--force-delete`:

```text
python scripts/push.py --only "evaluations/{set}/*" --yes
```

Use `--yes` only after the user explicitly confirms the push in Step 7. Use
`--force-delete` only after the exact selected-set deletions have been shown
and approved. The scope ensures unrelated local topic or workflow deletions
remain untouched for a later push.

If the push fails, show the error and offer retry or checkpoint revert.

### Successful workspace promotion cleanup

   Only when `push.py --yes` exits successfully:

   Run:

   ```text
   python scripts/evaluation_promotion.py cleanup --set-name "{set}" --agent-folder "{agent.folder}"
   ```

   The script verifies the promoted agent copy before deleting only the exact
   workspace source and its matching workspace CSV files. Do not manually delete
   promotion paths. If cleanup refuses to run, preserve everything and report the
   error instead of guessing.

If the push fails, is cancelled, or only the dry run completes, do not perform
cleanup. The workspace source remains available for retry.

## Step 10: Final summary

Report each updated set, its source, changed-case count, CSV location, and
whether it was:

- Kept local by user choice.
- Waiting for `/setup`.
- Promoted from the workspace, pushed, and removed from workspace staging.
- Updated and pushed from the configured agent folder.

For every set that was kept local, is waiting for `/setup`, had only a dry run,
or whose push failed/cancelled, end with this mandatory reminder:

> ⚠️ To make this test set available to an authorized judge or SME, it must be
> promoted to the configured agent and successfully pushed to Copilot Studio.
> The CSV and local evaluation files are not shared yet. Say
> **"push {set name}"** when you are ready.

Do not stop showing the reminder merely because the set now exists inside the
configured agent's local `evaluations/` folder. Remove it only after
`push.py --yes` completes successfully. For a successful push, state:

> ✅ This test set is now available in Copilot Studio for authorized judges and
> SMEs.

Exception: when this push records `review_completed`, do not mention judges or
SMEs. Instead state:

> ✅ Review completed and pushed successfully. You can now run this test set or
> view its evaluation run history.
