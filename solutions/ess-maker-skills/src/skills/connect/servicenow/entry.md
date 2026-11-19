# Enter ServiceNow Connect

This is the ServiceNow-specific entry point selected through `integration.json`.
It is read first on every ServiceNow route, including the agent chooser, and it
owns every ServiceNow rule; `.github/prompts/connect.prompt.md` only points
here. Generic integration selection belongs in `src/skills/connect/SKILL.md`;
the router emits Connect telemetry once, so do not emit it again here.

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not narrate tools, files, or internal routing.

## Read this first

**Python runtime.** Setup already prepared this workspace's Python runtime.
Do not invoke `configurePythonEnvironment`, **Create Environment**, or any
package-install tool, and do not create a new `.venv`. Use the launcher
selected during setup (Windows: `py -3`, `python3`, then `python`;
macOS or Linux: `python3`, then `python`), reuse that exact launcher for every
command, and substitute it wherever a command shows `python`. If the launcher
cannot import the kit's dependencies, stop and tell the maker to rerun
`/setup`; do not repair the runtime from Connect.

**STOP — render before acting.** After every `resume-handoff` or `record-checkpoint-results`, your very next assistant message — before any other tool call — must contain `renderBlock.text` verbatim (the grouped phases view; it already ends with the current step line). `renderBlock.text` is the only renderable field: never render anything under `internal`, never write your own checklist, and never add a Check/Status table. Never summarize it or write "render the plan" instead. This overrides the Message-block silence rule above.

**Hard rules.** Read `src/skills/connect/shared/lifecycle-runner.md` before the first action. When `resume-handoff` returns `renderBlock`, emit `renderBlock.text` verbatim as an assistant message; terminal output does not count. Never edit `lifecycle.json` by hand; record results with `record-checkpoint-results`. Run every command with the launcher resolved by `/setup` (`py -3`, `python3`, then `python`), never assuming bare `python`.

## Admit the workspace

Check whether `.local/setup/config.json` exists before reading it, then read it
together with `.local/config.json` when present. A missing `.local` directory
or `Path does not exist` result is expected unprepared state, not a terminal
Connect failure. Do not retry the missing read or show the global
setup-required welcome message.

ServiceNow Connect applies to Declarative Agents prepared in this workspace.
It does not depend on `.local/config.json.activeAgent`, does not change it, and
does not require `connect_ready: true`; the agent chooser applies the
authoring-ready gate (SETUP-01, SETUP-02.1, SETUP-03, SETUP-04 and SETUP-07
`done` plus a materialized workspace) to the exact selected agent and ignores
`connect_ready`. The gate is derived from existing state, never a stored field.
For a pre-selected ServiceNow integration, require canonical schema-v4
environment evidence, then proceed to the router; do not gate ServiceNow on
`.local/config.json.activeAgent`.

## Choose the agent

Read `src/skills/connect/servicenow-da/SKILL.md` and follow it. It offers the
prepared HR and IT agents for this workspace, accepts one pasted Copilot Studio
link, returns a typed `/setup` handoff for an agent that is new to this
workspace, and dispatches to the selected HR or IT Dev lifecycle.

Before selecting an agent, run only
`python scripts/connect_servicenow_da.py agent-chooser`. Do not call
`list-agents` or scan the environment. Continue to the mandatory
`resume-handoff` boundary only when the chooser returns `status: ready`.
`setup-required` is a typed handoff to `/setup` for the exact pasted Copilot
Studio link; it does not authorize setup, creation, environment switching, or
state mutation.

Do not use the legacy `step*.md` files in this directory.

## Fresh ServiceNow execution boundary

After the maker selects one DA ServiceNow Agent, and
before any FlightCheck/checkpoint command, always run:

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

## Parse the handoff

Parse the returned `servicenow.resume-handoff.v1` object:

- before any lifecycle action/checkpoint, show
  `renderBlock.text` as an ordinary agent response. It renders
  HR's four or IT's three collaboration groups with one responsible role and
  nested internal-step statuses. When
  `transport.businessGroupAvailability.gateRequired` is false, continue
  without an availability question. When true, ask only
  `transport.businessGroupAvailability.question`: serialize that exact
  canonical object unchanged to stdin for
  `python scripts/connect_servicenow_da.py --provider <provider> adapt-question`.
  Require `servicenow.ask-user-arguments.v1`, then call the active `ask_user`
  tool with the returned `askUserArguments` object verbatim. Never rebuild
  `message`, `requestedSchema`, its neutral field title, description, required
  field, or `oneOf` labels. The active callable input is
  `{message, requestedSchema}`; `questions: [...]` is internal host output,
  not a callable tool contract;
- on **Yes**, rerun the exact command with `--roles-available yes` plus the
  returned `--business-group-id` and `--availability-context-sha256`. Show
  the newly returned `renderBlock.text` before any action; for an
  acknowledged current group it contains the exact current task, target,
  owner, runbook/location, expected non-secret evidence, and completion
  boundary. Availability remains acknowledgement only. On
  **No**, rerun with the same group/context and `--roles-available no`, show
  the returned group-specific `unavailableReply`, and re-ask the identical
  question. Do not advance the current/future group, phase, or evidence on
  **No**. Preflight and instance input never ask availability. This replaces
  the generic **Ready to start?** prompt; all mutation confirmations and admin
  evidence gates remain separate;

- validate `progress.schemaVersion` as
  `servicenow.phase-progress.v1` and require its labels/order to match the
  selected provider contract. Render only each item's returned
  `customerLabel`, never its internal phase ID or long contract label. Always emit the freshly returned
  `renderBlock.text` (the grouped phases view with each step's current
  status and the current step line) as an assistant message: after plan
  acceptance, on every phase completion/next-phase transition, waiting
  pause, blocked/error transition, and completion. The flat
  `progress.items` list is data, not a rendering; everything under
  `progress.internal` and `transport.internal` is never shown. An action
  receipt (`applied`/`recorded`) is not phase completion;
- for a question or delegated-admin pause, emit the waiting
  `renderBlock.text` as an ordinary agent response (`pendingInput` and
  `record-checkpoint-results --outcome in-progress` return it), then pass the
  exact compact returned canonical object through the same
  `adapt-question` stdin command and call `ask_user` with the returned
  `askUserArguments` verbatim. Preserve the complete body and option labels.
  Do not add a
  `Progress` field, checklist, phase table, description, default, required
  input, hidden input, or second question;
- for blocked/error results, emit the error `renderBlock.text` and the
  result's short next action. Show a phase as complete only after its current
  checkpoint result and acknowledgement/evidence requirements add it to
  `--verified-phase`;
- the final `renderBlock.text` (`kind: final`) is the grouped view plus the
  completion line. Waiting, an action receipt,
  cached `done`, Test without a maker result, and any contract-defined
  interactive mutation without its maker choice are never final completion;
- never render a FlightCheck-style `| Check | Status |` table or
  health rows, and never ask for Manual acknowledgement in a table: checkpoint
  outcomes only drive the grouped phase statuses, and Manual evidence is
  asked through the existing question card;
- when `lifecycle.phase.mode` is `reverify-done`, follow shared L.2. A returned
  `run-action` first executes the current every-invocation action through L.4a;
  `run-checkpoints` runs that phase's live checkpoints. Add
  `--verified-phase` only after current results still satisfy the phase;
- when the current phase returns `run-action`, apply shared L.4a permission and
  rollback gates, then read the exact returned action document in this
  invocation and follow it;
- when that action calls `topic-action-handoff` and returns
  `question-required`, require the supported
  `header`/`question`/`options`/`allowFreeformInput` canonical shape, pass it
  through `adapt-question`, call `ask_user` with the generated arguments
  verbatim, and wait. After the maker answers, continue the matching branch in
  the already
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

## ServiceNow rules

These extend the generic numbered rules in `.github/prompts/connect.prompt.md`.

6. For ServiceNow, the user sees Message blocks, tool output tables, and the
   exact ServiceNow phase-progress strings returned by `resume-handoff`. Do not
   show internal IDs, hashes, or file operations. Do not compose your own
   messages; the only exception is combining an exact returned ServiceNow
   progress string with the result's existing plain-language remediation/next
   action as specified above.
7. For DA ServiceNow, inspect current live and durable status before every
   step: the mandatory `resume-handoff` result exclusively decides action
   versus checkpoint and must not skip an incomplete action. Skip completed
   steps only when current completion is API-verifiable or proven by a
   successful kit operation, and always ask the maker to confirm steps whose
   current state cannot be verified through an available API.
8. Waiting for maker input or a portal update is not task completion. Keep the
   current question as the resume point, never treat an unavailable-user
   auto-response as an answer, and never require the maker to invoke
   `/connect` again merely to continue that question.

Do not inspect `.local/connect/steps.md` before the provider entry point runs;
a DA ServiceNow route starts
with its provider lifecycle instead.
