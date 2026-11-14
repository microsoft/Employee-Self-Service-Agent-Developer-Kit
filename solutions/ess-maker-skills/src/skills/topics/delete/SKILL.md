# Delete Topic

Delete one eligible topic from the selected editable Dev agent, keep its deletion local for a later Push, or discard an established unsaved local draft.

Read the [shared foundation](../experience-contract.md) and [Deletion experience](../deletion-experience.md) before reviewing the request. Apply **Authoring policy for this release** and the deletion reference's summaries, local-only variations, scoped consent and outcome heads. Template protection cannot be overridden by approval or a cleanup request.

For a selected instruction correction, load [Authoring status updates](../authoring-experience.md#authoring-status-updates) and reuse its instruction-preparation and instruction-save definitions at the markers below. Deletion continues to own its own status definitions.

## 1. Resolve the topic and effects

Require completed canonical setup for the selected Dev agent. Read `.local/config.json` and resolve the intended topic from the request and context. Use `topic_authoring.py list` and the selected workspace's component mapping. Clarify ambiguity using the shared [Topic selection](../experience-contract.md#topic-selection) explanations and native control; do not silently retarget by display name.

For instruction-only cleanup after an established deletion or absence, carry the known exact topic and agent into [Routing cleanup after deletion](../deletion-experience.md#routing-cleanup-after-deletion). Do not require the deleted local file or repeat the deletion preview/write. Missing local mapping alone does not establish remote absence.

For an existing mapped topic, preview without mutation:

```powershell
python scripts\topic_authoring.py delete --topic "{agent.folder}\topics\{Topic}.mcs.yml" --output ".local\topic-authoring\topic-delete-preview.json"
```

The path can already be missing locally. The preview identifies the current topic, all contained components and the mapped working/baseline files affected by reconciliation. Review the complete scope, including any contained topics, against the shared policy. No remote or local deletion has occurred.

Read relevant current topics and instructions to assess references and practical effects. Use `agent_instructions.py read` for current instructions. Do not equate containment with arbitrary topic references or assume deletion repairs callers. Disclose an unavailable impact assessment as unverified. Do not expand deletion to referenced resources.

Identify instruction-routing references separately from other dependencies. A known dangling-routing consequence uses [Routing-conflict decision](../deletion-experience.md#routing-conflict-decision), not a warning that instructions must remain unchanged. Other referenced resources are not included in that correction automatically.

For an unmapped local draft, establish that it was never pushed before using the shared discard variation. Resolve ambiguous or uncertain remote state rather than treating missing tracking as absence.

{EMIT_STATUS_UPDATE: deletion-review}

## 2. Review and obtain scoped approval

Render `{delete_summary}` and its applicable choice explanations in normal chat, then use Deletion experience's separate native control. Use its routing-conflict branch when an instruction reference is known; otherwise use the default deletion decision. For an unsaved draft, use its draft-discard explanations and control instead.

Not now and Keep draft leave the selected state unchanged and return without checkpointing or deletion.

An unchanged approved Push batch may already supply deletion consent when its displayed scope explicitly includes this topic and contained content. Do not request the same approval again. A general cleanup/debugging objective, selection or missing local file alone does not supply destructive consent.

### Prepare a selected instruction correction

Only when the maker selects Resolve the routing conflict in the Agent Instructions, or the correction is already explicitly authorized, follow [Deletion-related instruction correction](../deletion-experience.md#deletion-related-instruction-correction). Reuse current saved instruction evidence or refresh it:

```powershell
python scripts\agent_instructions.py read --output ".local\topic-authoring\instructions-before.json"
```

Edit only the isolated desired instruction section in `{agent.folder}/agent.mcs.yml`, preserving unrelated content and drafts. Preview without writing remotely:

```powershell
python scripts\agent_instructions.py update --draft "{agent.folder}\agent.mcs.yml" --expected ".local\topic-authoring\instructions-before.json" --output ".local\topic-authoring\instructions-preview.json"
```

{EMIT_STATUS_UPDATE: instruction-preparation}

Render the shared exact-wording preview with deletion-specific state, then use the deletion reference's joint or instruction-only approval path. Resolution selection does not authorize deleting files, deleting the topic or saving instructions. Revisions return to fresh preview and scoped approval; reuse unchanged valid batch consent.

### Checkpoint the approved execution

After approval of topic removal and before executing it, checkpoint. For a jointly approved deletion and instruction correction, checkpoint before the first approved write. Instruction-only cleanup skips this deletion checkpoint and capability event:

```powershell
python scripts/checkpoint.py "pre-delete-{Topic}"
```

{EMIT_STATUS_UPDATE: deletion-checkpoint}

Continue only after the checkpoint is confirmed.

For an approved topic-removal operation, record this deletion invocation once. Instruction-only cleanup does not emit this event:

```powershell
python scripts/emit_capability.py topic_delete
```

Telemetry is best-effort. Preview, cancellation and recovery add no authoring count. When pushing an already-staged deletion, do not count staging again.

## 3. Apply only the chosen operation

### Keep deletion locally or discard a draft

Use file tools to remove only the approved working files. Recheck their contents against the reviewed scope before removal; preserve later edits and obtain a revised decision when needed.

For an existing topic, retain `.baseline` and `.component-map.json` unchanged. Use **DELETION KEPT LOCALLY AGENT UNCHANGED** after the status update below. Do not run a remote write or automatically proceed to Push.

For an established unsaved draft, remove only that draft and use **LOCAL DRAFT DISCARDED AGENT UNCHANGED** after the status update below. No remote deletion or pending deletion tracking is created.

After the selected local removal attempt and before its outcome report:

{EMIT_STATUS_UPDATE: local-removal}

### Push deletion to agent

When an instruction correction is also approved, follow the reviewed execution order from Deletion experience. The order of subsections here does not mandate write order. Preserve separately declined or pending changes.

Read [**Push telemetry**](../push-experience.md#push-telemetry) before remote execution. Reuse an enclosing approved batch's lifecycle; otherwise own the standalone batch, starting immediately before the approved command and ending from its observed result.

```powershell
python scripts\topic_authoring.py delete --topic "{agent.folder}\topics\{Topic}.mcs.yml" --expected ".local\topic-authoring\topic-delete-preview.json" --yes --output ".local\topic-authoring\topic-delete-result.json"
```

The operation rereads current state, compares the complete reviewed deletion scope and submits the deletion through the AgentBuilder components API. A successful HTTP 200 response completes the remote deletion (`writeAccepted: true`); no post-write read is required. The pre-write comparison is not an atomic compare-and-delete guarantee. If content or containment changed, return to review rather than silently accepting the new scope. Do not rely on the submitted component version to prevent concurrent changes.

HTTP success or an already-absent result from the pre-write inspection permits local working-file, baseline and mapping cleanup. Later local edits are preserved and reported as incomplete reconciliation. This operation does not use Dataverse, `push.py --force-delete`, or the existing-topic update planner.

{EMIT_STATUS_UPDATE: topic-deletion}

### Push an approved instruction correction

After the applicable instruction approval, including valid unchanged scoped batch consent, use the existing instruction operation. Read [Push telemetry](../push-experience.md#push-telemetry) before execution. Reuse the enclosing Push lifecycle; an instruction-only save owns its standalone lifecycle.

```powershell
python scripts\agent_instructions.py update --draft "{agent.folder}\agent.mcs.yml" --expected ".local\topic-authoring\instructions-before.json" --yes --output ".local\topic-authoring\instructions-result.json"
```

{EMIT_STATUS_UPDATE: instruction-save}

Apply the shared instruction concurrency and readback safeguards. Report instruction success, no-write, failure, uncertainty and local issues separately from deletion. Pause dependent work after a failed or uncertain prerequisite; do not repeat a known deletion or infer its success from an instruction save.

## 4. Interpret the outcome and recover

Use `{delete_outcome_heads}` from Deletion experience, or the enclosing [composed Push report](../push-experience.md#composed-push-report-composed_push_report). Preserve the HTTP status, service response, request ID and causal errors for interpretation. A new deletion is confirmed by `writeAccepted`, not the independent-readback `verified` flag. An unsuccessful command or HTTP response alone does not establish that no deletion occurred.

For an uncertain result, inspect current components before any further mutation. Do not repeat deletion automatically. If inspection finds the topic already absent, report absence without attributing a new deletion to this operation.

When deletion succeeded or absence was established but local reconciliation failed, use the captured preview and current workspace to complete only the outstanding approved local cleanup. Preserve newer files and mapping changes, unrelated edits and uncertainty. Do not repeat a remote write merely to repair bookkeeping or reset the whole baseline.

A checkpoint restores local files only. Recreating a topic in the agent is a separate approved operation, not a rollback implied by a local restore.

Do not invoke Copilot Studio Publish, activate content, or offer to test the deleted topic. Report established remaining references, declined corrections and evaluation mismatches without silently fixing them. For a newly discovered or materially changed routing conflict, use [Routing cleanup after deletion](../deletion-experience.md#routing-cleanup-after-deletion); do not repeat a declined unchanged correction. Finish without a generic next-action menu.
