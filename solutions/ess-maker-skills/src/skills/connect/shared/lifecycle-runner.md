# Connect Lifecycle Runner (Shared)

The single, provider-agnostic routine that drives **any** integration's
connect lifecycle from its contract file. A provider (Workday, ServiceNow, any
future ISV) supplies a contract (`lifecycle-contract-schema.md`) plus its own
action fragments for mutating phases; this file contains zero
integration-specific logic. Adding a new provider never requires changing this
file when its needs fit the documented contract; shared backward-compatible
contract evolution belongs here rather than in provider-specific branches.

Every **Message** block is the exact text to show the user after rendering its
declared placeholders. Do not rephrase, add commentary, or tell the user what
tools you are calling or what files you are reading. Never surface a checkpoint
ID, phase ID, file path, or the word "checkpoint"/"contract"/"state file" to the
user. Contract phase `label` values are customer-facing text, not phase IDs.

**Visible ServiceNow handoff style:** Render one task per question with real
blank lines and markdown-friendly bullets. Put literal bold headings on their
own lines and separate sections with two newlines, for example
`**Purpose**\n...\n\n**Owner**\n...\n\n**Action**\n1. ...`.
Use numbered or bulleted lines under Action so renderers cannot collapse the
question into one paragraph. Say exactly what value or choice the user must
provide. Show only current missing work; do not repeat passed steps or
internal IDs/status machinery. Prefer buttons with no recommended,
preselected, default, or automatic answer.
Freeform is allowed only for one genuinely unknown value: the public
ServiceNow instance URL, employee portal URL, or an unknown/replaced Entra
Application client ID. Never combine multiple values in one blank field.
Detailed technical navigation belongs in the linked administrator guide or
workbook Steps page, while the question names the result to return.

**Inputs from the calling file:**
- `PROVIDER` — the provider key (e.g. `"workday"`), matching a contract at
  `src/skills/connect/{PROVIDER}/contract.json`.
- `AGENT_SLUG` — the exact caller-selected agent slug. Existing callers may
  pass the active agent slug, while a chooser may select another locally
  configured agent without changing `.local/config.json.activeAgent`.

**ServiceNow phase-progress extension:** ServiceNow callers receive a
`servicenow.phase-progress.v1` object inside the mandatory `resume-handoff`.
This is display metadata derived from the same contract, lifecycle state, and
invocation-local executed/verified markers; it adds no remote read, polling,
or progress process. Each item retains its internal contract `label` for
validation and supplies a short `customerLabel` for every visible checklist.
Other providers retain this runner's existing output.

After plan acceptance, show its short headline once and its current phase
checklist. Re-emit the freshly returned checklist only on an actual phase
completion/next-phase transition, waiting pause, or blocked/error transition.
A cached `done` phase displays **Rechecking** until this invocation adds its
verified marker. Before each meaningful action or checkpoint run, show the
exact current-phase `startText`. After `applied`/`recorded`, show
`actionFinishedText` and continue checking; an action receipt is never phase
completion. When an action asks a question, prepend the exact `questionText`
to the durable question body; it contains the latest checklist with the
current phase marked waiting. Use `waitingText` for the pause. This does not
add a question. For a failure, show `errorChecklistText`,
`needsAttentionText`, and the exact full remediation returned by the
checkpoint. For ServiceNow, that remediation is the branch-loaded recovery
handoff: problem, category, owner, exact location, values, action, success
condition, and local recheck/resume point. Render it in full in the same
visible turn; do not summarize it into the generic stop message.

**ServiceNow preflight pending input:** When the preflight provider action
returns `instanceInputRequired: true`, show its exact `instanceQuestion` and
stop with `ACTION_RESULT = "waiting"` before running the preflight checkpoint.
This is normal Maker target confirmation, not a blocking checkpoint result.
Do not render the checkpoint's `NotConfigured` recovery handoff around or
before this question. If the Maker chooses **Provide another ServiceNow
instance URL**, show the exact returned `manualInstanceQuestion` once. A real
discovery error remains embedded in those questions; it does not convert an
empty or failed discovery into success.

The ServiceNow provider `resume-handoff` also enforces this boundary. If it
returns top-level `pendingInput`, show `pendingInput.question` exactly and stop
without running or reconstructing a checkpoint command. Use
`pendingInput.choiceValues` to translate a selected option. Only
`pendingInput.manualQuestion` may be shown after **Provide another ServiceNow
instance URL**. This barrier covers first-run and historical `NotConfigured`
state so normal unanswered Maker input is never rendered as an eight-section
configuration failure.

Only a verified phase may display **Complete — checked**,
**Complete — admin confirmed**, or **Reused — checked**. Waiting remains
waiting; Test requires the actual maker result, and any contract-defined
interactive mutation requires its actual maker choice and validation. Show
`finalText` only when the controller
returns complete and every contract phase has a current invocation verified
marker. Keep these updates short: one current step and one result update, not
per-subrequest heartbeats or repeated full tables.

**Files:**
- **Contract (read-only):** `src/skills/connect/{PROVIDER}/contract.json`
- **State (read/write):**
  `.local/connect/{PROVIDER}/agents/{AGENT_SLUG}/lifecycle.json` — shape
  defined in `lifecycle-contract-schema.md`.

---

## L.0 — Load the contract and state

Read `src/skills/connect/{PROVIDER}/contract.json`. If it does not exist,
**stop and report** — the calling file named a provider with no contract.

Resolve `contractRevision` as the positive integer in the contract, defaulting
to `1`. If the canonical state file already exists and the contract has
`stateMigrationCommand`, replace `{agentSlug}` with the exact `AGENT_SLUG`,
then run that exact checked-in command before reading the state. A migration
failure is blocking; do not discard or recreate the state.
Do not run a migration command on a first run, because the plan must be
accepted before the initial state file is written.

If the contract has `connectConfig` and that file exists, add
`--connect-config "{connectConfig}"` to every FlightCheck command in this
runner. If it does not exist, omit the argument; do not substitute another
provider or architecture's state.

If `AGENT_SLUG` is empty, stop and ask the user to run `/setup`; agent-specific
mutation and validation must never fall back to scanning every local agent.

Read `.local/connect/{PROVIDER}/agents/{AGENT_SLUG}/lifecycle.json`. If it
does not exist, this is a first run. Do not write a state file before the plan
is accepted. For plan rendering only, treat every contract phase as pending
and `attested` as false. If the contract has `stateInitializationCommand`,
the provider owns the complete canonical initial state; do not construct or
persist a generic substitute. Providers without that command retain the
generic first-run state described in L.1.

Track this distinction explicitly as `stateExists: false` /
`planReason: "first-run"` for an absent state and `stateExists: true` for an
existing state. A contract-revision mismatch on an existing attested state is
`planReason: "revision-reapproval"`, never a first run.

If existing state identifies a different provider or agent slug, stop instead
of reusing it. Never copy plan or role attestation across provider/agent
identity.

For backward compatibility, treat a missing `roleAttestations` object in an
older state file as `{}`. Do not infer an attestation from `attested`,
`attestedAt`, a completed phase, or a prior action.

Merge contract evolution without deleting provider-owned state: for every
contract phase absent from `phases`, add
`{status: "pending", checkpointResults: {}}`. Preserve every existing phase,
evidence object, transaction, admin-operation record, and unknown
forward-compatible key. The runner owns only generic lifecycle keys beneath
`phases`; provider commands own their evidence and operation state.

Initialize an invocation-local empty set named `executedActionPhases`. Add a
phase ID after its action returns `applied` or `recorded`; this prevents an
`every-invocation` action from running twice during L.2 and L.4 of the same
invocation.

Initialize a second invocation-local empty set named `verifiedPhases`. This set
records only phases whose current live checkpoint results satisfied their
completion statuses and acknowledgement requirements during this invocation.
Never initialize it from persisted `lastVerifiedAt`, `status: done`, or any
earlier invocation.

---

## L.1 — Show the plan and get attestation

Skip this section only when the state file has `attested: true` and
`acceptedContractRevision` equals the current contract revision. A contract
revision change must show the new complete plan before a newly introduced
phase runs.

Build the plan from the contract, in phase order:
- One line per phase using its `label` verbatim.
- Collect the **union** of `requiredRole` across every `mutates: true` phase,
  de-duplicated, in the order phases appear.
- Append the contract's optional display-only `planRoles`, de-duplicated.
  These roles explain external admin ownership; they do not create a role gate
  and must never be treated as authorization for an action.

Render this complete plan as an ordinary visible agent response before calling
`vscode_askQuestions`. It is a **Message**, not tool commentary or a question
body. Showing the plan is not execution approval.

**Message:**

Here's what I'll do to connect this agent to {displayName}:

{numbered list of every phase label, in contract order}

Access needed: {comma-separated required and display-only plan roles}.

I'll check as I go and stop to explain anything that needs attention.

Current step: Awaiting approval to start.

**End message.**

Before sending this ordinary reply, render every placeholder and verify that
the rendered plan contains every contract phase label exactly once, in order,
and all plan roles once. Stop if it is incomplete. The current-step line
describes the approval wait on both first run and revision reapproval; it does
not mark any phase executing or complete.

If available host information says ordinary replies cannot be displayed, or
the host reports a display failure, explicitly report the host display
limitation and stop before asking for approval or starting. Do not silently
start or move the complete plan back into the question. Verify the prepared
reply's content, not an unobservable render result: sending a reply is not
proof the host displayed it. This ordinary reply does not promise a pinned,
persistent, or non-collapsible UI.

After sending the complete ordinary reply, use `vscode_askQuestions` with only
this one short confirmation question:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "Start connection",
    "question": "Ready to start?",
    "options": [
      { "label": "Yes, let's go" },
      { "label": "Not now" }
    ],
    "allowFreeformInput": false
  }
]
```

Keep its options label-only, with no recommended, preselected, default, or
automatic answer. The plan, roles, and progress belong only in the ordinary
reply. This is the only plan confirmation question; initialize or continue
only after the user explicitly selects **Yes, let's go**.

**If "Not now":** Stop here. On a first run, do not write the state file. On a
contract-revision re-attestation, preserve the existing state unchanged,
byte-for-byte. The next invocation should show this same plan again.

**If "Yes, let's go" on a first run (`stateExists: false`):** If the contract has
`stateInitializationCommand`, replace `{contractRevision}` and `{agentSlug}`
in that exact checked-in command and run it now. Require exit code `0` and a
structured `status: "initialized"` success result. Then read the canonical
state file and verify its provider, profile when present, agent slug, agent ID
and environment ID when present, `attested: true`, and exact
`acceptedContractRevision`. Verify every contract phase exists at
`status: "pending"` with empty checkpoint results. Any command failure,
missing file, malformed schema, identity mismatch, missing phase, or
non-pending phase blocks the lifecycle; never write a generic fallback and
never silently repair an existing file.

If the contract has no initialization command, write the historical generic
state now with `provider: PROVIDER`, `agentSlug: AGENT_SLUG`,
`attested: true`, `attestedAt` = current UTC timestamp,
`acceptedContractRevision: contractRevision`, `roleAttestations: {}`, and
every phase at `status: "pending"` with empty checkpoint results.

**If "Yes, let's go" after a contract revision changed:** update only
`attested`, `attestedAt`, and `acceptedContractRevision`, plus missing phases
initialized in L.0. Do not reset or delete existing phase status, action
receipts, evidence, transactions, role attestations, or provider-owned admin
progress.

This path has `stateExists: true`,
`planReason: "revision-reapproval"`, and
`stateInitializationRequired: false`. Do **not** run
`stateInitializationCommand` after this update. If a host redundantly invokes
the provider's `initialize-state` command anyway, only a typed
`status: "existing-compatible-state"` result for the exact provider/profile/
agent/environment/ring, attested state, and accepted current revision is a
safe no-op. It must preserve the state byte-for-byte. Any other existing-state
result is blocking.

Continue to L.2. Accepting the plan does not claim a
role; the first required role gate remains explicit.

---

## L.2 — Live re-verification on resume

**This is the load-bearing rule of this file.** A phase recorded `status:
"done"` in the state file from an earlier turn is a *cache*, not a fact. Never
report a phase complete, and never skip straight past it, without a live
checkpoint run from **this** invocation confirming it still holds. Environments
drift — a connection can be removed, a topic redirect can be reverted outside
this tool — and trusting a stale checkbox has already caused a real bug in
this family of skills once; do not reintroduce it.

Walk the phases in contract order and re-verify only the contiguous prefix
whose state is `done`. Stop the prefix scan at the first non-`done` phase;
never re-run a later phase's action or checkpoints across that gap.

For every phase in that contiguous `done` prefix:

1. If the phase has `actionExecution: "every-invocation"`, execute its
   `actionDoc` first using L.4a without re-showing the plan. Run each such
   action at most once per invocation. If its gate stops, the action is
   cancelled, or the action fails, set this phase to `in-progress`, reset
   every later phase to `pending`, clear
   `actionApplied`/`lastActionAt`/`rollbackPushGlob` on the current and later
   phases, persist, and stop. `applied` or `recorded`
   updates `actionApplied` and `lastActionAt` but does not complete the phase.
2. Re-run every checkpoint the phase lists (see L.4's checkpoint-running
   steps — reuse that exact mechanism here, silently, without re-showing the
   up-front plan).
3. If every checkpoint still resolves to a status allowed by that phase's
   `completionStatuses`, and every `Manual`/`Warning` result has a matching
   persisted `checkpointAcknowledgements` entry for that checkpoint and
   status,    update `lastVerifiedAt`, add the phase ID to `verifiedPhases`, and leave the
   phase `done`. For an
   acknowledgement whose source is `matching-action-evidence`, also re-resolve
   the configured safe evidence path and require the current evidence kind and
   `recordedAt` to equal the acknowledgement provenance. If they differ or the
   evidence disappeared, remove that acknowledgement and treat the result as
   unacknowledged. Do **not**
   re-render the U.0 table for a phase that was already `done` and stays
   `done` on resume — only surface output for phases that change state or that
   are not yet done.
4. If any checkpoint resolves to a status **outside** that phase's
   `completionStatuses`, **or** an allowed `Manual`/`Warning` result lacks a
   persisted acknowledgement matching the checkpoint and current status, the
   cached completion has regressed. This includes `Warning`, `Skipped`,
   `NotConfigured`, and unacknowledged `Manual`/`Warning` results — not only
   `Failed`/`Error`. Set **every phase after it** back to `pending` (later
   phases may have depended on this one still holding). Clear `actionApplied`,
   `lastActionAt`, and `rollbackPushGlob` on this phase and every later phase
   so a `"once"` action can run again through a fresh gate
   and fresh rollback checkpoint. A rollback checkpoint from an earlier
   invocation must never be reused after drift.
   Remove this phase and every later phase ID from `verifiedPhases` and
   `executedActionPhases`. A marker is invocation-local routing evidence, not
   a substitute for the updated persisted state.

   - For `Failed`/`Error`, set the phase to `blocked`, persist the current
     checkpoint results, render the result and its exact full remediation
     without executing L.4b rollback, and stop for remediation. For
     ServiceNow, a missing structured recovery handoff is an
     execution-contract error: do not replace it with a generic retry
     sentence.
   - For every other regression, set the phase to `in-progress`, persist the
     current checkpoint results, and render the result without executing L.4b
     rollback. End the completed-prefix scan and continue to L.3 in this same
     invocation. L.4 must run the reset phase's provider action before its
     checkpoints, including any interactive question in the action document;
     do not end the turn merely because the cached completion regressed.

Once every previously-`done` phase is confirmed, or the prefix scan ends on a
non-fatal regression, continue to L.3. A `Failed`/`Error` regression already
stopped above.

---

## L.3 — Find the current phase

Run the executable decision controller before choosing an action or checkpoint:

```text
python scripts/connect_lifecycle.py next-step \
  --provider "{PROVIDER}" \
  --agent-slug "{AGENT_SLUG}" \
  {one --executed-action "{PHASE_ID}" argument for every phase in executedActionPhases} \
  {one --verified-phase "{PHASE_ID}" argument for every phase in verifiedPhases}
```

Parse exactly one `DA_LIFECYCLE_NEXT_JSON:` object. It is the required
execution boundary, not optional diagnostics. Validate its schema version,
provider, agent slug, contract revision and phase identity against the loaded
contract/state. A command failure, malformed result or identity mismatch
blocks the lifecycle. Do not fall back to interpreting
`resumeActionWhenIncomplete`, `actionApplied` or phase status yourself.

Controller decisions:

- `plan-required` — return to L.1. Read `stateExists`, `planReason`,
  `stateInitializationRequired`, and `stateInitializationCommand`; never infer
  first-run initialization when `stateExists` is true.
- `complete` — go to L.5.
- `run-action` — set `currentPhase` from the result and continue to L.4a. Read
  only the exact returned `actionDoc`.
- `run-checkpoints` — set `currentPhase` from the result and continue directly
  to L.4b.

After an action or checkpoint updates state and returns to L.3, rerun the
controller. Never reuse a prior decision after state changed.

---

## L.4 — Run the current phase

### L.4a — Run the provider action

The controller has already decided that this action must execute. Do not
re-evaluate or override its decision from prose. The following rules define
how to execute the returned action safely:

- `actionExecution` is `"every-invocation"` and this phase's action has not
  run during this invocation; or
- `actionExecution` is omitted/`"once"` and `actionApplied` is not yet `true`;
  or
- `actionExecution` is omitted/`"once"`,
  `resumeActionWhenIncomplete` is `true`, the phase status is not `done`, and
  this phase's action has not run during this invocation.

For `resumeActionWhenIncomplete`, the earlier `actionApplied`, `lastActionAt`,
transactions, rollback receipts, and provider evidence are historical facts,
not authorization for the newly observed state. Preserve them while the
provider action performs fresh read-only inspection. The action must expose
the current actionable state and obtain a new maker choice before another
mutation. It may return `applied` as a verified no-op when fresh inspection
shows the target already satisfied. Never automatically replay the prior
mutation or infer the old maker choice applies to newly discovered resources.

For a phase with `mutates: true`, resolve its `gateMode` (default
`"attested"`).

**Programmatic mode:** always apply `permission-gate.md` with
`REQUIRED_ROLE` = the phase's `requiredRole`, `GATE_MODE = "programmatic"`,
and the phase's `roleQuery`. Treat the query as a pass only if it returns one
of `roleQueryPassNames`. Never reuse `roleAttestations` for this mode,
including after resume.

**Attested mode with historical/default phase scope:** apply
`permission-gate.md` for this phase as before.

**Attested mode with `attestedRoleScope: "lifecycle"`:** inspect
`roleAttestations.{requiredRole}`. Reuse it only when all are true:

- `verifiedBy` is `"attested"`;
- `provider` exactly equals `PROVIDER`;
- `agentSlug` exactly equals `AGENT_SLUG`;
- the map key exactly equals the phase's `requiredRole`.

When valid, set `GATE_RESULT = "pass"` without asking again. When absent or
invalid, apply the normal attested `permission-gate.md`. On pass, persist:

```json
{
  "verifiedBy": "attested",
  "provider": "{PROVIDER}",
  "agentSlug": "{AGENT_SLUG}",
  "attestedAt": "<current UTC timestamp>",
  "note": "<GATE_EVIDENCE.note>"
}
```

under `roleAttestations.{requiredRole}` and write the lifecycle state before
executing the action. Non-mutating actions do not run a role gate.

**If the gate returns `"stop"`:** stop here. Leave the phase `in-progress` in
the state file, clear its `actionApplied`, `lastActionAt`, and
`rollbackPushGlob`, and write it now so the next invocation resumes at this
same gate rather than re-showing the whole plan. Keep valid lifecycle-scoped
role attestations unchanged.

**If the gate returns `"pass"` (or the action is non-mutating):** if the phase
names a `rollbackLabel`, save a checkpoint first:

```
python scripts/checkpoint.py "{rollbackLabel}"
```

Then read the phase's `actionDoc` file and follow it completely — it contains
its own Message blocks and tool calls and must return an explicit
`ACTION_RESULT`:

An admin-owned high-level phase has exactly one pause boundary per attempt.
Its action must present the phase purpose, responsible role, complete bundled
instructions, completion criteria, and requested non-secret evidence before
asking one completion question. It must not persist or ask separate questions
for checklist items inside that phase. On resume, accept the one phase return,
run the phase's complete verification set, and only then advance.

The ServiceNow Entra action has one bounded pre-handoff exception when its
producer returns `handoffMode: identity-requirement`: show that routing-only
Maker question before any workbook exists. Its options identify only the
intended user identifier type; they are not `Completed`/`Not yet` admin
evidence. Pass the returned question to the question tool unchanged: its
options are label-only. Use the separate `identityRequirementChoices`
envelope mapping to translate the selected label to the recorder's CLI choice;
never add `value` or another unsupported option field. A specific answer may
persist only the scoped routing intent, then
the caller reruns the producer and shows the normal one-workbook admin
completion question. `Not sure` returns waiting, writes no receipt, and
generates no workbook. This clarification must not set `actionApplied`, mark
the phase done, confirm claim emission, or replace the later admin completion
question. Once a valid scoped requirement receipt exists, do not ask the
routing question again. Never dereference a missing `workbookPath` from the
routing response.

For every interactive provider action, the question tool body is the durable
visible handoff. Read the action document's
`<!-- visible-handoff-question:v1 -->` JSON payload, render its placeholders,
and use that supported `header`/`question`/`options`/`allowFreeformInput`
shape exactly. The complete L.1 plan has already been shown in its ordinary
reply; do not repeat it inside `{CURRENT_PROGRESS}`. Replace that placeholder
with every checkpoint result produced in this invocation but not yet shown
inside a prior question body. Include checkpoint status, description, result,
and remediation when non-empty. Keep the ServiceNow current-phase checklist
and `questionText` rules unchanged.

`{CURRENT_PROGRESS}` is bounded FlightCheck/lifecycle display content only.
Never insert tokens, raw prompts or responses, employee/case data, full config
or component payloads, or secret-bearing tool output into a question.

Do not call the question tool if the payload is missing, malformed, truncated,
still contains placeholders, omits the action owner/instructions/completion
evidence, or references "above" content that is not in the question itself.
Stop and report the visible-handoff contract error instead of accepting
confirmation without current instructions. For these provider-action handoffs,
ordinary assistant messages remain useful, but are never the only copy of
content required to answer a question.
A completed phase on quiet resume does not redisplay its runbook; this rule
applies only when the action genuinely needs a new interactive pause.

- **`"applied"`** — the mutation or verified no-op completed successfully.
  Set `phases.{id}.actionApplied = true`. If the phase has
  `rollbackPushGlobFromAction: true`, require the action to return
  `ACTION_ROLLBACK_PUSH_GLOB` as one normalized relative path beneath
  `topics/`, with no `..` segment and no wildcard characters; persist it as
  `phases.{id}.rollbackPushGlob`. If the path is missing or unsafe, set the
  phase to `blocked`, write `actionApplied = true` immediately, and stop for
  manual attention; the live mutation may already have happened and must not
  be repeated without a known exact rollback scope. With a valid path, write
  the state file immediately.
- **`"recorded"`** — a non-mutating evidence action completed successfully.
  Set `phases.{id}.actionApplied = true`; this preserves the default
  `"once"` execution contract without creating rollback state.

  For either successful result, set `phases.{id}.lastActionAt` = now, mark the
  phase action as executed in the invocation-local set, and write the state
  file immediately. This does not complete the phase; continue to its
  checkpoints.
- **`"waiting"`** — a delegated administrator operation or interactive
  question is still pending. For a normal first action, keep
  `actionApplied = false`. For a `resumeActionWhenIncomplete` re-entry,
  preserve the historical `actionApplied`, `lastActionAt`, transaction, and
  rollback receipts because no new action completed. Leave the phase
  `in-progress`, preserve all provider-owned question, discovery, decision,
  and operation evidence exactly, write the state file, and stop. This is a
  resumable pause, not cancellation, failure, or completion. An unanswered
  question remains pending and is not cancellation.
- **`"cancelled"`** — the user declined before mutation. Keep
  `actionApplied = false` and remove `lastActionAt` and `rollbackPushGlob` for
  a normal first action. For a `resumeActionWhenIncomplete` re-entry, preserve
  those historical fields and all prior transactions. Leave the phase
  `in-progress`, write the state file, and stop. Do not run the phase
  checkpoints.

Any missing, unknown, or failure result is not success. For a normal first
action, keep `actionApplied = false` and remove `lastActionAt` and
`rollbackPushGlob`. For a `resumeActionWhenIncomplete` re-entry, preserve the
historical fields and prior transactions because they describe the earlier
attempt, not the failed new inspection/choice. Report the action failure,
write the state file, and stop.

Any gate stop, cancellation, waiting result, action failure, rollback or
checkpoint failure must not add the phase to `verifiedPhases`. When it
invalidates current/later phase state, remove the current and later phase IDs
from both invocation-local marker sets before stopping or returning to L.3.

### L.4b — Run the phase's checkpoints

For each checkpoint target the current phase lists, run:

```
python scripts/flightcheck/cli.py --checkpoint {TARGET} \
  --agent-slug "{AGENT_SLUG}"
```

If the contract sets `checkpointResultMode: "compact-stdout-v1"`, generate a
new opaque `CHECKPOINT_INVOCATION_ID` for this command and instead run:

```
python scripts/flightcheck/cli.py --checkpoint {TARGET} \
  --compact-result \
  --invocation-id "{CHECKPOINT_INVOCATION_ID}" \
  --quiet-auth \
  --agent-slug "{AGENT_SLUG}"
```

Capture stdout exactly. It must contain one JSON object and no surrounding
text. Parse and validate it fail closed before rendering or writing lifecycle
state:

- `schemaVersion` is exactly `flightcheck.lifecycle-checkpoint.v1`;
- `kind` is exactly `checkpoint-result` (a `checkpoint-error` object is a
  failure, never an empty/default result);
- `target` exactly equals `{TARGET}`;
- `targetKind` is exactly `fixed` or `family` as declared by the registered
  target;
- `identity.provider`, `identity.profile`, `identity.agentSlug`,
  `identity.agentId`, and `identity.environmentId` exactly match the accepted
  contract and current provider state;
- `invocation.id` exactly equals `CHECKPOINT_INVOCATION_ID`,
  `invocation.source` is non-empty, and `invocation.started` is non-empty;
- `results` is a non-empty array; an exact target emits only that checkpoint,
  and a family target emits only members of that family;
- every row contains the versioned checkpoint fields including
  `checkpointId`, `status`, `description`, `result`, `remediation`, links,
  roles, bounded evidence, severity, automation type, and remediation ID;
- statuses are known FlightCheck statuses, `overall` agrees with the rows, and
  `exitCode` is 1 exactly when a row is `Failed`, `Blocked`, or `Error`.
  `NotConfigured` and `Skipped` are evaluated, bounded non-ready results:
  their contract has `overall: "NOT_READY"` with `exitCode: 0`, preserves the
  target row and remediation, and is consumed by the normal phase-status
  rules below. They are not client, identity, execution, or contract errors.

Malformed, truncated, empty, extra-text, unsupported-version, wrong-target,
wrong-identity, wrong-invocation, zero-row, or internally inconsistent output
blocks the phase. Report the typed stderr/`checkpoint-error` condition; never
invent a success-shaped default and never fall back to an older result file.
Missing/failed required clients and a missing target row remain blocking
contract errors. Do not convert them into `NotConfigured` or `Skipped`.
This compact path writes no per-step `results.json`, history HTML, or latest
HTML. Render the validated rows directly with the same U.0/U.0a content and
status rules below. The contract must never contain tokens, raw prompts,
configuration/component payloads, employee data, or other secrets; preserve
only the bounded row evidence already approved for FlightCheck results.

If `checkpointResultMode` is absent, use the command and persisted report path
shown above and below unchanged.

When `TARGET` is a registered family/wildcard, start exactly one CLI process,
consume and render every matching emitted row, and persist each result under
its actual checkpoint ID. Do not invoke family members again as separate
processes. A family that emits zero matching rows blocks the phase.

For ServiceNow, the provider `resume-handoff` returns the complete exact
checkpoint `argv`, invocation marker, selected agent slug, and expected
provider/profile/agent/environment identity. Execute that argv verbatim and
validate the returned compact identity; never reconstruct it from
`activeAgent` or prose. A compact ServiceNow command without
`--agent-slug "{AGENT_SLUG}"` is an execution-contract error and must stop
before authentication or API reads.

If the contract has `connectConfig` and that file exists, add
`--connect-config "{connectConfig}"`. For agent-local checkpoints or profiles,
also add `--agent-slug "{AGENT_SLUG}"`. Use the same target and arguments when
re-verifying completed phases in L.2.

After each run, render the result using the exact U.0 and U.0a routines from
`src/skills/setup/shared/checklist-updater.md` (read that file's U.0/U.0a
sections and apply them verbatim against the validated compact rows, or against
`workspace/flightcheck/results.json` for a provider using the legacy transport
— do not re-implement or paraphrase that rendering logic here).

For every non-completing ServiceNow row with status `Blocked`, `Error`,
`Failed`, `NotConfigured`, or `Warning`, require the returned remediation to
contain these literal headings: `**Problem**`, `**Category**`, `**Owner**`,
`**Where**`, `**Values to use**`, `**Action**`, `**Success**`, and
`**Recheck and resume**`. Render the whole remediation in the same visible
row or question. If a heading is absent, stop as an execution-contract error
rather than showing an incomplete generic handoff. This validation applies
equally on first execution, completed-phase re-verification, and resume.
Other providers retain their existing remediation format.

Aggregate the phase's outcome using the phase's `completionStatuses`
(default `["Passed"]`) and the status rules in
`lifecycle-contract-schema.md`:

- **All checkpoints "count toward done"** (after any needed attestation for
  `Manual`/`Warning` results — ask the same style of yes/no confirmation
  `checklist-updater.md`'s U.2 uses when a result needs acknowledgement):
  before asking for a `Manual` row, inspect the phase's optional
  `manualAcknowledgementEvidence`. Skip the second generic question only
  when the action returned `applied` or `recorded` in this invocation, the
  current checkpoint status is exactly `Manual`, its safe `path` (with
  `{phaseId}` resolved to the current phase) points to a provider-owned object
  whose `status` is in `acceptedRecordStatuses`. Resolve its safe
  `evidenceObjectPath` beneath that record, or use the record itself when the
  configured value is `""`; that evidence object must have `kind` equal to
  `requiredEvidenceKind` plus a non-empty `recordedAt`. Require every
  configured `requiredValues` entry to match the evidence object exactly. For
  each configured `bindings` entry, resolve the
  safe relative `evidencePath` under that evidence object and safe provider-state
  `statePath`; both must exist and be equal. Reject paths with arrays, `..`,
  slashes, file syntax, unresolved placeholders, or non-scalar comparisons.
  Persist the acknowledgement with
  `source: "matching-action-evidence"`, the evidence path, kind, and evidence
  timestamp plus the compared binding values.
  Otherwise use the normal acknowledgement question. Its `question` field must
  include the complete just-rendered Manual/Warning row: status, description,
  result, remediation/manual steps, and final acknowledgement prompt. Do not
  rely on the preceding U.0/U.0a assistant message as the only visible copy.
  Never reuse this shortcut
  for an older action, unrelated phase evidence, `Warning`, or mismatched
  status/kind/timestamp. A persisted matching-evidence acknowledgement may be
  reused on resume only while the checkpoint remains `Manual` and the current
  evidence `recordedAt`, kind, required values, and all binding values still
  match; otherwise remove it and ask.
  set `phases.{id}.status = "done"`, `lastVerifiedAt` = now, record each
  checkpoint's status in `checkpointResults`. For each acknowledged
  `Manual`/`Warning` result, also record
  `checkpointAcknowledgements.{checkpointId} = {status, acknowledgedAt}`.
  Remove an old acknowledgement when that checkpoint now returns a different
  status. Add the current phase ID to `verifiedPhases`. Write the state file.
  Return to L.3 to advance to the next phase, passing the updated marker set.
- **Any checkpoint `Failed`/`Error`:** set `phases.{id}.status = "blocked"`,
  record `checkpointResults`. Write the state file.
  Do not add it to `verifiedPhases`; remove this and later phase IDs from both
  invocation-local marker sets.

  If this phase has `actionApplied: true` and `rollbackLabel`, resolve
  `{ROLLBACK_PUSH_GLOB}` from `phases.{id}.rollbackPushGlob` when
  `rollbackPushGlobFromAction: true`; otherwise use the contract's
  `rollbackPushGlob`. Stop with manual attention if the required value is
  missing. Restore and publish the exact pre-action state:

  ```
  python scripts/checkpoint.py --revert-reason "{rollbackLabel}" --only "{ROLLBACK_PUSH_GLOB}"
  python scripts/push.py --only "{ROLLBACK_PUSH_GLOB}" --dry-run
  python scripts/push.py --only "{ROLLBACK_PUSH_GLOB}" --yes
  ```

  If all three commands succeed, set `actionApplied = false`, remove
  `rollbackPushGlob`, keep the phase `in-progress`, record `rolledBackAt` =
  now, and write the state file. This lets a later invocation re-run the gated
  action instead of skipping an action that was undone. If any rollback
  command fails, leave
  `actionApplied = true`, keep the phase `blocked`, and report that both the
  phase and rollback need manual attention.

  **Message:**

  I can't complete this step yet. The recovery handoff above identifies the
  owner, exact location, values, success condition, and the current-step
  recheck. Complete that handoff, then tell me to continue and I'll resume at
  this step.

  **End message.**

  Stop. Do not attempt later phases.

- **Any status not in `completionStatuses`:** keep the phase
  `in-progress`, record the result, show its remediation, and stop. Do not
  add it to `verifiedPhases`; remove this and later phase IDs from both
  invocation-local marker sets. Do not describe the provider as connected.

---

## L.5 — Completion

Once every phase is `done`:

**Message:**

{displayName} is connected to this agent. Every required validation phase in
the provider plan completed.

Validation results: {checkpoint IDs and their actual current status values,
grouped by phase; preserve Manual, Warning, Skipped, and NotConfigured rather
than describing them as Passed}.

**End message.**

Return control to the calling file (it may offer next steps, such as `/create`
for building topics — that offer belongs to the calling file, not here).
