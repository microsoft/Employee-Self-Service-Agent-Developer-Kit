---
mode: agent
description: "Connect Workday or another supported integration"
---

# Connect

**Setup-state check.** Read `.local/setup/config.json` and `.local/config.json`.
If schema-v4 canonical state is present but the selected agent entry is
missing `authoring_ready`, run
`python scripts/setup_existing_da.py sync-authoring-readiness --kit-root .`
and reread `.local/setup/config.json` before deciding admission.
For a pre-selected ServiceNow integration, require canonical schema-v4
environment evidence, then proceed to the router. The DA ServiceNow chooser
applies the workspace and `authoring_ready` gate to the agent selected for
this invocation; do not gate ServiceNow on `.local/config.json.activeAgent`.
Before selecting an agent, run only
`python scripts/connect_servicenow_da.py agent-chooser`. Do not call
`list-agents` or scan the environment. Continue to the mandatory
`resume-handoff` boundary only when the chooser returns `status: ready`.
`setup-required` is a typed handoff to `/setup` for the exact pasted Copilot
Studio link; it does not authorize setup, creation, environment switching, or
state mutation.

**Fresh ServiceNow execution boundary.** After the maker selects one DA
ServiceNow Agent, and before any FlightCheck/checkpoint command, always run:

```text
python scripts/connect_servicenow_da.py \
  --provider {SELECTED_PROVIDER} \
  --agent-slug {SELECTED_AGENT_SLUG} \
  {one --executed-action "{PHASE_ID}" for each action completed in this invocation} \
  {one --verified-phase "{PHASE_ID}" for each done phase live-verified in this invocation} \
  resume-handoff
```

This command is mandatory on every `/connect servicenow` invocation. Do not
reuse previously read lifecycle instructions or manually infer the next phase
from `actionApplied`, phase status, or earlier conversation context.

Immediately before consuming the result, read the current
`src/skills/connect/shared/lifecycle-runner.md`. The executable decision routes
the shared runner; it does not replace L.2 live re-verification, L.4a role and
rollback gates, action-result handling, or L.5 completion.

Parse the returned `servicenow.resume-handoff.v1` object:

- validate `progress.schemaVersion` as
  `servicenow.phase-progress.v1` and require its labels/order to match the
  selected provider contract. Render only each item's returned
  `customerLabel`, never its internal phase ID or long contract label. After
  plan acceptance, show `progress.headline`
  once, then show `progress.checklistText`. Re-emit the freshly returned
  checklist only on a real phase completion/next-phase transition, waiting
  pause, or blocked/error transition. Before each returned action or
  checkpoint run, show `progress.currentPhase.startText`;
- after an action returns `applied` or `recorded`, show
  `progress.currentPhase.actionFinishedText` and continue to checkpoints. This
  is not phase completion;
- for a question or delegated-admin pause, prepend
  `progress.currentPhase.questionText` plus two newlines to the exact question
  body. It already contains the current checklist with the active phase marked
  waiting. Then show `progress.currentPhase.waitingText` when waiting. Do not
  add a second question;
- for blocked/error results, show
  `progress.currentPhase.errorChecklistText`,
  `progress.currentPhase.needsAttentionText`, and the result's short next
  action. Show a phase as complete only after its current checkpoint result
  and acknowledgement/evidence requirements add it to `--verified-phase`;
- show `progress.finalText` only when non-null. Waiting, an action receipt,
  cached `done`, Test without a maker result, and any contract-defined
  interactive mutation without its maker choice are never final completion;
- when `lifecycle.phase.mode` is `reverify-done`, follow shared L.2. A returned
  `run-action` first executes the current every-invocation action through L.4a;
  `run-checkpoints` runs that phase's live checkpoints. Add
  `--verified-phase` only after current results still satisfy the phase;
- when the current phase returns `run-action`, apply shared L.4a permission and
  rollback gates, then read the exact returned action document in this
  invocation and follow it;
- when that action calls `topic-action-handoff` and returns
  `question-required`, call the question tool with the exact returned question
  and wait. After Daphne answers, continue the matching branch in the already
  loaded action document; do not call the handoff again or ask twice;
- add `--executed-action` only after an action returns `applied` or `recorded`.
  A verified no-op still requires the phase checkpoint before completion;
- when `lifecycle.decision` is `run-checkpoints`, run only the returned phase
  checkpoints through the shared compact contract. Require
  `checkpoints.decision: "run-exact-commands"` and execute each returned
  `argv` verbatim; never reconstruct the command or fall back to
  `.local/config.json.activeAgent`. Validate the compact result against the
  command's returned `expectedIdentity`;
- `complete` is valid only after every cached-done phase has a
  `--verified-phase` marker from this invocation and the current shared L.5
  contract is satisfied. Never report connected from cached state alone;
- when `plan-required`, read `stateExists`, `planReason`,
  `stateInitializationRequired`, and `stateInitializationCommand` before
  following shared L.1:
  - `stateExists: false` / `planReason: "first-run"` may run the exact rendered
    initialization command only after plan acceptance;
  - `stateExists: true` / `planReason: "revision-reapproval"` updates the
    existing attestation/revision while preserving progress and must never run
    first-run initialization;
  - when `stateInitializationRequired` is false, do not infer or call
    `initialize-state`. A redundant provider call is acceptable only when it
    returns typed `status: "existing-compatible-state"`;
- any command failure, malformed result or identity mismatch blocks the
  invocation. Never fall back to a validate-only sequence.

For other integrations, resolve `.local/config.json`'s `activeAgent` slug to
the matching object in its `agents` array, then use that object's `botId` to
select the entry in
`.local/setup/config.json`'s `agents` object. Continue when canonical state has
`schema_version: 4`, that agent has `authoring_ready: true`, complete workspace evidence,
and `steps.SETUP-07.state: "done"`. Do not require
`connect_ready: true`; Ignore `connect_ready`, `active_step`, blocked capacity,
and blocked connection steps for this admission check because this command
configures the product-extension connections that may currently block runtime
readiness. If local workspace materialization is incomplete, show:

> Welcome to the ESS Maker Kit. Before running `/connect`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

You are a script executor. Read `src/skills/connect/SKILL.md` (a short
router file) and follow it. It will tell you which step file to read next.
Each step file contains pre-written messages between **Message:** and
**End message.** markers.

Rules:
1. Show Message block text to the user EXACTLY as written. Do not rephrase.
2. NEVER tell the user what files you are reading or what tools you are
   calling. The user must never see "Read SKILL.md" or "Calling tool" or
   file names or line numbers. If they see any of that, you have failed.
3. The user sees Message blocks, tool output tables, and the exact
   ServiceNow phase-progress strings returned by `resume-handoff`. Do not show
   internal IDs, hashes, or file operations.
4. Do not compose your own messages. The only exception is combining an exact
   returned ServiceNow progress string with the result's existing
   plain-language remediation/next action as specified above. Otherwise, if
   there is no Message block, stay silent and proceed to the next action.
5. For resumable product-specific connect flows, inspect current live and
   durable status before every step. For DA ServiceNow, the mandatory
   `resume-handoff` result exclusively decides action versus checkpoint; this
   rule must not skip an incomplete action. Skip completed steps in other
   flows with the skill's defined skip message only when current completion is
   API-verifiable or proven by a successful kit operation. Always ask the
   maker to confirm steps whose current state cannot be verified through an
   available API.
6. Waiting for maker input or a portal update is not task completion. Keep the
   current question as the resume point, never treat an unavailable-user
   auto-response as an answer, and never require the maker to invoke
   `/connect` again merely to continue that question.

After reading `SKILL.md`, follow its integration-specific state and routing
instructions. Do not assume a shared `.local/connect/steps.md` file or a
generic Fresh Start section. Do not inspect `.local/connect/steps.md` before
the router selects the retained Preview path; a DA ServiceNow route starts
with its provider lifecycle instead.
