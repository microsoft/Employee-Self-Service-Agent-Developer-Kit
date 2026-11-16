# Create Topic

Create one ordinary Copilot Studio topic in the selected editable Dev agent. The normal output is a `.mcs.yml` draft followed by an approved AgentBuilder save. Do not activate or publish as a save side effect.

Read the [shared foundation](../experience-contract.md) before interacting with the maker. Apply its Supported authoring scope, authoring policy and authorization rules. Before drafting or saving, read [Response wording and local drafts](../authoring-experience.md#response-wording-and-local-drafts) and [Authoring status updates](../authoring-experience.md#authoring-status-updates). Reuse those status definitions at the marked reporting points below. Load the other linked references at the steps that need them, not all upfront.

## Boundaries

- Require completed canonical setup for the selected Dev agent.
- Read `.local/config.json` and use its selected agent folder and schema.
- Read relevant existing topics before drafting. Preserve the established Object Model shape, expressions, IDs in copied patterns, and shared error behavior.
- Preserve supplied response wording and links by default. Suggest wording only when it is absent, using established facts and the shared wording review. Clarify consequential unknowns, but do not require a questionnaire or a separate wording-approval lifecycle.
- Follow the shared same-name creation rule. Treat meaningful intent overlap under a different name as advisory.
- Do not create Power Automate flows. When the request requires flow authoring, explain that it must be completed outside ADK.
- Creation stays inactive and unpublished. Only a separately selected Activate and test continuation may activate it through the installed testing owner.

## 1. Resolve the request and inspect current topics

Understand the intended behavior, inputs and outputs before drafting. Read relevant examples from `{agent.folder}/topics/`.

Run:

```powershell
python scripts\topic_authoring.py list --output ".local\topic-authoring\topic-list.json"
```

Use the returned current agent inventory with the local mapped topics. Apply the shared **Authoring policy for this release** to the proposed schema identity and display name before drafting and again before saving. Stop if the requested display name already exists. Warn about meaningful intent overlap under a different name.

## 2. Draft ordinary topic YAML

Immediately before substantive drafting, record this authoring invocation once, including when the maker later keeps the draft locally:

```powershell
python scripts/emit_capability.py topic_create
```

Telemetry is best-effort and must not block authoring. Previewing, saving or recovering the same proposal adds no authoring count. When this owner receives an unchanged draft for a later Push, skip this emission and reuse the draft; do not treat saving it as new authoring.

Create `{agent.folder}/topics/{ExactFileStem}.mcs.yml`. The filename stem becomes the final schema suffix with spelling and case preserved.

Use the existing Object Model-compatible YAML shape for the requested behavior. Do not use the optional exact-response helper as a universal admission validator. Preserve expressions and unknown supported fields from any selected pattern. Do not add authoring-origin tags or a mandatory preview artifact.

Prepare the [Create summary](../authoring-experience.md#create-summary). Cover relevant triggering intent, response/grounding, collected inputs, returned values and employee-visible outputs, confirmation, fallback, error behavior and dependencies. Render the completed summary after the current instruction-alignment assessment and save preview, before the separate short decision control.

Assess the outcome of preparing or reusing the local draft, including a failed or incomplete attempt. For a revision, return to this reporting point after assessing the revised draft.

`{EMIT_STATUS_UPDATE: draft-preparation}`

## 3. Assess agent-instruction alignment

Read current saved instructions:

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

For this selected correction attempt:

{EMIT_STATUS_UPDATE: instruction-preparation}

Ordinary topic and instruction changes require separate approvals. For a known mismatch, read [Routing Conflicts](../authoring-experience.md#routing-conflicts) and the [initial routing-conflict decision](../authoring-experience.md#initial-routing-conflict-decision). Allow a deliberate topic-only save while reporting unresolved alignment. When preparing a correction, use the [targeted instruction-change preview](../authoring-experience.md#targeted-instruction-change-preview-and-approval) and [Push review](../push-experience.md#entry-inventory-and-choices) before saving either proposed change. Reuse unchanged scoped batch/debugging consent from the shared foundation.

## 4. Preview and approve the topic save

Run without `--yes`:

```powershell
python scripts\topic_authoring.py create --draft "{agent.folder}\topics\{ExactFileStem}.mcs.yml" --display-name "{Display name}" --description "{Description}" --output ".local\topic-authoring\topic-preview.json"
```

Render the completed Create summary and use the [Topic save decision](../authoring-experience.md#topic-save-decision), including its applicable wording or routing branch. Keep the summary in normal chat and the decision control separate. Explain that creation is inactive and unpublished. Revisions return to a fresh preview and the shared decision before saving; reuse unchanged scoped batch/debugging approval rather than asking again.

Keeping a draft performs no remote save. Use [Topic outcomes](../authoring-experience.md#topic-outcomes) for a draft-only result or the [composed report](../push-experience.md#composed-push-report-composed_push_report) for partial saves. Changed drafts require a new preview, but the preview JSON is not a save token. Material changes outside the approved scope require a new summary and approval.

## 5. Save and report authoritative results

Read [**Push telemetry**](../push-experience.md#push-telemetry) before execution. Reuse an enclosing approved batch's lifecycle without emitting again. Otherwise own the standalone batch, starting immediately before the first approved save below and applying the shared terminal mapping after the final observed result, including any jointly approved instruction save. Keep capability authoring counts separate from this save lifecycle.

After topic approval, including valid unchanged batch/debugging consent:

```powershell
python scripts\topic_authoring.py create --draft "{agent.folder}\topics\{ExactFileStem}.mcs.yml" --display-name "{Display name}" --description "{Description}" --yes --output ".local\topic-authoring\topic-result.json"
```

The adapter captures submitted YAML once, creates one inactive component, verifies AgentBuilder readback and diagnostics, registers the verified identity in `.component-map.json`, and acknowledges only the captured YAML in `.baseline`. A later disk edit remains pending.

Assess the topic-save attempt, including rejected, no-write, partial or unconfirmed outcomes.

`{EMIT_STATUS_UPDATE: topic-save}`

After the applicable instruction approval, including valid scoped batch/debugging consent:

```powershell
python scripts\agent_instructions.py update --draft "{agent.folder}\agent.mcs.yml" --expected ".local\topic-authoring\instructions-before.json" --yes --output ".local\topic-authoring\instructions-result.json"
```

{EMIT_STATUS_UPDATE: instruction-save}

Report through [Topic outcomes](../authoring-experience.md#topic-outcomes) and, when applicable, [Instruction-push outcomes and testing](../authoring-experience.md#instruction-push-outcomes-and-testing). A joint approval uses the [composed Push report](../push-experience.md#composed-push-report-composed_push_report), not stacked owner blocks. Preserve known remote success when local result-file or bookkeeping output fails. Do not blind-retry an uncertain create.

## 6. Testing and evaluation handoff

Read [Topic testing continuation](../testing-experience.md#topic-testing-continuation) when reaching this handoff. Carry the selected topic, latest intended behavior, actual save/state, existing authorization and declined corrections. Check `scripts/native_topic_test.py` before offering runnable testing; if unavailable, report conversation acceptance as pending. Enter [the testing owner](../test/SKILL.md) only within the shared consent rules. Do not activate or publish as a save side effect.

At the end of an authoring iteration, identify relevant existing evaluation cases across sets, including routing, negative, fallback, and cross-topic impact. Do not regenerate evaluations automatically or repeat this review after every edit. For separately requested evaluation work, use `src/skills/evaluations/dispatcher/SKILL.md`.
