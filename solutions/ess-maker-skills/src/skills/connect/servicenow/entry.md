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

**STOP — render before acting.** After every `resume-handoff` or `record-checkpoint-results`, your very next assistant message — before any other tool call — must contain `renderBlock.text` verbatim (the setup checklist; it already ends with the current step line). `renderBlock.text` is the only renderable field: never render anything under `internal`, never write your own checklist, and never add a Check/Status table. Never summarize it or write "render the plan" instead. At the start of a fresh run `renderBlock.text` begins with the connection opening ("We'll connect ... so employees can ...", or "We'll add ..." when another ESS agent in the same environment already has shared sign-in setup); emit it verbatim as part of the same message, and never write your own opening or repeat it later. The Test-pane ready message in the current-task lead-in is controller-built: show it verbatim and never reword it, and when `record-test --result untested` or `--result empty` returns `message`, show that `message` verbatim (for `empty`, nothing is recorded and the Test step stays open; ask the result question again) and never claim the integration works. The portal URL question is controller-built plain chat text inside the current-task message: show it verbatim, end the turn, and wait for the Maker's typed reply (never call a question card for it). The portal URL confirmation question and options returned by `portal-url-confirmation` are controller-built: show them verbatim, and save nothing before the Maker selects Yes. This overrides the Message-block silence rule above.

**Controller output rules.** Every `connect_servicenow_da.py` output starts with `chatMessage`: send it verbatim as plain chat text before any other tool call. If `endTurn` is `true`, end your turn right after sending it (the message asks the Maker to reply, return, paste, send or act outside chat); do not read the next document or run another command until the Maker replies, then follow `afterReply` when present. If `endTurn` is `false`, do not stop or wait: run `nextCommand` in the same turn. Wording such as "Return here", "tell us", "reply", "paste", "send" or "let us know" always means wait for the Maker. When `pendingCard` is present, ask it with one `ask_user` call using `pendingCard.askUserArguments` exactly as given: the card title is the question and the card has no body, so add no examples, warnings or notes to it; all explanation belongs in `chatMessage`. Option labels are Yes/No or very short; never rebuild them.

**Hard rules.** Read `src/skills/connect/shared/lifecycle-runner.md` before the first action. When `resume-handoff` returns `renderBlock`, emit `renderBlock.text` verbatim as an assistant message; terminal output does not count. Never edit `lifecycle.json` by hand; record results with `record-checkpoint-results`. Run every command with the launcher resolved by `/setup` (`py -3`, `python3`, then `python`), never assuming bare `python`.

## Admit the workspace

Check whether `.local/setup/config.json` exists before reading it, then read it
together with `.local/config.json` when present. A missing `.local` directory
or `Path does not exist` result is expected unprepared state, not a terminal
Connect failure. Do not retry the missing read or show the global
setup-required welcome message. Unprepared state is handled by the automatic
Setup handoff in **Choose the agent**; never ask the maker to type `/setup` or
repeat their Connect request.

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
link, hands off to Setup automatically when the workspace or the pasted agent
is not prepared, and dispatches to the selected HR or IT Dev lifecycle.

Before selecting an agent, run only
`python scripts/connect_servicenow_da.py agent-chooser`, adding
`--selection-key "another-agent" --agent-link "{LINK}"` when the maker's
request already includes a Copilot Studio link. Do not call `list-agents` or
scan the environment. Continue to the mandatory `resume-handoff` boundary only
when the chooser returns `status: ready`.

**Reuse an agent the maker already named in this conversation.** Do not show
the Yes/No agent question ("Connect {agent} to ServiceNow?") when the maker
already gave or settled on the agent
earlier in the same conversation: a Copilot Studio agent link pasted during
Setup or any earlier turn, or an agent Setup or an earlier Connect turn already
selected, attached, or prepared. Reuse it silently, without asking:

- When a link is known, run
  `agent-chooser --selection-key "another-agent" --agent-link "{LINK}"`.
- Otherwise, when the agent ID is known from the conversation (for example the
  ID Setup reported), run `agent-chooser --selection-key "prepared:{AGENT_ID}"`.
- Otherwise, when the maker only named the agent (for example "my Benefits
  agent"), run `agent-chooser --agent-name "{NAME_AS_TYPED}"` and follow its
  result without showing a card: `ready` continues, `setup-incomplete` is the
  Setup handoff, and `unsupported-agent` shows its `message` verbatim (see
  **Unsupported agent**). Never ask for a Copilot Studio link for a named agent
  and never start Setup for an unsupported one.
- When the maker named no agent and wants a plain chat question instead of the
  card, get it from
  `python scripts/connect_servicenow_da.py --provider {PROVIDER} validation-notice --situation agent-chooser`
  (see **Validation notices** below), send it verbatim, and map the reply to
  one `prepared:{ID}` key.

Continue only when the result is `status: ready`; then show the confirmation
Message at the end of this section, with its **Choose a different agent**
offer, which stays the maker's way to switch. Treat
`setup-required` and `setup-incomplete` as the automatic Setup handoffs above,
carrying the known link.

Fall back to the normal chooser when the conversation names no agent, names
more than one distinct agent, or the key returns an error such as the agent no
longer being available. A single prepared agent that the maker never mentioned
does not count as a choice already made: show the chooser. An agent the maker
named that is not an ESS HR or IT agent is not a fallback case: use
`--agent-name` as above and show the unsupported-agent message.

`setup-required` (branch `workspace-not-prepared` or `explicit-agent-link`) and
`setup-incomplete` (branch `setup-not-finished`: the agent is already in this
workspace but its Setup steps are still pending) are automatic Setup
handoffs, not stops. Show:

**Message:**

Before we can connect ServiceNow, we need to finish basic ADK setup. We'll
complete that first, then return to the ServiceNow connection.

**End message.**

Then immediately read `src/skills/foundation-setup/SKILL.md` and follow
**Prepare the workspace for an integration** in the same invocation. Preserve
ServiceNow as the selected integration, the original request, and any supplied
agent link; pass `setupHandoff.targetUrl` to Setup as the supplied target so it
does not ask whether the maker already has an agent. Do not ask the maker to
type `/setup`, ask for confirmation just to enter Setup, or ask them to repeat
Connect. Setup's normal selection, sign-in, and environment/account
confirmation controls still apply; do not choose or create an agent for the
maker. The chooser itself changes no state. When Setup attaches the agent,
pass the service-provided environment display name with
`--environment-display-name "{ENVIRONMENT_DISPLAY_NAME}"` exactly as
`foundation-setup/da-existing-dev.md` requires, and omit it when Setup has none;
never derive a name from an ID, URL, or host.

When the pasted link is in a different environment than this workspace, the
handoff carries `workspaceEnvironmentDiffers: true`. Setup's existing
conflicting-environment choice (**Shared workspace choices** in
`foundation-setup/SKILL.md`) applies; do not make the choice for the maker or
ask them to type `/setup`. Continue below only when Setup returns a
materialized workspace for this agent; if it ends elsewhere (for example in a
separate worktree), show its actual disposition and do not continue here.

If Setup is blocked, cancelled, or exited, do not continue Connect or invoke
Setup again in this invocation, and do not tell the maker to type `/setup`.
Preserve the original request. When Setup reported a blocker the maker can
fix, show:

**Message:**

Setup for **{AGENT_NAME}** didn't finish: {REASON}. ServiceNow wasn't
connected, and nothing was changed. Please fix that first. When you're ready,
just tell me to finish setup and connect ServiceNow, and I'll pick up from
here.

**End message.**

When the maker simply cancelled, there is nothing to fix; show:

**Message:**

Setup for **{AGENT_NAME}** didn't finish: setup was cancelled. ServiceNow
wasn't connected, and nothing was changed. When you're ready, just tell me to
finish setup and connect ServiceNow, and I'll pick up from here.

**End message.**

`{REASON}` is a short plain clause with no trailing period that says what to
fix, taken from what Setup reported, with no paths or error codes. Use the
agent name from the pasted link or Setup's report, and omit " for
**{AGENT_NAME}**" when none is known.

When the maker later asks to finish setup and connect ServiceNow (or sends
`/connect servicenow` again), treat it as a fresh request: rerun
`agent-chooser` and follow this handoff again, without requiring `/setup`. The
no-loop rule applies only within one invocation.

When Setup returns a materialized workspace, continue directly: Setup's
completion summary and post-setup choices are not shown, as in Workday's
prepare-at-entry flow. Rerun the chooser instead of showing the full chooser
again:

- with a link: `agent-chooser --selection-key "another-agent" --agent-link "{LINK}"`
- without a link: `agent-chooser --selection-key "prepared:{AGENT_ID}"`, using
  the agent ID Setup reports for the agent it just prepared

Continue only when the rerun returns `status: ready` for that agent. Do not
say the agent is set up, show the "We'll continue" message, or start any
Connect step before that result.

If the rerun returns `setup-incomplete`, the agent is in the workspace but
Setup's remaining steps are still pending (for example after **Checkpoint and
refresh** reset them). Do not end with an error. Resume Setup once in this
invocation for that exact agent, without repeating the first Message: run the
setup-readiness FlightChecks `DA-AGENT-001` and `DA-CONTENT-001` and apply each
result with `setup_existing_da.py maintain-flightcheck`, exactly as the
readiness sequence in `foundation-setup/da-existing-dev.md` describes (same
agent, environment, ring, and `--preferred-username "{SETUP_ACCOUNT}"`), then
rerun the chooser once more. If it still does not return `ready`, or Setup
reports a blocker, treat it as a blocked Setup: show the blocker Message above
with the pending step in plain language as `{REASON}`, and do not resume again.
Any other chooser error is shown as returned, without looping into Setup.

After the rerun returns `ready`, show:

**Message:**

We'll continue with **{AGENT_NAME}**, the agent you just set up in
**{ENVIRONMENT_NAME}**. You can select another supported ESS agent before we
continue.

**End message.**

Use the canonical `environment.display_name` from `.local/setup/config.json`
(the same optional field Setup uses as `{ENVIRONMENT_DISPLAY_NAME}`), and omit
" in **{ENVIRONMENT_NAME}**" when it is not recorded; never infer a name. Offer only
**Choose a different agent**; if the maker picks it, run
`python scripts/connect_servicenow_da.py agent-chooser` and follow
`servicenow-da/SKILL.md`. Otherwise continue without asking again. Do not change
`.local/config.json.activeAgent` or persist the choice.

Do not use the legacy `step*.md` files in this directory.

## Test and Prod realms

When the maker says the agent was promoted to Test or Production, chooses to
configure either realm, or pastes a Test or Production agent link, read
`src/skills/connect/servicenow/realms.md` and follow it. Test and Prod checks
are independent of the Dev lifecycle and never reuse the Dev connection. It
never changes Dev behavior.

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

## ServiceNow additions to the shared runner

These rules apply only to ServiceNow and extend `lifecycle-runner.md`; no other
provider uses them.

- **Role attestation.** For **Maker configuration and validation**, the **Yes**
  answer to the availability question asked at the start of that group is also
  the role attestation for every mutating phase in it (`credential`, `topics`,
  `portal-url`). The controller records `roleAttestations.{requiredRole}` in
  the same write as the group acknowledgement (and backfills it for an
  already-acknowledged group on resume). Do not show `permission-gate.md`'s
  Yes/No role question for those phases, so those phases never show a role
  question. If `roleAttestations.{requiredRole}` is missing or invalid
  at a mutating phase, do not run the action or ask a role question there:
  rerun `resume-handoff` so the phase-start question is asked first. A **No**
  answer records nothing and mutates nothing.
- **Administrator instructions.** Render `ordinaryReply.text` verbatim; it
  already contains the plain-text lead-in and the Ready-to-send fenced block.
- **Phase `renderBlock.text`.** After **Yes**, the newly returned
  `renderBlock.text` is maker-facing wording only: a short lead-in that
  connects to the previous step, the numbered steps or Ready-to-send message
  when the phase has one, and nothing else. Show it verbatim. It never renders
  the target, responsible role, runbook path, expected evidence, or completion
  boundary; those stay in the controller JSON and the action docs for the
  agent. The credential lead-in names the saved User Claim and User Field only
  when both are recorded.
- **Final `renderBlock.text`.** Its closing sentence states what the
  Maker-reported Test pane result does and does not cover.

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
  `renderBlock.text` (the flat setup checklist with a checked or unchecked box
  per task and the current step line) as an assistant message: after plan
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
  `askUserArguments` verbatim. The card shows only the question title and its
  short option labels; its body was already sent as chat text. Do not add a
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
  `question-required`, first show the returned `replyBeforeQuestion` verbatim
  as an ordinary agent reply, then require the supported
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

## Clarification and recovery Messages

These replace the relevant point in the journey; they do not restart it. Use
the agent and environment names already known (omit " in **{ENVIRONMENT_NAME}**"
when no display name is recorded) and never add paths, IDs, or error codes.

**Unsupported agent.** When `agent-chooser` returns `status:
unsupported-agent`, show `message` verbatim, offer **Choose a different
agent**, and do not enter Setup or any lifecycle for that agent:

**Message:**

We can connect **Employee Self-Service HR to ServiceNow HR Service Delivery**
or **Employee Self-Service IT to ServiceNow IT Service Management**, one agent
at a time. The selected agent isn't supported.

Select Employee Self-Service HR or IT to continue.

**End message.**

**Permission denied.** When the target preflight read returns a permission
denial (HTTP 401/403), show the following and stop without administrator work:

**Message:**

Your account doesn't have the required access to configure **{AGENT_NAME} in
{ENVIRONMENT_NAME}**.

Ask a maker with the Environment Maker role and permission to edit this agent
to run `/connect servicenow` using their own account.

**End message.**

**Permission unavailable.** When the same read cannot complete (throttling,
network, or service error), show the following. When the maker answers Retry,
rerun the mandatory `resume-handoff`; an assurance from the maker or an
administrator never replaces the check:

**Message:**

We couldn't verify whether your account can configure **{AGENT_NAME} in
{ENVIRONMENT_NAME}**. Setup is paused; this doesn't mean your access was
denied.

Retry the permission check to continue.

**End message.**

**HR plugin not ready.** When the maker reports that the ServiceNow
administrator says the HR plugin is not active yet, show the following. Do not
install the plugin or describe this as a failed integration:

**Message:**

HR setup is waiting for your ServiceNow administrator to confirm that the HR
Service Delivery Core plugin is installed and active.

Bring back that confirmation when it's ready, and we'll continue with the
Entra handoff. You won't need to restart.

**End message.**

**Maker pauses for an administrator.** When the maker says they will return
later while an administrator reply is outstanding, show the first Message. Any
later message from the maker in this setup (including "continue" or any other
words) means they want to continue; never ask a Yes/No question to confirm it.
Show the second Message, rerun `resume-handoff` (which rechecks permission),
and only after it succeeds show the third Message and wait for the reply. Do
not render the administrator's ready-to-send message again. Record the reply
with the existing commands; when items are missing, use the matching
clarification Message:

**Message:**

We're waiting for your ServiceNow administrator's saved-configuration
confirmation, User Claim, and User Field.

When you return, paste their non-sensitive reply or send those items
individually. Don't include employee identifiers or secrets. You won't need to
repeat the Entra values.

**End message.**

**Message:**

We're continuing the ServiceNow setup for **{AGENT_NAME} in
{ENVIRONMENT_NAME}**.

We're rechecking your permission to configure this agent before we continue.
Next, we'll need your ServiceNow administrator's reply.

**End message.**

**Message:**

Paste their non-sensitive saved-configuration confirmation, User Claim, and
User Field—or send those items individually. Don't include employee
identifiers or secrets.

**End message.**

**Conflicting Client IDs.** When the Entra reply contains more than one
different Client ID, record nothing and show:

**Message:**

The reply contains more than one Client ID. Ask your Entra administrator which
**Client ID** ServiceNow should use.

Send that value here.

**End message.**

**Custom employee identifier (payroll ID).** Only when the maker or an
administrator says employees are identified by a payroll or other custom
employee ID (not by email or UPN), pass `--custom-identifier` on the first
`identity-direct-handoff --stage entra` call. The controller stores a
non-sensitive `customIdentifier` marker (no identifier values) so every later
step keeps the custom-identifier wording after a resume: the Entra and
ServiceNow handoffs ask for the exact custom claim name and tell the
administrators to review the existing setup first, and the connection step says
to use a supported ESS ServiceNow connection if one is available and otherwise
create one. A custom claim name alone does not switch wording; only the flag or
the stored marker does. The existing-identity (Knowledge, SSO, Graph) wording
takes precedence when both apply. Render the returned text verbatim.

**Custom claim not confirmed.** Only when the maker says a custom claim (or
custom field) is wanted and the Entra administrator has not confirmed it, show
the following Message verbatim as the whole reply. Mentioning an employee ID or
another field without saying a custom claim is wanted does not trigger it:
never point the maker to Part 4 then; run the same command without
`--custom-claim` and send its reply, which only asks the Entra administrator to
confirm the exact claim name. This
applies at any point in the journey, including while waiting for the
ServiceNow administrator's reply. Do not explain the current claim, list your
own next steps, record anything, or ask a question. Get the Message from the
controller instead of writing it: run
`python scripts/connect_servicenow_da.py --provider {PROVIDER} claim-confirmation-handoff --custom-claim`
(add `--claim-name-given` when the Entra administrator's exact claim name is
already stated; the reply then asks the Entra administrator to complete the
custom-claim work and return the confirmation plus the exact configured claim
name, and ignores `--servicenow-confirmed`; otherwise add
`--servicenow-confirmed` when the ServiceNow
administrator's saved-configuration confirmation with the matching User Claim
and User Field is already supplied; add `--second-agent` when the maker is
adding a second agent that reuses another agent's setup), send `chatMessage` verbatim and follow
`endTurn`/`afterReply`. The command records nothing and needs no agent state. The maker
is not asked to select an identity mapping or invent a claim name; a proposed
name, a name alone, or a vague "done" does not establish readiness. End the
turn and wait; the next message from the maker continues the setup.

When some items are already confirmed, ask only for the missing ones: when the
Entra administrator's exact claim name is already stated, show the "We have
the claim name" Message below instead of asking for the name again; when the ServiceNow administrator's
saved-configuration confirmation with the matching User Claim and User Field
is already supplied, omit the third paragraph. Never drop the last paragraph:
the already supplied values stay in place.

**Message:**

We need the Entra administrator to confirm the custom claim before ServiceNow
can use it to identify employees.

Ask them to complete the custom-claim work in Part 4 of their instructions.
Bring back the exact configured claim name and confirmation that the setup is
complete, including the appropriate format and populated source attribute for
every intended employee.

Then ask your ServiceNow administrator to confirm that the supported
configuration is saved, with the matching User Claim and User Field. Don't send
employee identifiers or secrets.

We'll keep the Client ID already supplied.

**End message.**

**Claim name omitted.** When the Entra reply gives a Client ID but only says a
custom claim "is configured" without naming it, record nothing about the claim,
never guess a name from the phrase, and show the first Message. When the reply
contains two possible claim names, show the second. When an exact name is given
without confirmation that its setup is complete, show the third, substituting
the stated name. Get it from the controller: run `record-identity-direct
--stage entra --claim-name "<name>" --yes` without `--claim-setup-confirmed`
(it records nothing and returns this Message in `chatMessage`). Never ask a
clarifying card about the name, and record a custom name only after the Entra
administrator confirms the setup is complete (then add
`--claim-setup-confirmed`):

**Message:**

We have the Client ID. Next, we need the **exact claim name** your Entra
administrator configured for ServiceNow to use.

Ask your Entra administrator for that name, or paste the rest of their
non-sensitive reply. You don't need to resend the Client ID.

**End message.**

**Message:**

The reply contains two claim names, and we can't tell which one the app emits
for this setup.

Ask your Entra administrator to confirm the exact one ServiceNow should use.
The confirmed Client ID stays in place.

**End message.**

**Message:**

We have the claim name `{CLAIM_NAME}`. Ask your Entra administrator to confirm
that its setup is complete, including the appropriate format and populated
source attribute for every intended employee, as requested in their message.

Bring back their non-sensitive confirmation; you don't need to resend the name
or the Client ID. Don't include employee identifiers or secrets.

**End message.**

**Metadata URL with `/v2.0` reported.** Only when the maker (or an administrator
reply) states the actual saved OIDC metadata URL and it contains `/v2.0`; never
infer it from a generic failure or from a URL that was not reported. Get the
Message from the controller instead of writing it: run
`python scripts/connect_servicenow_da.py --provider {PROVIDER} metadata-url-handoff --metadata-url "<reported URL>"`,
send `chatMessage` verbatim as the whole reply, and follow `endTurn` and
`afterReply`. The command records nothing and changes no shared identity
configuration; the corrected URL it shows is derived from the reported one.
If it returns `no-diagnosis`, this scenario does not apply: do not call it a
known setup problem and continue the normal flow. Do not ask a Yes/No
question. When the maker returns, any message means they want to continue:
record only the administrators' non-sensitive reply and recheck the affected
setup before the Test-pane request is repeated. An unresolved compatibility
conflict stays paused. The Message is, with the directory GUID taken from the
reported URL:

**Message:**

That metadata URL contains `/v2.0`, which is a known setup problem for this
connection.

Ask your ServiceNow administrator to review the saved URL against the supported
ESS metadata URL below, coordinating compatibility with your Entra
administrator before any repair:

`https://login.microsoftonline.com/{DIRECTORY_GUID}/.well-known/openid-configuration`

Don't change an existing configuration serving SSO or the Microsoft Graph
connector. If compatibility is unresolved, the administrators need to resolve it
manually.

Bring back their non-sensitive confirmation that the supported configuration is
saved and any changed setup values. We'll recheck the affected setup before you
repeat the request in this agent's Test pane.

**End message.**

**Existing sign-in setup (Knowledge, single sign-on, or Microsoft Graph).** When
the maker says ESS should reuse an existing ServiceNow Knowledge, single
sign-on, or Microsoft Graph sign-in setup, in the first message or later, run
`python scripts/connect_servicenow_da.py --provider {PROVIDER} existing-identity-handoff --existing {knowledge|sso|graph}`
before anything else and send `chatMessage` verbatim. The maker's statement
supplies the context: never detect, ask about, or inspect existing Entra or
OIDC configuration. The command records only a non-identity marker
(`existingIdentity`) in the lifecycle state, so every later administrator
message keeps the compatibility-review wording instead of the standard setup
wording: the Entra and ServiceNow handoffs from `identity-direct-handoff`, the
connection guidance, the waiting reminder, and the final messages are already
switched by the marker and must be sent verbatim. The administrators confirm
compatibility first. The setup steps in their handoffs are reference only, and
ESS never changes the shared sign-in configuration. After their confirmation
the normal flow continues. Never fall back to the standard wording partway
through, and never write these messages yourself.

When a later reply matches one of these situations, run the same command with
`--situation <name>`, send `chatMessage` verbatim, end the turn for a waiting
reply, and follow `afterReply`. None of them shows a card or a Yes/No question,
and none records identity values:

- `setup-incomplete`, `setup-complete`: basic ADK setup is not finished, then
  finished.
- `entra-incomplete`, `two-client-ids`: the Entra
  administrator's reply is incomplete or names two registrations. A reply
  that gives the Client ID is enough; never ask anyone for the Directory
  (tenant) ID, because the controller takes it from the signed-in
  environment.
- `servicenow-incomplete`, `servicenow-fields-unnamed`: the ServiceNow
  administrator's reply is incomplete or does not name the User Claim and
  User Field.
- `coexistence-conflict`, `replace-configuration`, `different-registration`:
  the administrators report a conflict, ask to replace the existing
  configuration, or report a different registration. Never authorize
  replacing a configuration that serves SSO or Graph.
- `custom-claim`, `resolution-missing-mapping`: a custom claim or an agreed
  resolution is missing its mapping confirmation.
- `knowledge-connector`, `existing-connection`, `connection-disconnected`:
  the maker offers the existing Knowledge or SSO connection, names a
  connection, or the connection is not connected. Pass `--connection-name
  "<name the maker used>"` when one was named.
- `missing-consent`: only when a supported check shows missing consent, never
  from a generic failure.
- `metadata-url --metadata-url "<the URL the maker reports>"`: the same
  `/v2.0` diagnosis as `metadata-url-handoff`, in the compatibility-review
  wording.
- `waiting`, `resumed`, `blocked-finish`: the maker asks for status, comes
  back, or tries to finish while a confirmation is outstanding.
- `hr-prerequisite-self-confirmed` (HR agent only): the maker confirms the
  HR prerequisite without the administrator's reply.
- `topic-off`, `binding-missing`, `retry-after-fix`: a supported check shows a
  required built-in topic is off or the agent isn't linked to the selected
  connection (never from a generic failure). Send the matching message, apply
  only that targeted correction, keep the completed administrator setup and
  the Knowledge connector unchanged, then send `retry-after-fix`. In this mode
  the portal confirmation question reads "Is **{URL}** the portal employees
  should use for {IT tickets|HR cases}?" and the URL is saved only after the
  maker confirms.

**Second ESS agent reusing this instance's sign-in setup.** When the other ESS
ServiceNow agent (HR for IT, IT for HR) already completed sign-in setup in this
tenant and environment, the controller switches the administrator messages to
the reuse-review wording on its own; no marker or maker statement is needed and
the first-agent flow is unchanged. Send these controller messages verbatim and
never write them yourself: the Entra and ServiceNow handoffs from
`identity-direct-handoff` (lead-in, "Earlier {other agent} values/mapping -
review before using", "Review the existing setup first", and setup
instructions only for work the administrators determine is needed), the
connection guidance (select an existing connection available for this agent,
with no new connection required), and the final message, which states that the
other agent wasn't retested in this setup. The existing-identity marker takes
priority: when it is set, the compatibility-review wording above applies
instead. Both agents use the same wording with only the agent name swapped.

**Target changes (environment, agent, instance, tenant, or signed-in user).**
When the maker switches to another environment or agent, or says the instance,
tenant, or signed-in user is different, get the Message from the controller
instead of writing it: run
`python scripts/connect_servicenow_da.py --provider {PROVIDER} target-change-handoff --change {environment|agent|instance|tenant|user}`
(add `--target "<new environment or agent name>"` for an environment or agent
change, using the friendly name the maker used, never an ID or a URL). Send
`chatMessage` verbatim, then follow `nextCommand` and `afterReply`. The command
records nothing. Do not reuse evidence from the earlier target until the
permission and applicability checks pass; only the affected evidence is
reopened. For a promoted Test or Prod destination, the realm-change and
different-instance messages in `realms.md` apply instead. The Message for an
environment change is:

**Message:**

That changes the target environment. We'll check your permission for
**{Agent} in {New environment}** and which earlier setup information still
applies.

We won't reuse evidence from {Previous environment} without those checks.

**End message.**

When the existing sign-in setup marker is set, the last line is "We won't assume
that the connection or test evidence from {Previous environment} applies
there." The command applies it automatically.

**HR service areas empty (HR agent only).** When the maker reports that the
HR service-area list is empty (for example when creating an HR case), get the
Message from the controller instead of writing it: run
`python scripts/connect_servicenow_da.py --provider {PROVIDER} empty-service-areas-handoff`
(add `--realm test` or `--realm prod` for a Test or Prod destination), send
`chatMessage` verbatim as the whole reply, and follow `endTurn` and
`afterReply`. The command records nothing. Never claim the employee's roles
were checked, never assign a role, and never treat the empty list alone as
proof of the cause. For the IT agent the command returns `no-diagnosis`; this
scenario does not apply. Do not ask a Yes/No question. When the maker returns,
any message means they want to continue: record only the administrator's
non-sensitive reply, rerun the recheck of the affected setup, then ask them to
repeat the HR request in the Test pane and tell us whether the service areas
appear. The Dev Message is:

**Message:**

An empty HR service-area list can occur when the signed-in employee doesn't have
the required ServiceNow HR access.

Ask your ServiceNow administrator to review the access for the account used in
this request through your organization's normal process. The administrator
instructions identify the applicable roles: `sn_hr_core.basic`,
`sn_hr_core.manager`, or `sn_hr_core.admin`.

Return with their non-sensitive reply after any required access work is
complete. We'll recheck the applicable setup. Then repeat the HR request in this
agent's Test pane and tell us whether the service areas appear.

**End message.**

**The Test request didn't return the expected results.** When the maker says
this agent's Test pane request did not return the expected results (including
when another ESS agent or Knowledge still works), get the Message from the
controller instead of writing it: run
`python scripts/connect_servicenow_da.py --provider {PROVIDER} test-failure-handoff`,
send `chatMessage` verbatim as the whole reply, and follow `endTurn` and
`afterReply`. The command records nothing and is a plain chat question: no card,
no Yes/No. Never assume a shared identity failure merely because this agent's
request failed. Add `--reported-claim "<claim>" --reported-user-field "<field>"`
only when the administrators' reply or the maker's evidence actually names the
claim and User Field; the controller names the mismatch only when they differ
from the saved mapping, and otherwise asks for the specific error or result. Ask
only for what is still missing, and never for the whole setup history. Missing
consent or a `/v2.0` metadata URL is named only when a supported check or an
actual reported URL shows it (use `metadata-url-handoff` for the URL); never
infer either from a generic failure. When the maker returns, any message means
they want to continue: record only the administrators' non-sensitive reply,
recheck the affected setup, then ask the maker to repeat the request in the
Test pane. The controller picks the variant itself and names the other agent
(HR or IT) only when that agent is actually connected, uses the existing-identity
wording when the marker is set, and uses the payroll wording when the saved
User Claim is a custom claim. The first-agent Message without identity evidence
is:

**Message:**

The request didn't return the expected tickets. We'll check the setup
information already supplied to narrow down the problem.

If more information is needed, we'll ask for the specific error or result—not
the whole setup history.

We haven't identified the cause yet.

Did the Test pane show an error, an empty result, or something else? If there
was an error, send only its text without ticket contents, employee identifiers,
tokens, or other secrets.

**End message.**

When another agent is connected, the first paragraph names the agent
("IT didn't return the expected tickets. We'll check the IT setup information
already supplied to narrow down the problem.") and the second ends "not the
whole HR setup history." With the existing sign-in setup marker, the second
paragraph is "If more information is needed, we'll ask for the specific result
or error—not the whole setup history." With a custom (payroll) User Claim, the
Message is "That doesn't match the result you expected. We'll check the
available setup information before asking you for anything else." followed by
"We can't identify the cause from the information available yet." and "Did the
Test pane show an error or only an empty result?" with the same secrets caveat.

With evidence that the claim and User Field differ from the saved mapping, the
reply continues after its first paragraph with the mismatch text for the
variant. For a second agent it is:

**Message:**

The supplied evidence shows a mismatch between the sign-in claim and ServiceNow
user field.

Ask your ServiceNow administrator to review the mismatch with your Entra
administrator and confirm a supported mapping that accounts for the shared
setup's existing uses. Don't change an existing OIDC configuration serving SSO
or the Microsoft Graph connector.

Bring back their non-sensitive confirmation that the configuration is saved and
supports IT, the exact User Claim and User Field, and any changed registration
or claim values. If a custom claim changed, also bring back its completed-setup
confirmation for the intended employees.

We'll recheck the affected setup before you repeat the IT request in this
agent's Test pane.

**End message.**

For the HR agent the same message is used with HR and IT swapped and "cases" for
"tickets".

**Claim attributes missing.** When the Entra administrator says the identifiers
are not populated for every employee who will use this agent, pause the claim
and show the following. Never populate directory attributes or audit employee
records:

**Message:**

The custom-claim setup is paused until the identifiers are populated for the
intended employees.

Ask your Entra administrator to complete that work and return confirmation
that the claim setup is complete. You don't need to send an employee list or
anyone's identifier here.

**End message.**

**Claim still in email format.** When the Entra administrator says the custom
claim still has the default email format, show the following. Never ask the
maker to choose a claim transformation or edit the application:

**Message:**

The claim setup isn't ready yet.

Ask your Entra administrator to review the format guidance in Part 4 of their
message and confirm the completed claim setup. The Client ID stays in place.

**End message.**

**Entra error during claim configuration.** When the Entra administrator hits
an error after adding the custom claim, show the following. Never claim that a
particular setting will fix an error the available information does not
establish:

**Message:**

Ask your Entra administrator to review the error using the claim-customization
guidance in Part 4 of their message.

Return with their confirmation that the claim setup is complete before we
continue. Don't send tokens, signing keys, or certificate material here.

**End message.**

**Administrator replies contradict each other.** When the Entra and ServiceNow
replies name different claims, record nothing new and never change either
administrator's mapping. Treat optional email claims as no evidence that email
is the intended identifier. Show the following with the two claim names
substituted:

**Message:**

The administrator replies name different claims: Entra confirmed
`{ENTRA_CLAIM}`, while ServiceNow reported `{SERVICENOW_CLAIM}`.

Send both replies to the administrators and ask them to agree on a supported
claim and matching ServiceNow field that accounts for any existing uses. Bring
back their non-sensitive confirmation of the completed claim setup, saved
mapping, and any changed registration or claim values.

We'll recheck the affected setup before continuing. Don't include employee
identifiers or secrets.

The confirmed Client ID stays in place.

**End message.**

**Maker waits for the claim.** When the maker says they are waiting for the
custom claim to be configured, show the first Message. When they return, show
the second, rerun `resume-handoff` (which rechecks permission), and resume at
that waiting action rather than restarting the administrator instructions:

**Message:**

We're waiting for your Entra administrator's confirmation of the configured
claim.

When they reply, paste their non-sensitive confirmation that the claim setup is
complete, plus the exact configured claim name. Don't include employee
identifiers or secrets. The confirmed Client ID is already recorded for this
run.

**End message.**

**Message:**

We're continuing the ServiceNow setup for **{AGENT_NAME} in
{ENVIRONMENT_NAME}**.

We're rechecking your permission before we continue. Then, bring back your
Entra administrator's confirmation that the custom-claim setup is complete and
its exact configured name.

**End message.**

**Resource URI holds the claim name.** When a supported connection check shows
that the connection's Resource URI contains the claim name instead of the Entra
app's Client ID, show the following with the claim name, the recorded Client
ID, and the agent substituted. Never delete or silently replace a shared
connection, and never return to Entra registration:

**Message:**

The connection's **Resource URI** is set to `{CLAIM_NAME}`. That field needs
the Entra app's **Client ID**, not the claim name.

If this connection is only used by this agent, correct it to `{CLIENT_ID}` in
the supported connection setup. If it is shared, select or create a separate
supported ESS connection for this agent rather than changing the shared
connection.

Return here and tell us which connection you used. We'll check this agent's
connection and link before continuing. The administrator-confirmed mapping stays
in place.

**End message.**

**Knowledge-only request.** When the maker asks to configure ServiceNow
Knowledge instead of connecting an ESS agent, show the following and do not
start or infer an ESS target from the existence of Knowledge:

**Message:**

We can connect Employee Self-Service HR or IT to ServiceNow, but we can't
configure the ServiceNow Knowledge connector.

Use the [ServiceNow Knowledge connector guidance](https://learn.microsoft.com/en-us/microsoftsearch/servicenow-knowledge-connector)
for that setup.

**End message.**

**Unclear ServiceNow administrator return.** When the ServiceNow reply says
the work is done but does not confirm the saved configuration or does not name
both the **User Claim** and the **User Field**, never infer the missing value
and never ask the maker to interpret settings. Record nothing, then show the
Message that matches what is missing (the first when neither value is named,
the second when the claim is named but the User Field is missing). Statements
that an existing Knowledge or single sign-on setup "already works" use the
next block instead:

**Message:**

Thanks. Please ask your ServiceNow administrator to confirm that the
configuration is saved and name both the **User Claim** and **User Field**.

That will clarify which settings identify the signed-in employee.

**End message.**

**Message:**

We have the saved-configuration confirmation and User Claim `{CLAIM_NAME}`.
Ask your administrator which **User Field** they selected.

Send that value on its own.

**End message.**

**Administrator says only "already working".** A bare statement such as
"Knowledge already works" or "we use email" never confirms the setup and never
establishes the User Claim or User Field. Never infer `email` or **Email**.
Show the first Message for the bare statement and the second for "we use
email":

**Message:**

Ask your ServiceNow administrator to confirm that the configuration is saved
and supports ESS, and name its **User Claim** and **User Field**.

Paste their reply here without secrets, or send the missing items individually.
You don't need to repeat the Entra values.

**End message.**

**Message:**

Ask your ServiceNow administrator which **User Claim** and **User Field** they
confirmed for ESS. Send those values here.

**End message.**

**Different registration returned.** When the administrators resolve a
conflict manually and return a different Client ID, discard the earlier
confirmations tied to the old Client ID, never reuse the old metadata URL,
connection Resource URI, or mapping evidence, and show:

**Message:**

We'll check the setup information tied to the newly confirmed Client ID before
continuing.

Ask your ServiceNow administrator to confirm that the configuration for that
registration is saved and supports ESS, and provide its **User Claim** and
**User Field**. Bring back their non-sensitive reply and any other changed
setup values. We won't carry forward confirmation tied to the earlier Client
ID.

**End message.**

**Maker selects the Knowledge connector.** When the maker asks whether to
select the ServiceNow Knowledge connection for the ESS agent, show the first
Message, substituting the agent, the confirmed Client ID, and the ServiceNow
instance name. When the maker already has a supported ESS ServiceNow
connection, show the second. Reuse is never inferred merely because a
connection is named "ServiceNow":

**Message:**

That is the Knowledge connector, not the ServiceNow connection used by
**{AGENT_NAME}**.

In **{AGENT_NAME} > Settings > Connection Settings > ServiceNow**, create the
connection using **Microsoft Entra ID User Login**, `{CLIENT_ID}` as **Resource
URI**, and `{INSTANCE_NAME}` as **Instance name**.

Leave the Knowledge connector unchanged. Return here and tell us which ESS
connection you used. We'll check this agent's connection and link before
continuing.

**End message.**

**Message:**

You can select that existing ESS ServiceNow connection instead of creating a
duplicate.

Return here and tell us which one you selected. We'll check that
**{AGENT_NAME}** can use it.

**End message.**

**Knowledge not retested.** When the maker disclosed during this run that
ServiceNow Knowledge shares the same sign-in configuration, append this
sentence to the final success paragraph as the last sentence, after the
statement that other requests and sign-in for other employees haven't been
verified. Never add it when Knowledge was not mentioned:

**Message:**

ServiceNow Knowledge wasn't retested.

**End message.**

**Existing SSO or Graph configuration conflict.** When the maker reports that
an existing OIDC configuration already serves SSO or the Microsoft Graph
connector and cannot be changed, never change or troubleshoot it. Show:

**Message:**

Send the reported conflict to your Entra and ServiceNow administrators. Ask
them to agree on a supported setup using the compatibility guidance in their
messages.

We won't change that configuration or troubleshoot the conflict. Bring back
their non-sensitive compatibility confirmation, saved-configuration
confirmation, User Field, and any changed registration or claim values.

We'll recheck the affected setup before continuing. Don't include employee
identifiers or secrets.

**End message.**

**Validation notices (controller-emitted).** For the situations below, get
the Message from the controller instead of writing it: run
`python scripts/connect_servicenow_da.py --provider {PROVIDER} validation-notice --situation {SITUATION}`
with the extra arguments listed, send `chatMessage` verbatim as the whole
reply, and follow `endTurn` and `afterReply`. The command records nothing and
shows no card or Yes/No. `--scenario {first-agent|second-agent|payroll}` is
derived from the saved state (second agent when another ESS agent already
uses the connection); pass `payroll` explicitly only for the HR payroll
custom-claim flow. When the command errors because the spec defines no wording
for that scenario, do not write one: name the actual blocker, its owner, and
the exact outstanding action instead. A saved existing-identity marker routes
the existing-identity situations to `existing-identity-handoff`; only the
context-free situations below are shared.

- `agent-chooser`: no saved state is needed. When the maker has not named an
  agent, ask the plain question instead of the Yes/No agent card, then map the
  reply to `agent-chooser --selection-key "prepared:{AGENT_ID}"` (or
  `another-agent --agent-link`).
- `instance-question` (first agent only): the plain question for the
  ServiceNow instance URL; never accept credentials.
- `knowledge-only-exit`: when the maker only wants ServiceNow Knowledge and no
  ESS connection, send the message and end the turn. Start no setup and record
  nothing.
- `sso-conflict`: use this instead of the hand-written conflict Message above.
  Never change or troubleshoot the existing SSO or Graph configuration.
- `claim-contradiction` (add `--entra-claim` and `--servicenow-claim`, only
  when the administrators' replies name different claims).
- `blocked-finish` (add `--waiting-for servicenow`, or `--waiting-for
  entra-claim` for payroll): when the maker asks to finish, or reports the
  integration done, while required setup is incomplete. Claim neither success
  nor completion. When a different blocker remains, name it instead.
- `connection-disconnected` (add `--connection-name "<friendly name>"`, never
  an ID or a URL) and `no-usable-connection` (second agent; the confirmed
  Client ID and instance name must already be recorded).
- `resource-uri-claim-name` (payroll; add `--claim-name "<claim>"`): only when
  the maker's reply shows the connection's Resource URI is set to the claim
  name.
- `topic-off` and `agent-not-linked`: only after a supported check or the
  maker's observed result shows it. Then run the topics or connection step and
  `retry-request`.
- `missing-consent`: only when a supported check identifies the missing
  consent. Never infer it from a generic failure, and never claim a live-tenant
  consent check ran when it did not.

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
