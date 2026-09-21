# Connect Lifecycle Runner (Shared)

The single, provider-agnostic routine that drives **any** integration's
connect lifecycle from its contract file. A provider (Workday, ServiceNow, any
future ISV) supplies a contract (`lifecycle-contract-schema.md`) plus its own
action fragments for mutating phases; this file contains zero
integration-specific logic. Adding a new provider never requires changing this
file — only authoring a new contract + action fragments.

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
`agentSlug: AGENT_SLUG`, `attested: false`, and every phase from the contract
at `status: "pending"`, `checkpointResults: {}` — do not write it to disk yet
(write only after the plan is shown, in L.1).

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
`agentSlug: AGENT_SLUG`, `attested: true`, `attestedAt` = current UTC
timestamp, and every phase at `status: "pending"`. Continue to L.2.

---

## L.2 — Live re-verification on resume

**This is the load-bearing rule of this file.** A phase recorded `status:
"done"` in the state file from an earlier turn is a *cache*, not a fact. Never
report a phase complete, and never skip straight past it, without a live
checkpoint run from **this** invocation confirming it still holds. Environments
drift — a connection can be removed, a topic redirect can be reverted outside
this tool — and trusting a stale checkbox has already caused a real bug in
this family of skills once; do not reintroduce it.

For every phase the state file marks `done`, in contract order, before doing
anything else:

1. Re-run every checkpoint the phase lists (see L.4's checkpoint-running
   steps — reuse that exact mechanism here, silently, without re-showing the
   up-front plan).
2. If every checkpoint still resolves to a status allowed by that phase's
   `completionStatuses`, and every `Manual`/`Warning` result has a matching
   persisted `checkpointAcknowledgements` entry for that checkpoint and
   status, update `lastVerifiedAt` and leave the phase `done`. Do **not**
   re-render the U.0 table for a phase that was already `done` and stays
   `done` on resume — only surface output for phases that change state or that
   are not yet done.
3. If any checkpoint resolves to a status **outside** that phase's
   `completionStatuses`, **or** an allowed `Manual`/`Warning` result lacks a
   persisted acknowledgement matching the checkpoint and current status, the
   cached completion has regressed. This includes `Warning`, `Skipped`,
   `NotConfigured`, and unacknowledged `Manual`/`Warning` results — not only
   `Failed`/`Error`. Set the phase to `blocked` for `Failed`/`Error`, otherwise
   set it to `in-progress`, and set **every phase after it** back to `pending`
   (later phases may have depended on this one still holding). Persist the
   current checkpoint results, render the result using L.4b, and stop. Do not
   re-run L.4a's mutating action merely because a live re-check regressed;
   mutation requires a fresh gate and rollback checkpoint.

Once every previously-`done` phase is confirmed (or the loop stopped early on
a regression), continue to L.3.

---

## L.3 — Find the current phase

Walk the phases in contract order. The **current phase** is the first one
whose `status` is not `done`.

- If every phase is `done`: go to L.5 (completion).
- Otherwise: set `currentPhase` to that phase's `id` and continue to L.4.

---

## L.4 — Run the current phase

### L.4a — Mutating phases: gate, then act

If the current phase has `mutates: true` and `actionApplied` is not yet
`true` in its state entry:

Apply `permission-gate.md` (from `src/skills/setup/shared/permission-gate.md`)
with `REQUIRED_ROLE` = the phase's `requiredRole`. Use the phase's `gateMode`
(default `"attested"` if the contract omits it); if `gateMode` is
`"programmatic"`, pass the phase's `roleQuery` as `ROLE_QUERY` verbatim, and
treat the query as a pass only if it returns one of `roleQueryPassNames` — the
runner never invents its own role query or pass condition.

**If the gate returns `"stop"`:** stop here. Leave the phase `in-progress` in
the state file (write it now) so the next invocation resumes at this same
gate rather than re-showing the whole plan.

**If the gate returns `"pass"`:** if the phase names a `rollbackLabel`, save a
checkpoint first:

```
python scripts/checkpoint.py "{rollbackLabel}"
```

Then read the phase's `actionDoc` file and follow it completely — it contains
its own Message blocks and tool calls. When it finishes, set
`phases.{id}.actionApplied = true` and write the state file immediately.

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

  If this phase has `actionApplied: true`, `rollbackLabel`, and
  `rollbackPushGlob`, restore and publish the exact pre-action state:

  ```
  python scripts/checkpoint.py --revert-reason "{rollbackLabel}" --only "{rollbackPushGlob}"
  python scripts/push.py --only "{rollbackPushGlob}" --dry-run
  python scripts/push.py --only "{rollbackPushGlob}" --yes
  ```

  If all three commands succeed, set `actionApplied = false`, keep the phase
  `in-progress`, record `rolledBackAt` = now, and write the state file. This
  lets a later invocation re-run the gated action instead of skipping an
  action that was undone. If any rollback command fails, leave
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
the provider plan passed.

**End message.**

Return control to the calling file (it may offer next steps, such as `/create`
for building topics — that offer belongs to the calling file, not here).
