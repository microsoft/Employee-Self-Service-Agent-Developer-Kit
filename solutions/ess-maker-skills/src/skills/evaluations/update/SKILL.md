# Update Evaluation Skill

Update evaluation test sets from either the workspace-level catalogue output or
a configured agent. Keep `.mcs.yml` and CSV representations synchronized.
Read `src/skills/evaluations/experience-contract.md` for shared presentation,
method admission, quality copy, and four maker actions. Run and Request Review
include required scoped deployment through
`src/skills/evaluations/deployment-flow.md`. Explicit standalone evaluation push
remains available. Local editing never automatically deploys.

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
- Never deploy until the user selects Run, Request Review, explicit push, or
  reviewer completion and the required scope/side-effect approvals are obtained.
- Promote a workspace-level set only for that selected action. Promotion
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
- Never finish immediately after displaying test cases. Makers receive the
  shared four actions; the Edit experience visibly includes adding cases.
  Keep/cancel remains a no-op. Reviewers must receive an explicit choice to
  provide feedback, suggestions, or recommendations, or complete review
  without feedback.

## Review-intent routing

Before the normal update flow, inspect the user's intent:

- **Tag for review / send for review / Mark this test set ready for review** → follow **Flow R1** below.
- **Review assigned test sets / act as judge or SME** → follow **Flow R2**.
- **Run this test set in Copilot Studio** -> hand exact selected context to
  `src/skills/evaluations/run/SKILL.md` Flow A; do not tag or push here as well.
- **Run another quality review** -> select the exact set if needed, then follow
  Step 5 and return to the shared maker actions without mutation or deployment.
- **Explicitly push an evaluation set** -> discover/select the exact set and
  continue through Step 7 with helper action `push`, preserving review state.
- Otherwise continue with Step 1.

Review state and review activity are separate:

- `review_requested` records review intent. Dataverse publishes the marker
  through the existing push; native MinimalBot retains it locally only.
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
  status from the configured agent baseline on Dataverse. Native review
  sidecars are not copied into the deployed `.baseline`; its server review
  status remains absent.

Use `nextAction` from the command. The remote-state meanings below apply to
Dataverse; for native label review state as local and do not infer a remotely
published tag or cross-user discovery:

| Next action | Meaning | User-facing action |
|---|---|---|
| `push_review_request` | Local tag is requested, but Copilot Studio is untagged or the set is not deployed | Resume Request Review and its required deployment |
| `review` | Local and deployed status are both `review_requested` | Offer the reviewer feedback/completion workflow |
| `push_review_completion` | Review was completed locally but Copilot Studio still has the requested tag | Resume the confirmed review-completion deployment |
| `run_or_view_results` | Local and deployed status are both `review_completed` | Offer run or result-history actions |

Never derive these actions from `localStatus` alone on Dataverse. If another user may have
changed the set since the last pull, refresh first; the baseline must represent
the latest retrieved Copilot Studio state before entering Flow R2.
For native, preserve the existing local review workflow and pending-review Run
gate; `deployedReviewStatus=null` does not erase local intent or prove completion.
Use the selected local `review.json` for an explicitly entered native R2 review,
not a remote `nextAction=review` requirement. A local requested marker keeps
Run blocked; explicit local completion can proceed through verified YAML
push/reuse. Do not repeatedly push to obtain an unsupported shared marker.

### Flow R1 — Tag selected test sets for review

Before asking the user to tag a set, explain:

> **Mark for review** indicates that the test set is ready for another
> reviewer, judge, or SME to inspect and provide feedback, suggestions, or
> recommendations. The maker remains responsible for editing the test set. The
> tag must be pushed to Copilot Studio before it is shared with other users on
> Dataverse. Native push uploads the test-set YAML but retains review status
> locally; it does not publish shared review metadata.

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
5. Follow `src/skills/evaluations/deployment-flow.md` before remote mutation.
   Native MinimalBot uses the existing insert API, with new-copy/old-copy
   behavior and its local-only review warning reported after deployment. The
   selected Request Review action authorizes the required non-destructive push;
   do not ask for another confirmation. Stop for approval only if the preview
   reveals destructive Dataverse deletions or replacement of different local
   files. Do not add a native review-persistence or in-place-update prerequisite.
6. Continue Step 7 with helper action `request-review` in the same workflow. The
   deployment owner persists `review_requested` using the existing
   `evaluation_review.py --set-folder "{set-folder}" --status review_requested`
   operation. Dataverse includes review-only changes and verifies the deployed
   marker; native preserves the sidecar locally and pushes/reuses YAML without
   serializing shared review metadata.
   If already `review_requested`, do not ask again or change it to completed.
   Do not ask an independent "push now?" question or require another command.
7. After verified Dataverse success with `reviewMetadataPersisted=true` say:

   > **{set name} is ready for review in the connected agent.** Share the set name
   > with an authorized reviewer so they can open the evaluation review flow.
   > This has not run the evaluation or sent a reviewer notification.

   For native success with `reviewMetadataPersisted=false`, say instead:

   > **{set name} was uploaded/reused as {actual deployed ID}.** Review is
   > requested locally. Native push uploads YAML only; shared review state was
   > not published. {reviewWarning} This has not run the evaluation or sent a
   > reviewer notification.

   Use the actual `deploymentBehavior`, not the literal "uploaded/reused"
   alternative, and state that the old remote copy remains for a new copy.

On failure/cancellation, say the review request is local/pending synchronization
only if it was actually saved; report the actual failure and preserve files.
Do not infer remote availability from `review.json`, staging, or a dry run.

On Dataverse, the pushed parent description contains:

```text
[ADK-REVIEW status=review_requested]
```

### Flow R2 — Review assigned test sets

When a user asks to review test sets, follow the existing discovery workflow.
Native review sidecars can support the local workflow; they do not establish
cross-user availability. Explain that distinction rather than blocking review
or inventing remote metadata. Use `src/skills/evaluations/deployment-flow.md`
for backend-specific outcome copy.

For a Dataverse configured agent, automatically refresh before discovery
unless `fetch_and_setup.py --refresh` already completed successfully in the current turn:

```text
python scripts/fetch_and_setup.py --refresh
```

This refresh creates a checkpoint before updating local files and rebuilds the
baseline from the latest Copilot Studio state. Do not ask the reviewer to pull
manually or require an extra `/setup --refresh` step. If the refresh fails,
report the actual error and stop rather than reviewing stale local data.

After a successful Dataverse refresh, run:

```text
python scripts/evaluation_review.py --list --status review_requested
```

Use its JSON output to list eligible requested sets for workspace/current-agent
discovery. Do not substitute an ad hoc `review.json` glob or widen to other agents.
Local-only requests are not proof of deployed review availability.
For native local review, use `python scripts/evaluation_review.py --list-all`
and select returned rows with `localStatus=review_requested`. Do not require a
remote review refresh or a matching baseline marker: the sidecar is retained
only in the local/promoted folder and is not copied into deployed `.baseline`.
Label those rows **Review requested locally**. An empty local review list is
not evidence that no remote colleague requested review; the existing API does
not publish that shared state. Do not promise cross-user discovery.

**Hard entry gate:** display the tagged-set table and wait for the user to
select a set before reading all category files or invoking quality validation.
The word "review" alone never means "run the evaluation quality validator."
Use the available structured choice control with one option per returned set.
Ask: **"Which test set would you like to review?"** Do not use "Which pending
test set..." in the user-facing question.

For each selected set:

1. Validate the method and regenerate the current CSV through the strict
   `evaluation_csv.py` command in the shared **CSV synchronization** contract
   (which uses `generate_set_csv`), then show its actual downloadable link before
   displaying any prompts or expected responses.
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
   conversation, retaining all earlier feedback for this same selected set.
   State that the maker remains responsible for applying the
   official changes, validating them, pushing the set, and running it. Do not
   claim that conversational recommendations were automatically written to the
   test-set description or source files.
4. Follow **Step 6a: Review completion gate**. Ask whether to provide more
   feedback or finish; never silently complete review after receiving feedback.
5. Explicit completion continues through Step 7 as reviewer completion
   in the same workflow, preserving scoped approval and deployment verification.
   Dataverse completion becomes shared after the marker is pushed. Native
   completion remains local after YAML deployment; retain and explain the
   returned review warning rather than claiming shared completion.

On Dataverse, the existing push replaces only the ADK marker with:

```text
[ADK-REVIEW status=review_completed]
```

The human-authored description remains unchanged. Completed sets no longer
appear in the pending-review list.

## Step 1: Discover all evaluation sets

If the current user explicitly selected an exact folder/source in generation
or the shared maker menu, retain that selected context and go to Step 2. Do not
rediscover by display name and accidentally switch to a same-name set. Confirm
again if the target/context has changed.

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
> | 1 | Compensation | Workspace | 8 | Local YAML + CSV; choose next action after update |
> | 2 | Topic Triggering | Configured agent | 24 | YAML + CSV; choose next action after update |

If the same set name exists in both locations, include both rows and their full
source labels. If no sets are found, explain that there is nothing to update and
suggest creating an evaluation set first.

Ask which set or sets the user wants to update using the structured choice
control. Each option must include the test-set name, source, and case count.

## Step 2: Identify the requested changes

Reject an unsupported method-change request before applying any mutation, using
the shared Compare Meaning-only error copy. Preserve the parent and threshold;
never silently translate a requested method into another method.

For each supported selected set, use the strict export CLI:

```text
python scripts/evaluation_csv.py --evaluation-folder "{set-folder}" --exports-folder "{exports-folder}"
```

It calls `evaluation_csv.generate_set_csv`. Regenerate from the authoritative
YAML and show the downloadable CSV link first, using the JSON `csv` path:

> Here's the current evaluation set for **{set name}**:
>
> [{YYYYMMDD}_{Evaluation_Set_Display_Name}.csv]({csv-path})
>
> The CSV file is for preview purposes only. Tell me which prompts, scenarios,
> or rows you want to modify; changes are made to the source evaluation files
> and automatically reflected in the CSV.

If admission fails, report the exact invalid/missing field and preserve the last
valid CSV; do not link it as a freshly synchronized preview. A requested
prompt/assertion correction may continue by reading the affected YAML directly
and validating the complete proposed result before saving. An unsupported
method is not silently converted, and no invalid set is advertised as runnable.

Then continue with the existing detailed edit experience and show its cases:

> | # | Input | Expected output | File |
> |---|---|---|---|
> | 1 | "What is my employee ID?" | "The agent should display..." | `employee-id.mcs.yml` |

Read both `input` and `expectedOutput` from every EvaluationData file before
presenting the cases. The expected response is required context, not optional.

If this is an explicit edit/add handoff, show structured editing choices:

1. **Edit existing prompts or expected responses**
2. **Add test cases to this set**
3. **Keep it unchanged**

Otherwise show **Four maker actions** from the shared experience contract.
**Edit this test set** opens these editing choices. Keep/cancel does not mutate
or deploy. An add request does not require selecting an old case to overwrite.
Gather each new prompt and meaningful expected response before Step 3.

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

Removal retains the delete skill's existing restrictions; do not implement
deletion or Excel ingestion here. Case identity is file plus row index, never
input text alone. Preserve duplicate inputs with distinct assertions.

If adding would exceed 100 cases, stop before writes and explain the limit.
Offer an explicitly chosen separate set/split, not automatic replacement,
truncation, or movement of old cases. For model-generated additional coverage,
show the shared pre-generation explanation before generating new cases.

Keep selection and editing as separate questions:

These existing-row selection steps do not apply to adding cases. For an add
request, collect only the new prompt and meaningful expected response.

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
python scripts/emit_capability.py evaluation_update
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

Before saving an edit, validate the proposed parent and complete case documents
with `validate_evaluation_documents` from `evaluation_method_policy`. Preserve
parent identity, valid threshold, review metadata, untouched files, and rows.
On validation failure, report the specific error without changing valid files.

For a new case, use the append helper rather than constructing a possibly
colliding filename:

```text
python scripts/evaluation_authoring.py add --evaluation-folder "{set-folder}" --input "{new prompt}" --expected-output "{new expected response}"
```

Pass user values as literal subprocess arguments, never executable shell text.
The helper checks all cases/capacity before writes, chooses a unique filename,
and appends a stable display order. It returns the actual case file and CSV.
If it reports the case saved but CSV synchronization failed, fix that error and
regenerate the CSV; do not add the same case again.

After all YAML edits, regenerate that set's CSV from its complete final
EvaluationData list:

- Workspace set: `workspace/evaluations/exports/`.
- Agent set: `{agent.folder}/evaluations/exports/`.
- Call `evaluation_csv.generate_set_csv` for the complete set. It owns
  `{YYYYMMDD}_{Evaluation_Set_Display_Name}.csv` naming, collisions, RFC-4180,
  formula protection, and validation before replacing an old export.
- Use the strict export CLI above for this synchronization; never use
  historical interoperability as a permissive feature fallback.
- Use the returned CSV path, not an independently reconstructed name.
- Keep only the allowed CompareMeaning method and preserve the parent's
  threshold. Do not create an independent CSV writer or General Quality fallback.

The YAML files are authoritative. Never update a CSV independently.
Do not ask for confirmation before synchronizing the CSV; perform it as part of
the same edit operation.

## Step 5: Quality validation

Invoke the evaluation validate subagent with every `.mcs.yml` file in each
affected set, plus the set name and source folder.

Display the exact compact **Post-generation quality report** scorecard from
`src/skills/evaluations/experience-contract.md` directly to the user without a
separate preamble, table, filename callout, or summary. Follow
`src/skills/evaluations/quality-fix-flow.md`; the "review step" referenced
there is Step 6 below.

If validation fixes change YAML, regenerate the matching CSV again before
continuing.

## Step 6: Review

For an edit/add, show a source-aware summary:

> | Set | Source | File | Field | Before | After |
> |---|---|---|---|---|---|
> | Compensation | Workspace | `base-pay.mcs.yml` | input | "salary" | "What is my base compensation?" |

For an edit/add, the local update has already been saved; do not ask to "apply"
it again. For a quality-only request with no fixes, do not claim files changed.
Render changed final cases/current CSV with the shared preview, then offer
**Four maker actions** from `src/skills/evaluations/experience-contract.md`.
If this was an explicit repeat quality review with no edits, avoid repeating
unchanged tables. Neither displaying the menu nor choosing Edit deploys.

## Step 6a: Review completion gate

Enter this gate only when the current interaction originated from **Flow R2**
or the user explicitly asked to complete an active review. Do not enter it
during Flow R1, a normal update, a normal push, or a resumed push.

In an active Dataverse Flow R2 review, require `nextAction=review`. For native
local review, require explicit selection from the local requested rows instead;
do not require a remote or baseline review marker. Then inspect the selected
set's `review.json`. If its status is `review_requested`, ask:

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

Continue to Step 7 as reviewer completion. The deployment owner first
validates the method and selected target, then uses the existing marker operation:
`evaluation_review.py --set-folder "{set-folder}" --status review_completed`.
Continue the same scoped push workflow: verify the Dataverse remote marker,
or report native local completion and actual YAML deployment without a shared
completion claim. Do not add another independent push menu.

### Provide feedback or recommendations for the maker

Capture the recommendations and present them back as a concise checklist tied
to the relevant prompts or expected responses. End with this mandatory
statement:

> Your recommendations are ready to hand back to the maker. The maker should apply the official test-case changes, push the updated set, and then run the evaluation. Recommendations alone do not modify the test-set files.

Then ask using the structured choice control:

> Would you like to provide more feedback, or is your feedback complete and
> ready for the maker to run this test set?

- **Provide more feedback**: append recommendations for the same set; retain
  earlier feedback without overwriting it.
- **Mark review complete**: explicitly enter the completion path above.

Do not silently mark the review complete. Conversation feedback is not a
persisted source edit or a reviewer notification.

Outside Flow R2, preserve `review_requested` and skip this gate. If a workspace
set was tagged and the user cancelled before promotion or push, a later
**"push {set name}"** request must resume promotion/push with the existing tag.
Say:

> **{set name}** is already marked for review locally. I’ll keep that status
> and continue the existing push. Dataverse publishes the review marker; native
> push retains review status locally and uploads the YAML only.

Do not offer **Mark review complete** in that resumed-maker flow.

If `review.json` is absent or already has `review_completed`, skip this gate and
continue normally. Never infer completion merely because edits passed quality
validation; completion requires the user's explicit choice in an active review.

## Step 7: Continue the selected deployment action

Enter only for Request Review, explicit evaluation push, or confirmed reviewer
completion. Run delegates to `run/SKILL.md` instead and owns its own deployment;
do not run the same push from both skills.

Read `src/skills/evaluations/deployment-flow.md` and follow it with the exact
selected folder/source and intended action. It owns setup/backend admission,
review reconciliation, promotion collisions, scoped dry-run visibility,
action-aware authorization, verified push/no-op, and success-only cleanup.
Flow R1 pushes immediately without another confirmation; never use an unscoped
push or skip destructive replacement/deletion approval.

For Flow R1, continue Request Review without another typed push command.
For Flow R2, preserve the user's explicit completion choice and persist it in
the same workflow. An ordinary or resumed explicit push preserves existing
review state; it must not create a request or mark review complete.

If configuration is missing, preserve all files, explain the prerequisite, and
resume the same selected action after setup. Do not require setup for local
editing, displaying choices, or keeping a set.

## Step 8: Final summary

Report the selected set, actual local/deployed state, changes, and current CSV
link. Use the shared local-only reminder after failure/cancellation or when
files remain local. Remove it only after verified successful deployment; a
staging copy and dry run do not make a set available to authorized reviewers.

For successful Flow R1 use its backend-specific reviewer handoff with no notification/run claim.
When this push records `review_completed` on Dataverse and verifies it, say:

> Review completed and pushed successfully. You can now run this test set or
> view its evaluation run history.

For native success, report the actual deployed ID and local completion with
`reviewMetadataPersisted=false`, `deployedReviewStatus=null`, and `reviewWarning`.
Do not say completion was published to other users. Run still checks the
existing pending-review, method, target, and connection requirements.

If completion deployment fails, state it is local/pending synchronization, not
ready to run. For ordinary maker completion, return to the shared four actions;
for reviewer feedback, preserve the more-feedback/completion loop instead.
