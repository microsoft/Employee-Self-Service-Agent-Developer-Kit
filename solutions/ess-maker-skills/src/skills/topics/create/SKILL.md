# Create Topic

Create one ordinary Copilot Studio topic in the selected editable Dev agent. The normal output is a `.mcs.yml` draft followed by an approved native save. Do not activate or publish as a save side effect.

Read [experience-contract.md](../experience-contract.md) before interacting with the maker. Use its Create summary, initial routing-conflict decision when applicable, otherwise the short Push topic to agent / Keep as draft control, topic outcome heads, authorization rules and state-aware testing continuation. Keep requirements and revisions in normal chat; do not paraphrase fixed copy or put the summary inside the question.

## Boundaries

- Require completed canonical setup for the selected Dev agent.
- Read `.local/config.json` and use its selected agent folder and schema.
- Read relevant existing topics before drafting. Preserve the established Object Model shape, expressions, IDs in copied patterns, and shared error behavior.
- Draft wording from the approved request and supplied context. Preserve exact wording when requested. Clarify consequential unknowns, but do not require a questionnaire or a separate wording-approval lifecycle.
- Treat same-name or semantic overlap as advisory. Explain the overlap and suggest an explicitly selected existing topic when appropriate. Do not automatically deactivate, reroute, overwrite, or reject a deliberate separate topic.
- Do not create Power Automate flows. When the request requires flow authoring, explain that it must be completed outside ADK.
- Creation stays inactive and unpublished. Only a separately selected Activate and test continuation may activate it through the installed testing owner.

## 1. Resolve the request and inspect current topics

Understand the intended conversation, triggering scope, response/grounding, fallback behavior, integrations, and confirmation requirements. Read relevant examples from `{agent.folder}/topics/`.

Run:

```powershell
python scripts\topic_authoring.py list --output ".local\topic-authoring\topic-list.json"
```

Use the returned current native inventory with the local mapped topics. Warn about meaningful intent overlap. A same-name advisory does not prohibit a separately approved create.

## 2. Draft ordinary topic YAML

Immediately before substantive drafting, record this authoring invocation once, including when the maker later keeps the draft locally:

```powershell
python scripts/emit_capability.py topic_create
```

Telemetry is best-effort and must not block authoring. Previewing, saving or recovering the same proposal adds no authoring count. When this owner receives an unchanged draft for a later Push, skip this emission and reuse the draft; do not treat saving it as new authoring.

Create `{agent.folder}/topics/{ExactFileStem}.mcs.yml`. The filename stem becomes the final schema suffix with spelling and case preserved.

Use the existing Object Model-compatible YAML shape. Include all behavior needed by the request, not only fixed text. Preserve expressions and unknown supported fields from any selected pattern. Do not add authoring-origin tags or a mandatory preview artifact.

Prepare the Create summary from the shared experience contract. Cover relevant triggering intent, response/grounding, collected inputs, returned values and employee-visible outputs, confirmation, fallback, error behavior and dependencies. Render the completed summary after the current instruction-alignment assessment and native preview, before the separate short decision control.

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

When the maker selects Resolve the routing conflict in the Agent Instructions, or the correction is already explicitly authorized, edit only the desired instruction section in `{agent.folder}/agent.mcs.yml`. Do not prepare it merely because a topic is being authored. Preview it separately:

```powershell
python scripts\agent_instructions.py update --draft "{agent.folder}\agent.mcs.yml" --expected ".local\topic-authoring\instructions-before.json" --output ".local\topic-authoring\instructions-preview.json"
```

Ordinary topic and instruction changes require separate approvals. A known mismatch is advisory: explain its issue, likely execution impact and separate suggested action under Routing Conflicts, and offer the shared initial routing-conflict decision before Push. Allow a deliberate topic-only save while reporting unresolved alignment. Use the shared targeted instruction-change preview and exact two-component review before saving either proposed change. An unchanged approved Push batch or explicitly authorized in-scope debugging objective supplies its scoped consent as defined in the shared experience contract.

## 4. Preview and approve the topic save

Run without `--yes`:

```powershell
python scripts\topic_authoring.py create --draft "{agent.folder}\topics\{ExactFileStem}.mcs.yml" --display-name "{Display name}" --description "{Description}" --output ".local\topic-authoring\topic-preview.json"
```

Render the shared Create summary with the exact submitted behavior and applicable Notes and Routing Conflicts sections. Explain that creation is inactive and unpublished. With a known instruction-routing conflict, use the initial Resolve the routing conflict in the Agent Instructions / Push topic anyway / Keep as draft decision. Otherwise use the separate Push topic to agent / Keep as draft control. Reuse unchanged scoped batch/debugging approval rather than asking again.

Keep as draft performs no remote save and uses **Draft kept locally. Agent unchanged.** only for a draft-only outcome. If another approved component was saved, use the shared composed report with actual per-component results. Changed drafts require a new preview, but the preview JSON is not a save token. Material changes outside the approved scope require a new summary and approval.

## 5. Save and report authoritative results

Follow **Push telemetry** in the shared experience contract. Reuse an enclosing approved batch's lifecycle without emitting again. Otherwise own the standalone batch, starting immediately before the first approved save below and applying the shared terminal mapping after the final observed result, including any jointly approved instruction save. Keep capability authoring counts separate from this save lifecycle.

After topic approval, including valid unchanged batch/debugging consent:

```powershell
python scripts\topic_authoring.py create --draft "{agent.folder}\topics\{ExactFileStem}.mcs.yml" --display-name "{Display name}" --description "{Description}" --yes --output ".local\topic-authoring\topic-result.json"
```

The adapter captures submitted YAML once, creates one inactive component, verifies native readback and diagnostics, registers the verified identity in `.component-map.json`, and acknowledges only the captured YAML in `.baseline`. A later disk edit remains pending.

After the applicable instruction approval, including valid scoped batch/debugging consent:

```powershell
python scripts\agent_instructions.py update --draft "{agent.folder}\agent.mcs.yml" --expected ".local\topic-authoring\instructions-before.json" --yes --output ".local\topic-authoring\instructions-result.json"
```

Select the presentation from the approval scope. A topic and routing correction approved together use the shared composed Push report, including the complete instruction-save statement in its row and the conflict assessment and testing readiness in the trailer. Do not stack topic and instruction outcome blocks. Outside composed Push, use the shared truthful topic or instruction outcome block with its full statement and paragraph structure. A successful instruction save is not proof of topic execution. Preserve known remote success when local result-file or bookkeeping output fails. Do not blind-retry an uncertain create.

## 6. Testing and evaluation handoff

After a confirmed push, honor the initial routing-conflict decision. Only for a newly discovered or materially changed conflict, follow the shared combined routing-conflict/testing decision; otherwise use the ordinary state-aware testing continuation. Push topic anyway carries the declined correction into later authorized testing, but does not itself authorize testing. A test-anyway choice enters testing directly with that exclusion; do not introduce another testing offer or repair the declined conflict. If testing was already requested and `scripts/native_topic_test.py` is installed, carry the selected topic, intended behavior and authorized editable scope into `src/skills/topics/test/SKILL.md` without repeating the testing offer or topic selection. An inactive topic still requires explicit activation consent; honor no-activation and test-only requests. If the testing capability is unavailable, report conversation acceptance as pending. Do not publish.

At the end of an authoring iteration, identify relevant existing evaluation cases across sets, including routing, negative, fallback, and cross-topic impact. Do not regenerate evaluations automatically or repeat this review after every edit. For separately requested evaluation work, use `src/skills/evaluations/dispatcher/SKILL.md`.
