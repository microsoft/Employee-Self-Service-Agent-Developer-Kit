# Connect Lifecycle Runner (Shared)

The single, provider-agnostic routine that drives **any** integration's
connect lifecycle from its contract file. A provider (Workday, ServiceNow, any
future ISV) supplies a contract (`lifecycle-contract-schema.md`) plus its own
action fragments for mutating phases; this file contains zero
integration-specific logic. Adding a new provider never requires changing this
file when its needs fit the documented contract; shared backward-compatible
contract evolution belongs here rather than in provider-specific branches.

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling
or what files you are reading. Never surface a checkpoint ID, phase ID, file
path, or the word "checkpoint"/"contract"/"state file" to the user.

**Inputs from the calling file:**
- `PROVIDER` — the provider key (e.g. `"workday"`), matching a contract at
  `src/skills/connect/{PROVIDER}/contract.json`.
- `AGENT_SLUG` — the active agent's slug from `.local/config.json`
  (`activeAgent`, falling back to `agent.slug`).

**Files:**
- **Contract (read-only):** `src/skills/connect/{PROVIDER}/contract.json`
- **State (read/write):**
  `.local/connect/{PROVIDER}/agents/{AGENT_SLUG}/lifecycle.json` — shape
  defined in `lifecycle-contract-schema.md`.

---

## L.0 — Load the contract and state

Read `src/skills/connect/{PROVIDER}/contract.json`. If it does not exist,
**stop and report** — the calling file named a provider with no contract.

If the contract has `connectConfig` and that file exists, add
`--connect-config "{connectConfig}"` to every FlightCheck command in this
runner. If it does not exist, omit the argument; do not substitute another
provider or architecture's state.

If `AGENT_SLUG` is empty, stop and ask the user to run `/setup`; agent-specific
mutation and validation must never fall back to scanning every local agent.

Read `.local/connect/{PROVIDER}/agents/{AGENT_SLUG}/lifecycle.json`. If it
does not exist, this is a first run: initialize it in memory with
`provider: PROVIDER`, `agentSlug: AGENT_SLUG`, `attested: false`,
`roleAttestations: {}`, and every phase from the contract at
`status: "pending"`, `checkpointResults: {}` — do not write it to disk yet
(write only after the plan is shown, in L.1).

If existing state identifies a different provider or agent slug, stop instead
of reusing it. Never copy plan or role attestation across provider/agent
identity.

For backward compatibility, treat a missing `roleAttestations` object in an
older state file as `{}`. Do not infer an attestation from `attested`,
`attestedAt`, a completed phase, or a prior action.

Initialize an invocation-local empty set named `executedActionPhases`. Add a
phase ID after its action returns `applied` or `recorded`; this prevents an
`every-invocation` action from running twice during L.2 and L.4 of the same
invocation.

---

## L.1 — Show the plan and get attestation (first run only)

Skip this section entirely if the state file already has `attested: true`.

Build the plan from the contract, in phase order:
- One line per phase using its `label` verbatim.
- Collect the **union** of `requiredRole` across every `mutates: true` phase,
  de-duplicated, in the order phases appear.

**Message:**

Here's what I'll do to connect this agent to {displayName}:

{numbered list of phase labels, in contract order}

This needs someone with the following access: {comma-separated required
roles, or omit this sentence entirely if no phase mutates}.

I'll check as I go and stop to tell you if something needs attention. Ready
to start?

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Start connection",
    "question": "Ready to start?",
    "options": [
      { "label": "Yes, let's go", "recommended": true },
      { "label": "Not now" }
    ],
    "allowFreeformInput": false
  }
]
```

**If "Not now":** Stop here. Do not write the state file — the next
invocation should show this same plan again.

**If "Yes, let's go":** Write
`.local/connect/{PROVIDER}/agents/{AGENT_SLUG}/lifecycle.json` now with
`provider: PROVIDER`, `agentSlug: AGENT_SLUG`, `attested: true`,
`attestedAt` = current UTC timestamp, `roleAttestations: {}`, and every phase
at `status: "pending"`. Continue to L.2. Accepting the plan does not claim a
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
   status, update `lastVerifiedAt` and leave the phase `done`. Do **not**
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

   - For `Failed`/`Error`, set the phase to `blocked`, persist the current
     checkpoint results, render the result without executing L.4b rollback,
     and stop for remediation.
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

Walk the phases in contract order. The **current phase** is the first one
whose `status` is not `done`.

- If every phase is `done`: go to L.5 (completion).
- Otherwise: set `currentPhase` to that phase's `id` and continue to L.4.

---

## L.4 — Run the current phase

### L.4a — Run the provider action

If the current phase has an `actionDoc`, execute it when:

- `actionExecution` is `"every-invocation"` and this phase's action has not
  run during this invocation; or
- `actionExecution` is omitted/`"once"` and `actionApplied` is not yet `true`.

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
- **`"cancelled"`** — the user declined before mutation. Keep
  `actionApplied = false`, remove `lastActionAt` and `rollbackPushGlob`, leave
  the phase `in-progress`, write the state file, and stop. Do not run the phase
  checkpoints.

Any missing, unknown, or failure result is not success: keep
`actionApplied = false`, remove `lastActionAt` and `rollbackPushGlob`, report
the action failure, write the state file, and stop.

### L.4b — Run the phase's checkpoints

For each checkpoint ID the current phase lists, run:

```
python scripts/flightcheck/cli.py --checkpoint {ID}
```

If the contract has `connectConfig` and that file exists, add
`--connect-config "{connectConfig}"`. For agent-local checkpoints, also add
`--agent-slug "{AGENT_SLUG}"`. Use the same arguments when re-verifying
completed phases in L.2.

After each run, render the result using the exact U.0 and U.0a routines from
`src/skills/setup/shared/checklist-updater.md` (read that file's U.0/U.0a
sections and apply them verbatim against `workspace/flightcheck/results.json`
— do not re-implement or paraphrase that rendering logic here).

Aggregate the phase's outcome using the phase's `completionStatuses`
(default `["Passed"]`) and the status rules in
`lifecycle-contract-schema.md`:

- **All checkpoints "count toward done"** (after any needed attestation for
  `Manual`/`Warning` results — ask the same style of yes/no confirmation
  `checklist-updater.md`'s U.2 uses when a result needs acknowledgement):
  set `phases.{id}.status = "done"`, `lastVerifiedAt` = now, record each
  checkpoint's status in `checkpointResults`. For each acknowledged
  `Manual`/`Warning` result, also record
  `checkpointAcknowledgements.{checkpointId} = {status, acknowledgedAt}`.
  Remove an old acknowledgement when that checkpoint now returns a different
  status. Write the state file. Return to L.3 to advance to the next phase.
- **Any checkpoint `Failed`/`Error`:** set `phases.{id}.status = "blocked"`,
  record `checkpointResults`. Write the state file.

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

  I can't complete this step yet — {plain-language summary of what's
  blocking it, drawn from the remediation text already shown above}. Fix
  that, then tell me to continue and I'll pick up right here.

  **End message.**

  Stop. Do not attempt later phases.

- **Any status not in `completionStatuses`:** keep the phase
  `in-progress`, record the result, show its remediation, and stop. Do not
  describe the provider as connected.

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
