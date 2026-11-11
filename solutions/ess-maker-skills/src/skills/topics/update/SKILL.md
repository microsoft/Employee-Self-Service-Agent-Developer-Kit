# Update Topic

Update one mapped topic in the selected editable Dev agent from an ordinary `.mcs.yml` draft. Preserve component identity, unrelated behavior, active state, and newer non-overlapping remote content. Do not activate or publish as a save side effect.

Read the [shared foundation](../experience-contract.md) before interacting with the maker. Apply its Text-response authoring scope, authoring policy and authorization rules. Before drafting, read [Response wording and local drafts](../authoring-experience.md#response-wording-and-local-drafts). Load the other linked references at the steps that need them, not all upfront.

## Boundaries

- Require completed canonical setup for the selected Dev agent.
- Resolve the topic through `.component-map.json`; never retarget by display name.
- Read the current saved topic before editing.
- Preserve unrelated dialog fields, action IDs, triggers, metadata, expressions, and state.
- Preserve supplied or accepted response wording and links outside the authorized wording change. Do not polish or paraphrase them without permission.
- Re-evaluate stale review suggestions against the current actions before applying them.
- Treat routing overlap and instruction mismatch as advisory. Do not auto-deactivate or overwrite another topic.
- Do not author Power Automate flows.

## 1. Resolve and read the selected topic

Infer or carry the selected topic from the request and context when unambiguous. Discover available local mapped and current saved topics using `topic_authoring.py list`. Topic selection is a fallback, not a mandatory question: when needed, offer discovered titles with short purposes plus free text for a name or description. Disambiguate and resolve exact component identity before proceeding; do not require name recall.

Read `.local/config.json`, resolve exactly one mapped path, and run:

```powershell
python scripts\topic_authoring.py read --topic "{agent.folder}\topics\{Topic}.mcs.yml" --output ".local\topic-authoring\topic-before.json" --yaml-output ".local\topic-authoring\remote-topic.mcs.yml"
```

The returned component is authoritative current state. The optional projection is evidence, not permission to overwrite the working draft. Read the full local draft and surrounding components whose contracts matter.

Apply the shared **Authoring policy for this release** to this component identity before editing and again before saving. Check the requested and resulting topic against the shared authoring scope before editing. If preserving existing behavior would leave it outside that boundary, explain the limitation and seek an in-scope request rather than silently deleting or rewriting that behavior.

## 2. Draft and review the change

Immediately before applying the intended edit, record this authoring invocation once, including when the maker later keeps the draft locally:

```powershell
python scripts/emit_capability.py topic_update
```

Telemetry is best-effort and must not block authoring. Previewing, saving or recovering the same proposal adds no authoring count. When this owner receives an unchanged draft for a later Push, skip this emission and reuse the draft; do not treat saving it as new authoring.

Edit `{agent.folder}/topics/{Topic}.mcs.yml`. Preserve behavior outside the requested scope.

Ask in normal chat only for missing requirements. Prepare the [change-focused Update summary](../authoring-experience.md#update-summary). Render it after the current instruction-alignment assessment and save preview, before the separate short decision control.

Warn about routing-changing overlap. Skip response-only overlap scans and reuse still-current assessments instead of repeating unchanged warnings.

## 3. Assess instruction alignment

Read current saved instructions:

```powershell
python scripts\agent_instructions.py read --output ".local\topic-authoring\instructions-before.json"
```

Assess intent/scope, routing/disambiguation, policy/confirmation, response/grounding, fallback, and identity/existence. If the read fails, mark alignment unverified and offer best-effort supported testing collaboration. Do not claim an automated browser instruction reader.

When the maker selects Resolve the routing conflict in the Agent Instructions, or the correction is already explicitly authorized, edit only the desired instructions in `{agent.folder}/agent.mcs.yml` and preview separately. Do not prepare it merely because a topic is being authored:

```powershell
python scripts\agent_instructions.py update --draft "{agent.folder}\agent.mcs.yml" --expected ".local\topic-authoring\instructions-before.json" --output ".local\topic-authoring\instructions-preview.json"
```

Ordinary authoring requires separate topic and instruction approvals. For a known mismatch, read [Routing Conflicts](../authoring-experience.md#routing-conflicts) and the [initial routing-conflict decision](../authoring-experience.md#initial-routing-conflict-decision). A deliberately approved topic-only save may leave that mismatch unresolved. When preparing a correction, use the [targeted instruction-change preview](../authoring-experience.md#targeted-instruction-change-preview-and-approval) and [Push review](../push-experience.md#entry-inventory-and-choices) before saving either proposed change. Reuse unchanged scoped batch/debugging consent from the shared foundation.

## 4. Preview and save

Preview without mutation:

```powershell
python scripts\topic_authoring.py update --draft "{agent.folder}\topics\{Topic}.mcs.yml" --expected ".local\topic-authoring\topic-before.json" --output ".local\topic-authoring\topic-preview.json"
```

Render the completed Update summary and use the [Topic save decision](../authoring-experience.md#topic-save-decision), including its applicable wording or routing branch. Keep the summary in normal chat and the decision control separate. Revisions return to a fresh preview and the shared decision before saving; reuse unchanged scoped batch/debugging approval rather than asking again. Keeping a draft performs no remote save. Use [Topic outcomes](../authoring-experience.md#topic-outcomes) for a draft-only result or the [composed report](../push-experience.md#composed-push-report-composed_push_report) for partial saves.

After topic approval, including valid unchanged batch/debugging consent:

Read [**Push telemetry**](../push-experience.md#push-telemetry) before execution. Reuse an enclosing approved batch's lifecycle without emitting again. Otherwise own the standalone batch, starting immediately before the approved save below and applying the shared terminal mapping after the final observed result, including any jointly approved instruction save. Keep capability authoring counts separate from this save lifecycle.

```powershell
python scripts\topic_authoring.py update --draft "{agent.folder}\topics\{Topic}.mcs.yml" --expected ".local\topic-authoring\topic-before.json" --yes --output ".local\topic-authoring\topic-result.json"
```

The adapter uses mapped identity, initial reconciliation, service concurrency, and authoritative readback. It does not automatically reapply HTTP 409/412 responses. It acknowledges verified saved content, retaining the captured submitted YAML when it matches readback. After a compatible merge, it synchronizes the working draft only if it still matches the submitted capture; later disk edits remain pending.

After the applicable instruction approval, including valid scoped batch/debugging consent:

```powershell
python scripts\agent_instructions.py update --draft "{agent.folder}\agent.mcs.yml" --expected ".local\topic-authoring\instructions-before.json" --yes --output ".local\topic-authoring\instructions-result.json"
```

Report through [Topic outcomes](../authoring-experience.md#topic-outcomes), including its verified no-write outcome, and, when applicable, [Instruction-push outcomes and testing](../authoring-experience.md#instruction-push-outcomes-and-testing). A joint approval uses the [composed Push report](../push-experience.md#composed-push-report-composed_push_report), not stacked owner blocks. Preserve known remote outcome separately from local bookkeeping or output failures. Do not auto-refresh setup, overwrite later local edits from remote content, or invent rollback/replay behavior.

Unchanged-intent recovery does not require approval merely because another operation is needed. For materially changed target, behavior, scope or treatment of conflicting edits, follow the shared recovery rule: report the actual save outcome and re-render the change-focused Update summary from step 2 with Title, Agent, fresh current/proposed details, preservation facts and Full draft before obtaining the specific new decision. Do not reduce the re-review to conflicting reply excerpts alone.

## 5. Testing and evaluation handoff

Read [Topic testing continuation](../testing-experience.md#topic-testing-continuation) when reaching this handoff. Carry the selected topic, latest intended behavior, actual save/state, existing authorization and declined corrections. Check `scripts/native_topic_test.py` before offering runnable testing; if unavailable, report conversation acceptance as pending. Enter [the testing owner](../test/SKILL.md) only within the shared consent rules. Do not activate or publish as a save side effect.

At the end of the authoring iteration, identify relevant affected evaluation cases across sets, including routing, negative, fallback, and cross-topic cases. A topic-only save may leave disclosed evaluation mismatches. Separately requested evaluation changes remain owned by `src/skills/evaluations/dispatcher/SKILL.md`.
