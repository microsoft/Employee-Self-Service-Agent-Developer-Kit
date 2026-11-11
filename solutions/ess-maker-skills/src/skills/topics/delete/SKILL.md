# Delete Topic

Delete one customer-authored topic from the selected editable Dev agent, keep its deletion local for a later Push, or discard an established unsaved local draft.

Read the [shared foundation](../experience-contract.md) and [Deletion experience](../deletion-experience.md) before reviewing the request. Apply **Authoring policy for this release** and the deletion reference's summaries, local-only variations, scoped consent and outcome heads. Template protection cannot be overridden by approval or a cleanup request.

## 1. Resolve the topic and effects

Require completed canonical setup for the selected Dev agent. Read `.local/config.json` and resolve the intended topic from the request and context. Use `topic_authoring.py list` and the selected workspace's component mapping. Clarify ambiguity with discovered titles and purposes; do not silently retarget by display name.

For an existing mapped topic, preview without mutation:

```powershell
python scripts\topic_authoring.py delete --topic "{agent.folder}\topics\{Topic}.mcs.yml" --output ".local\topic-authoring\topic-delete-preview.json"
```

The path can already be missing locally. The preview identifies the current topic, all contained components and the mapped working/baseline files affected by reconciliation. Review the complete scope, including any contained topics, against the shared policy. No remote or local deletion has occurred.

Read relevant current topics and instructions to assess references and practical effects. Use `agent_instructions.py read` for current instructions. Do not equate containment with arbitrary topic references or assume deletion repairs callers. Disclose an unavailable impact assessment as unverified. Do not expand deletion to referenced resources.

For an unmapped local draft, establish that it was never pushed before using the shared discard variation. Resolve ambiguous or uncertain remote state rather than treating missing tracking as absence.

## 2. Review and obtain scoped approval

Render `{delete_summary}` in normal chat, then the separate **Push deletion to agent** / **Keep deletion locally** / **Not now** control. For an unsaved draft, use **Discard local draft** / **Keep draft** instead.

An unchanged approved Push batch may already supply deletion consent when its displayed scope explicitly includes this topic and contained content. Do not request the same approval again. A general cleanup/debugging objective, selection or missing local file alone does not supply destructive consent.

After approval and before changing files or the agent, checkpoint:

```powershell
python scripts/checkpoint.py "pre-delete-{Topic}"
```

Record this deletion invocation once:

```powershell
python scripts/emit_capability.py topic_delete
```

Telemetry is best-effort. Preview, cancellation and recovery add no authoring count. When pushing an already-staged deletion, do not count staging again.

## 3. Apply only the chosen operation

### Keep deletion locally or discard a draft

Use file tools to remove only the approved working files. Recheck their contents against the reviewed scope before removal; preserve later edits and obtain a revised decision when needed.

For an existing topic, retain `.baseline` and `.component-map.json` unchanged. Report **Deletion kept locally. Agent unchanged.** Do not run a remote write or automatically proceed to Push.

For an established unsaved draft, remove only that draft and report **Local draft discarded. Agent unchanged.** No remote deletion or pending deletion tracking is created.

### Push deletion to agent

Read [**Push telemetry**](../push-experience.md#push-telemetry) before remote execution. Reuse an enclosing approved batch's lifecycle; otherwise own the standalone batch, starting immediately before the approved command and ending from its observed result.

```powershell
python scripts\topic_authoring.py delete --topic "{agent.folder}\topics\{Topic}.mcs.yml" --expected ".local\topic-authoring\topic-delete-preview.json" --yes --output ".local\topic-authoring\topic-delete-result.json"
```

The operation rereads current state, compares the complete reviewed deletion scope, submits the deletion through the AgentBuilder components API and verifies absence. The pre-write comparison is not an atomic compare-and-delete guarantee. If content or containment changed, return to review rather than silently accepting the new scope. Do not rely on the submitted component version to prevent concurrent changes.

Only verified absence permits local working-file, baseline and mapping cleanup. Later local edits are preserved and reported as incomplete reconciliation. This operation does not use Dataverse, `push.py --force-delete`, or the existing-topic update planner.

## 4. Interpret the outcome and recover

Use `{delete_outcome_heads}` from Deletion experience, or the enclosing [composed Push report](../push-experience.md#composed-push-report-composed_push_report). Preserve the service response, request ID, readback and causal errors for interpretation. An unsuccessful command or HTTP response alone does not establish that no deletion occurred.

For an uncertain result, inspect current components before any further mutation. Do not repeat deletion automatically. If inspection finds the topic already absent, report absence without attributing a new deletion to this operation.

When remote absence is verified but local reconciliation failed, use the captured preview and current workspace to complete only the outstanding approved local cleanup. Preserve newer files and mapping changes, unrelated edits and uncertainty. Do not repeat a remote write merely to repair bookkeeping or reset the whole baseline.

A checkpoint restores local files only. Recreating a topic in the agent is a separate approved operation, not a rollback implied by a local restore.

Do not invoke Copilot Studio Publish, activate content, or offer to test the deleted topic. Mention established remaining references or evaluation mismatches without silently fixing them. Finish without a generic next-action menu.
