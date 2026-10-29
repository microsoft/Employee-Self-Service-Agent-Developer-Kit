# Create Topic

Create one ordinary Copilot Studio topic in the selected editable Dev agent. The normal output is a `.mcs.yml` draft followed by a separately approved native save. Do not activate or publish.

## Boundaries

- Require completed canonical setup for the selected Dev agent.
- Read `.local/config.json` and use its selected agent folder and schema.
- Read relevant existing topics before drafting. Preserve the established Object Model shape, expressions, IDs in copied patterns, and shared error behavior.
- Draft wording from the approved request and supplied context. Preserve exact wording when requested. Clarify consequential unknowns, but do not require a questionnaire or a separate wording-approval lifecycle.
- Treat same-name or semantic overlap as advisory. Explain the overlap and suggest an explicitly selected existing topic when appropriate. Do not automatically deactivate, reroute, overwrite, or reject a deliberate separate topic.
- Do not create Power Automate flows. When the request requires flow authoring, explain that it must be completed outside ADK.
- Do not activate or publish the new topic.

## 1. Resolve the request and inspect current topics

Understand the intended conversation, triggering scope, response/grounding, fallback behavior, integrations, and confirmation requirements. Read relevant examples from `{agent.folder}/topics/`.

Run:

```powershell
python scripts\topic_authoring.py list --output ".local\topic-authoring\topic-list.json"
```

Use the returned current native inventory with the local mapped topics. Warn about meaningful intent overlap. A same-name advisory does not prohibit a separately approved create.

## 2. Draft ordinary topic YAML

Create `{agent.folder}/topics/{ExactFileStem}.mcs.yml`. The filename stem becomes the final schema suffix with spelling and case preserved.

Use the existing Object Model-compatible YAML shape. Include all behavior needed by the request, not only fixed text. Preserve expressions and unknown supported fields from any selected pattern. Do not add authoring-origin tags or a mandatory preview artifact.

Show a normal topic preview covering:

- Filename and display name.
- Triggering intent and disambiguation.
- Conversation actions and user-facing wording.
- Grounding, confirmation, fallback, and error behavior.
- Integrations or dependencies.

## 3. Assess agent-instruction alignment

Read current native instructions:

```powershell
python scripts\agent_instructions.py read --output ".local\topic-authoring\instructions-before.json"
```

Assess alignment across:

- Intent and scope.
- Routing and disambiguation.
- Policy and confirmation.
- Response and grounding.
- Fallback.
- Topic identity and existence.

If the read fails, report alignment as unverified and pause advisably. Offer best-effort testing/browser collaboration through the topic-test owner only when `scripts/native_topic_test.py` is installed and its supported conditions hold; do not claim an automated browser instruction reader.

When a matching instruction change is useful, edit only the desired instruction section in `{agent.folder}/agent.mcs.yml`. Preview it separately:

```powershell
python scripts\agent_instructions.py update --draft "{agent.folder}\agent.mcs.yml" --expected ".local\topic-authoring\instructions-before.json" --output ".local\topic-authoring\instructions-preview.json"
```

Topic and instruction changes require separate approvals. A known mismatch is advisory: explain it and allow a deliberate topic-only save while reporting unresolved alignment.

## 4. Preview and approve the topic save

Run without `--yes`:

```powershell
python scripts\topic_authoring.py create --draft "{agent.folder}\topics\{ExactFileStem}.mcs.yml" --display-name "{Display name}" --description "{Description}" --output ".local\topic-authoring\topic-preview.json"
```

Show the exact submitted behavior and any overlap advisories. Explain that creation is inactive and unpublished.

Obtain explicit approval for the topic save. Obtain separate approval for any instruction save. Changed drafts require a new preview, but the preview JSON is not a save token.

## 5. Save and report authoritative results

After topic approval:

```powershell
python scripts\topic_authoring.py create --draft "{agent.folder}\topics\{ExactFileStem}.mcs.yml" --display-name "{Display name}" --description "{Description}" --yes --output ".local\topic-authoring\topic-result.json"
```

The adapter captures submitted YAML once, creates one inactive component, verifies native readback and diagnostics, registers the verified identity in `.component-map.json`, and acknowledges only the captured YAML in `.baseline`. A later disk edit remains pending.

After separate instruction approval:

```powershell
python scripts\agent_instructions.py update --draft "{agent.folder}\agent.mcs.yml" --expected ".local\topic-authoring\instructions-before.json" --yes --output ".local\topic-authoring\instructions-result.json"
```

Report topic and instruction outcomes separately. Preserve known remote success when local result-file or bookkeeping output fails. Do not blind-retry an uncertain create.

## 6. Testing and evaluation handoff

For a plain save request, offer supported conversation testing. If testing was already requested and `scripts/native_topic_test.py` is installed, carry the selected topic into `src/skills/topics/test/SKILL.md` without asking the user to select it again. If the testing capability is unavailable, report conversation acceptance as pending. Never activate or publish merely to make a test runnable.

At the end of an authoring iteration, identify relevant existing evaluation cases across sets, including routing, negative, fallback, and cross-topic impact. Do not regenerate evaluations automatically or repeat this review after every edit. For separately requested evaluation work, use `src/skills/evaluations/dispatcher/SKILL.md`.
