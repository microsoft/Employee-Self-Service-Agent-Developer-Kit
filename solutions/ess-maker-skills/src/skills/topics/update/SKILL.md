# Update Topic

Update one mapped topic in the selected editable Dev agent from an ordinary `.mcs.yml` draft. Preserve native identity, unrelated behavior, active state, and newer non-overlapping remote content. Do not activate or publish as a save side effect.

Read [experience-contract.md](../experience-contract.md) before interacting with the maker. Use its change-focused Update summary, initial routing-conflict decision when applicable, otherwise the short Push topic to agent / Keep as draft control, topic outcome heads, authorization rules and state-aware testing continuation.

## Boundaries

- Require completed canonical setup for the selected Dev agent.
- Resolve the topic through `.component-map.json`; never retarget by display name.
- Read the current native topic before editing.
- Preserve unrelated dialog fields, action IDs, triggers, metadata, expressions, and state.
- Re-evaluate stale review suggestions against the current actions before applying them.
- Treat routing overlap and instruction mismatch as advisory. Do not auto-deactivate or overwrite another topic.
- Do not author Power Automate flows.

## 1. Resolve and read the selected topic

Infer or carry the selected topic from the request and context when unambiguous. Discover available local mapped and current native topics using `topic_authoring.py list`. Topic selection is a fallback, not a mandatory question: when needed, offer discovered titles with short purposes plus free text for a name or description. Disambiguate and resolve exact native identity before proceeding; do not require name recall.

Read `.local/config.json`, resolve exactly one mapped path, and run:

```powershell
python scripts\topic_authoring.py read --topic "{agent.folder}\topics\{Topic}.mcs.yml" --output ".local\topic-authoring\topic-before.json" --yaml-output ".local\topic-authoring\remote-topic.mcs.yml"
```

The returned component is authoritative current state. The optional projection is evidence, not permission to overwrite the working draft. Read the full local draft and surrounding components whose contracts matter.

## 2. Draft and review the change

Immediately before applying the intended edit, record this authoring invocation once, including when the maker later keeps the draft locally:

```powershell
python scripts/emit_capability.py topic_update
```

Telemetry is best-effort and must not block authoring. Previewing, saving or recovering the same proposal adds no authoring count. When this owner receives an unchanged draft for a later Push, skip this emission and reuse the draft; do not treat saving it as new authoring.

Edit `{agent.folder}/topics/{Topic}.mcs.yml`. Preserve behavior outside the requested scope.

Ask in normal chat only for missing requirements. Prepare the shared change-focused Update summary with affected Behavior, Inputs, Outputs and Starts when, relevant before/after details, verified Unchanged facts, applicable Notes and Routing Conflicts sections, and the full-draft link. Render it after the current instruction-alignment assessment and native preview, before the separate short decision control.

Warn about routing-changing overlap. Skip response-only overlap scans and reuse still-current assessments instead of repeating unchanged warnings.

## 3. Assess instruction alignment

Read current native instructions:

```powershell
python scripts\agent_instructions.py read --output ".local\topic-authoring\instructions-before.json"
```

Assess intent/scope, routing/disambiguation, policy/confirmation, response/grounding, fallback, and identity/existence. If the read fails, mark alignment unverified and offer best-effort supported testing collaboration. Do not claim an automated browser instruction reader.

When the maker selects Resolve the routing conflict in the Agent Instructions, or the correction is already explicitly authorized, edit only the desired instructions in `{agent.folder}/agent.mcs.yml` and preview separately. Do not prepare it merely because a topic is being authored:

```powershell
python scripts\agent_instructions.py update --draft "{agent.folder}\agent.mcs.yml" --expected ".local\topic-authoring\instructions-before.json" --output ".local\topic-authoring\instructions-preview.json"
```

Ordinary authoring requires separate topic and instruction approvals. An unchanged approved Push batch or explicitly authorized in-scope debugging objective supplies its scoped consent as defined in the shared experience contract. Disclose a known mismatch, likely execution impact and separate suggested action under Routing Conflicts, and offer the shared initial routing-conflict decision before Push. A deliberately approved topic-only save may leave that mismatch unresolved. Use the shared targeted instruction-change preview and exact two-component review before saving either proposed change.

## 4. Preview and save

Preview without mutation:

```powershell
python scripts\topic_authoring.py update --draft "{agent.folder}\topics\{Topic}.mcs.yml" --expected ".local\topic-authoring\topic-before.json" --output ".local\topic-authoring\topic-preview.json"
```

Render the shared Update summary in normal chat. With a known instruction-routing conflict, follow it with the initial Resolve the routing conflict in the Agent Instructions / Push topic anyway / Keep as draft decision. Otherwise use the separate Push topic to agent / Keep as draft control. Reuse unchanged scoped batch/debugging approval rather than asking again. Keep as draft performs no remote save and uses **Draft kept locally. Agent unchanged.** only for a draft-only outcome. If another approved component was saved, use the shared composed report with actual per-component results.

After topic approval, including valid unchanged batch/debugging consent:

Follow **Push telemetry** in the shared experience contract. Reuse an enclosing approved batch's lifecycle without emitting again. Otherwise own the standalone batch, starting immediately before the approved save below and applying the shared terminal mapping after the final observed result, including any jointly approved instruction save. Keep capability authoring counts separate from this save lifecycle.

```powershell
python scripts\topic_authoring.py update --draft "{agent.folder}\topics\{Topic}.mcs.yml" --expected ".local\topic-authoring\topic-before.json" --yes --output ".local\topic-authoring\topic-result.json"
```

The adapter uses mapped identity, initial reconciliation, service concurrency, and authoritative readback. It does not automatically reapply HTTP 409/412 responses. It acknowledges verified saved content, retaining the captured submitted YAML when it matches readback. After a compatible merge, it synchronizes the working draft only if it still matches the submitted capture; later disk edits remain pending.

After the applicable instruction approval, including valid scoped batch/debugging consent:

```powershell
python scripts\agent_instructions.py update --draft "{agent.folder}\agent.mcs.yml" --expected ".local\topic-authoring\instructions-before.json" --yes --output ".local\topic-authoring\instructions-result.json"
```

Select the presentation from the approval scope. A topic and routing correction approved together use the shared composed Push report, including the complete instruction-save statement in its row and the conflict assessment and testing readiness in the trailer. Do not stack topic and instruction outcome blocks. Outside composed Push, use the shared truthful topic or instruction outcome block with its full statement and paragraph structure, including the no-write outcome when authoritative verification shows the requested content already exists without a new remote write. A successful instruction save is not proof of topic execution. Preserve known remote outcome separately from local bookkeeping or output failures. Do not auto-refresh setup, overwrite later local edits from remote content, or invent rollback/replay behavior.

Unchanged-intent recovery does not require approval merely because another operation is needed. For materially changed target, behavior, scope or treatment of conflicting edits, follow the shared recovery rule: report the actual save outcome and re-render the change-focused Update summary from step 2 with Title, Agent, fresh current/proposed details, preservation facts and Full draft before obtaining the specific new decision. Do not reduce the re-review to conflicting reply excerpts alone.

## 5. Testing and evaluation handoff

After a confirmed push, honor the initial routing-conflict decision. Only for a newly discovered or materially changed conflict, follow the shared combined routing-conflict/testing decision; otherwise use the ordinary state-aware testing continuation. Push topic anyway carries the declined correction into later authorized testing, but does not itself authorize testing. A test-anyway choice enters testing directly with that exclusion; do not introduce another testing offer or repair the declined conflict. If testing is already requested and `scripts/native_topic_test.py` is installed, carry this selected topic, intended behavior and authorized editable scope directly into `src/skills/topics/test/SKILL.md` without repeating the testing offer or topic selection. An inactive topic still requires explicit activation consent; honor no-activation and test-only requests. Otherwise report conversation acceptance as pending. Do not publish.

At the end of the authoring iteration, identify relevant affected evaluation cases across sets, including routing, negative, fallback, and cross-topic cases. A topic-only save may leave disclosed evaluation mismatches. Separately requested evaluation changes remain owned by `src/skills/evaluations/dispatcher/SKILL.md`.
