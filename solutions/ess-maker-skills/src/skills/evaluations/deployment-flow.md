# Selected evaluation deployment

This is the single action-aware deployment sequence for Request Review, Run,
explicit evaluation push, and reviewer completion. Never invoke it merely to
display choices, discover sets, edit cases, or review local test-set quality.
Commands run from the solution root.

## Entry and admission

Preserve the exact selected folder/source, current agent/environment, intended
action, and local/deployed review state. Require explicit set selection, except
for Run's workflow handoff exception. Run selects its connection as defined in
`run/SKILL.md`. Do not switch targets or choose a connection that does not match
the signed-in account without the maker's choice.

The selected Request Review action, saved reviewer feedback, and the reviewer's
explicit **Mark review complete** choice each authorize their required
non-destructive, selected-set push. Preview and deploy immediately without
showing a separate scope confirmation or asking "would you like to push?" or
"publish the completed review status?". Run and explicit push retain their
existing confirmation rules. These review pushes must still stop for explicit
approval when the preview reveals destructive Dataverse deletions or
replacement of different local files; after approval, preview again with the
approved flags before deploying.

1. Run `python scripts/evaluation_method_policy.py --evaluation-folder "{set-folder}"`.
   On failure, stop before staging, export replacement, tagging, or remote writes.
   Do not repair methods automatically or omit unsupported cases.
2. Require completed canonical setup for the active agent and its configured
   identity/baseline before deployment. Preserve local files if setup is absent;
   after setup, resume the intended action on the same set, not a separate push.
3. Reconcile the selected set's `localStatus`, `deployedStatus`, and `nextAction`
   using `evaluation_review.py --list-all`. Ordinary Run never creates a review
   request or marks review complete. Pending-review gates remain effective.
4. Use the existing push APIs for the selected backend. Dataverse `push.py`
   persists `review.json` in the evaluation-parent description, preserving
   human-authored description text. Native MinimalBot uploads YAML through
   `BotComponentInsert`: new or changed YAML creates a new deployed copy and
   leaves the old remote copy intact. Unchanged YAML uses verified reuse;
   review-only changes use `BotComponentUpdate` on the existing parent description,
   retaining all set and case IDs. Both backends preserve human-authored
   description text and verify the shared ADK review marker on readback before
   recording `review.json` in the deployed `.baseline`.
   A sidecar or modified native set is not itself a deployment blocker. Keep ordinary pending-review Run
   gates, method validation, setup, identity verification, and consent.
   The Request Review helper may save local intent before reporting an actual
   setup/transport failure; do not equate saved intent with reviewer availability.

## Helper interface and consent

Use `scripts/evaluation_deployment.py`; do not reproduce its transport logic.
Its CLI actions are `request-review`, `run`, and `push`:

| Workflow | Helper action |
|---|---|
| Flow R1 Request Review | `request-review` (the helper owns the local requested marker) |
| Flow A Run | `run` |
| Explicit standalone push | `push`, preserving existing review state |
| Flow R2 completion | `push`, after the explicit completion marker step below |

Preview the exact selected set:

```text
python scripts/evaluation_deployment.py preview --set-folder "{set-folder}" --action "{action}"
```

Only `status=ready` is a successful preview, not a successful deployment. Show
`backend`, `environmentId`, `botId`, `sourceFolder`, `agentSetFolder`,
`requiresPush`, and all `changes.new`, `changes.modified`, `changes.deleted`.
Also inspect `promotion.required`, `promotion.replacesLocalFiles`, and
`promotion.changes` separately: replacing the configured agent's local files
is distinct from changing or deleting remote cases. For Request Review, an
ordinary promotion into an unused destination is authorized by the selected
action; a collision that replaces different local files still requires explicit
replacement approval.
For native previews, `new_copy`
means a new deployed ID will be created using the existing insert API and the
old remote copy will be retained; removed cases are absent only from the new
copy, not deleted from the old set. `reuse` means the helper will verify the
existing mapped copy and apply any confirmed review-only description update.
Request Review does not pause for confirmation for either
native behavior because neither deletes the retained remote copy. Report the
actual behavior after deployment. For native previews used by Run, explicit
push, or reviewer completion, show `deploymentBehavior` before consent. Show
`requiresPush=true` for a native review-only change means an in-place metadata
update, not a new set or a remote case deletion.

Keep the returned `confirmationToken` associated with that exact preview.
After a collision, `--replace` may be used to preview replacement only when the
user chooses that intent; show and approve the actual replacement diff.

For Request Review, deploy immediately with the preview token and `--yes`; the
maker's selected Request Review action is the authorization:

```text
python scripts/evaluation_deployment.py deploy --set-folder "{set-folder}" --action "request-review" --confirmation-token "{confirmationToken}" --yes
```

For explicit push, obtain scope/side-effect confirmation before running the same
command with action=`push`. Keep `--replace` consistent with approved local
replacement. Add
`--force-delete` only for exact approved remote deletions on the existing
Dataverse path, not case omissions in a native new copy. A stale-token error
means preview and confirm again, not bypassing the check. `blocked`, `cancelled`,
and `failed` are not successful deployment statuses.
Native `--force-delete` remains rejected; case omissions in a new copy use
normal scoped confirmation without that flag.

For **Run**, do not call `deploy` separately. Give the confirmed action=`run`
token, folder, replacement/deletion approvals, and explicitly selected
connection to `evaluation_runs.py run-prepared` as defined in `run/SKILL.md`.
That single command owns deployment and starts at most one run.

Even when `requiresPush=false`, continue through `deploy` (or `run-prepared`
for Run). Request Review proceeds immediately; other actions proceed after
their required consent. A preview alone is not synchronization proof: the
helper still verifies remote state and returns the actual deployed identity.
Do not skip this verification or force a redundant remote write.
This includes native metadata-only changes: verify YAML reuse, update the parent
description when needed, verify the shared marker, then synchronize the baseline.

For **Flow R2 completion**, first preview action=`push` to check the configured
target and selected scope. Stop on an actual setup/validation error, not the
an inferred review completion. After the reviewer explicitly chooses
completion, save the marker once:

```text
python scripts/evaluation_review.py --set-folder "{set-folder}" --status review_completed
```

Then preview action=`push` again and deploy with this new token without asking
again; the **Mark review complete** choice is the consent. Stop only for the
destructive cases above. Never reuse the pre-marker token. On both backends,
confirm `reviewMetadataPersisted=true` and
`sets[].deployedReviewStatus=review_completed` after success. Report the actual
uploaded/reused set ID; a status-only native update retains that ID.
Ordinary explicit push must never perform this marker step.

## Promotion, scoped deployment, and verification

The helper owns the following sequence. These underlying commands explain
scope and safeguards; do not run them again outside the helper or fall back to
an unscoped `push.py` call if preparation or verification fails:

1. Checkpoint before staging changes. For a workspace source, inspect both
   `{agent.folder}/evaluations/{set}/` and
   `{agent.folder}/.baseline/evaluations/{set}/`.
2. Show collisions and local-file replacement before promotion. On Dataverse,
   explain that pushing a replacement will delete those cases from Copilot
   Studio only when the preview lists remote deletions. On native, explain
   new-copy behavior and old-copy retention instead; do not describe missing
   cases in the new copy as remote deletion. Require explicit replacement
   approval; keep/cancel performs no mutation.
3. Promotion uses `evaluation_promotion.py promote`, preserving `review.json`
   and the workspace source. An identical staged copy from a failed/cancelled
   attempt is a resume, not a new set or proof of completed review.
4. The selected-set scope is `--only "evaluations/{set}/*"` for each selected
   set. The equivalent underlying preview is:

   ```text
   python scripts/push.py --only "evaluations/{set}/*" --dry-run
   ```

   Include Dataverse review-only metadata changes even if every case YAML is
   unchanged. Native review-only changes update the existing parent description.
   Never use an unscoped push: unrelated pending topics, workflows, and sets
   must remain local.
5. For Request Review, the selected action authorizes the underlying
   noninteractive push immediately. For other actions, run it after their
   required confirmation:

   ```text
   python scripts/push.py --only "evaluations/{set}/*" --yes
   ```

   Use `--yes --force-delete` only after showing and approving the exact selected
   Dataverse remote deletions. Prior replacement consent counts only for those
   same files. Preserve unrelated local topic or workflow deletions.
6. Verify the deployed identity and complete selected YAML content before
   reporting success or starting a run. Verify intended remote review markers
   on both backends; a local sidecar alone is not remote-marker evidence. Use the
   returned new ID for a native new copy, not the retained old remote ID.
   An unchanged reuse and any pending insertion retry retain their verified or
   confirmed planned IDs. A synchronized no-op requires verification; do not
   force a remote write or choose a same-name ID.
7. Only after verified success, use `evaluation_promotion.py cleanup` for a
   workspace promotion. Do not manually delete promotion paths. A dry run,
   failure, cancellation, or failed verification never authorizes cleanup.

Success is only `status=pushed` or `status=up_to_date`, with matching returned
`sets[].sourceFolder`, `agentSetFolder`, and a verified `testSetId`. Dataverse
and native success report `reviewMetadataPersisted=true`; Request Review also
requires `deployedReviewStatus=review_requested`. Report native
`deploymentBehavior`, the actual deployed ID, and retained old copy when applicable.
Never report shared review availability or completion before remote verification.
The helper owns promotion cleanup; report `cleanupWarning` truthfully and retain
its recovery instructions instead of manually deleting files.

After verified success, the set is available in Copilot Studio but no run
exists yet. Link only to the returned `evaluationPageUrl`, labeled
"[Open the Evaluation page in Copilot Studio]({evaluationPageUrl})". Never
present it as a run link, and never build a run link before a run starts. If
`evaluationPageUrl` is absent or `null`, omit the link. Show no link after a
failed or unverified deployment, because the set is not confirmed in Copilot
Studio.

## Continue exactly the intended action

| Action | After verified deployment |
|---|---|
| Request Review / Flow R1 | On either backend, confirm the verified deployed requested marker and give reviewer handoff. Neither starts a run or sends notification |
| Run | Pass the verified deployed set identity to `run/SKILL.md`; complete connection prerequisites and start exactly once |
| Explicit evaluation push | Report deployment only, preserving any existing review state; do not tag or run. After verified success, run `python scripts/analytics_pointer.py --post-deploy` and show any stdout verbatim. This is a one-time reminder for the current DA environment/agent association; it is silent after completion |
| Reviewer completion / Flow R2 | On either backend, verify deployed completion. Offer Run subject to the existing review/connection gates |

On error or cancellation, distinguish saved locally, staged, deployed, and
started. Preserve the source and retry context; never claim review availability
or start a run after failed verification. If deployment succeeded but run start
failed, report both facts and retry the start only after resolving its failure.
For a failure with `remoteCommitted=true`, report that the remote write committed
but local tracking/synchronization failed. With `deploymentMayHaveCommitted`,
report uncertainty rather than claiming rollback or no change. In both cases,
preserve source files and the returned recovery details; reconcile actual state
through the helper before any retry, never blindly repeat the remote write.
