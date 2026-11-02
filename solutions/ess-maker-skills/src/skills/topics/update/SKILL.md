# Update Topic

Update one mapped topic in the selected editable Dev agent from an ordinary `.mcs.yml` draft. Preserve native identity, unrelated behavior, active state, and newer non-overlapping remote content. Do not activate or publish as a save side effect.

Read [experience-contract.md](../experience-contract.md) before interacting with the maker. Use its change-focused Update summary, short Push topic to agent / Keep as draft control, topic outcome heads, authorization rules and state-aware testing continuation.

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

Edit `{agent.folder}/topics/{Topic}.mcs.yml`. Preserve behavior outside the requested scope.

Ask in normal chat only for missing requirements. Prepare the shared change-focused Update summary with affected Behavior, Inputs, Outputs and Starts when, relevant before/after details, verified Unchanged facts, Notes and the full-draft link. Render it after the current instruction-alignment assessment and native preview, before the separate short decision control.

Warn about routing-changing overlap. Skip response-only overlap scans and reuse still-current assessments instead of repeating unchanged warnings.

## 3. Assess instruction alignment

Read current native instructions:

```powershell
python scripts\agent_instructions.py read --output ".local\topic-authoring\instructions-before.json"
```

Assess intent/scope, routing/disambiguation, policy/confirmation, response/grounding, fallback, and identity/existence. If the read fails, mark alignment unverified and offer best-effort supported testing collaboration. Do not claim an automated browser instruction reader.

When needed, edit only the desired instructions in `{agent.folder}/agent.mcs.yml` and preview separately:

```powershell
python scripts\agent_instructions.py update --draft "{agent.folder}\agent.mcs.yml" --expected ".local\topic-authoring\instructions-before.json" --output ".local\topic-authoring\instructions-preview.json"
```

Ordinary authoring requires separate topic and instruction approvals. An unchanged approved Push batch or explicitly authorized in-scope debugging objective supplies its scoped consent as defined in the shared experience contract. A known mismatch may remain after a deliberately approved topic-only save; disclose its issue, practical effect and suggested action in Notes.

## 4. Preview and save

Preview without mutation:

```powershell
python scripts\topic_authoring.py update --draft "{agent.folder}\topics\{Topic}.mcs.yml" --expected ".local\topic-authoring\topic-before.json" --output ".local\topic-authoring\topic-preview.json"
```

Render the shared Update summary in normal chat and follow it with the separate Push topic to agent / Keep as draft control, unless the unchanged operation already has scoped batch/debugging approval. Keep as draft performs no remote save and uses **Draft kept locally. Agent unchanged.**

After topic approval, including valid unchanged batch/debugging consent:

```powershell
python scripts\topic_authoring.py update --draft "{agent.folder}\topics\{Topic}.mcs.yml" --expected ".local\topic-authoring\topic-before.json" --yes --output ".local\topic-authoring\topic-result.json"
```

The adapter uses mapped identity, initial reconciliation, service concurrency, and authoritative readback. It does not automatically reapply HTTP 409/412 responses. It acknowledges only captured submitted YAML, so later disk edits remain pending.

After the applicable instruction approval, including valid scoped batch/debugging consent:

```powershell
python scripts\agent_instructions.py update --draft "{agent.folder}\agent.mcs.yml" --expected ".local\topic-authoring\instructions-before.json" --yes --output ".local\topic-authoring\instructions-result.json"
```

Use the shared truthful topic outcome head and factual trailer, preserving known remote outcome separately from local bookkeeping or output failures. In composed Push, return those facts to its one results report instead of stacking owner reports. Do not auto-refresh setup, overwrite drafts from remote content, or invent rollback/replay behavior. Unchanged-intent recovery does not require approval merely because another operation is needed; materially changed target, behavior, scope or treatment of conflicting edits requires a revised summary and approval.

## 5. Testing and evaluation handoff

After a confirmed push, follow the shared state-aware testing continuation. If testing is already requested and `scripts/native_topic_test.py` is installed, carry this selected topic, intended behavior and authorized editable scope directly into `src/skills/topics/test/SKILL.md` without repeating the testing offer or topic selection. An inactive topic still requires explicit activation consent; honor no-activation and test-only requests. Otherwise report conversation acceptance as pending. Do not publish.

At the end of the authoring iteration, identify relevant affected evaluation cases across sets, including routing, negative, fallback, and cross-topic cases. A topic-only save may leave disclosed evaluation mismatches. Separately requested evaluation changes remain owned by `src/skills/evaluations/dispatcher/SKILL.md`.
