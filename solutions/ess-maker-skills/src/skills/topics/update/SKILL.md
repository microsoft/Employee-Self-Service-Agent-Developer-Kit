# Update Topic

Update one mapped topic in the selected editable Dev agent from an ordinary `.mcs.yml` draft. Preserve native identity, unrelated behavior, active state, and newer non-overlapping remote content. Do not activate or publish.

## Boundaries

- Require completed canonical setup for the selected Dev agent.
- Resolve the topic through `.component-map.json`; never retarget by display name.
- Read the current native topic before editing.
- Preserve unrelated dialog fields, action IDs, triggers, metadata, expressions, and state.
- Re-evaluate stale review suggestions against the current actions before applying them.
- Treat routing overlap and instruction mismatch as advisory. Do not auto-deactivate or overwrite another topic.
- Do not author Power Automate flows.

## 1. Resolve and read the selected topic

Read `.local/config.json`, resolve exactly one mapped path, and run:

```powershell
python scripts\topic_authoring.py read --topic "{agent.folder}\topics\{Topic}.mcs.yml" --output ".local\topic-authoring\topic-before.json" --yaml-output ".local\topic-authoring\remote-topic.mcs.yml"
```

The returned component is authoritative current state. The optional projection is evidence, not permission to overwrite the working draft. Read the full local draft and surrounding components whose contracts matter.

## 2. Draft and review the change

Edit `{agent.folder}/topics/{Topic}.mcs.yml`. Preserve behavior outside the requested scope.

Show a request-sensitive preview of:

- Current and proposed triggering behavior.
- Current and proposed response, grounding, confirmation, and fallback.
- Added, removed, or reordered actions.
- Integration and cross-topic effects.

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

Obtain separate topic and instruction approvals. A known mismatch may remain after a deliberately approved topic-only save; disclose it.

## 4. Preview and save

Preview without mutation:

```powershell
python scripts\topic_authoring.py update --draft "{agent.folder}\topics\{Topic}.mcs.yml" --expected ".local\topic-authoring\topic-before.json" --output ".local\topic-authoring\topic-preview.json"
```

After topic approval:

```powershell
python scripts\topic_authoring.py update --draft "{agent.folder}\topics\{Topic}.mcs.yml" --expected ".local\topic-authoring\topic-before.json" --yes --output ".local\topic-authoring\topic-result.json"
```

The adapter uses mapped identity, initial reconciliation, service concurrency, and authoritative readback. It does not automatically reapply HTTP 409/412 responses. It acknowledges only captured submitted YAML, so later disk edits remain pending.

After separate instruction approval:

```powershell
python scripts\agent_instructions.py update --draft "{agent.folder}\agent.mcs.yml" --expected ".local\topic-authoring\instructions-before.json" --yes --output ".local\topic-authoring\instructions-result.json"
```

Report known remote outcome separately from local bookkeeping or output failures. Do not auto-refresh setup, overwrite drafts from remote content, or invent rollback/replay behavior.

## 5. Testing and evaluation handoff

For a plain save request, offer supported conversation testing. If testing is already requested and `scripts/native_topic_test.py` is installed, carry this selected topic directly into `src/skills/topics/test/SKILL.md`. Otherwise report conversation acceptance as pending. Do not activate or publish to make testing runnable.

At the end of the authoring iteration, identify relevant affected evaluation cases across sets, including routing, negative, fallback, and cross-topic cases. A topic-only save may leave disclosed evaluation mismatches. Separately requested evaluation changes remain owned by `src/skills/evaluations/dispatcher/SKILL.md`.
