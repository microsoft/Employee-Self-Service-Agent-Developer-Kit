# Master-Checklist Updater (DA)

The single routine every DA Workday setup skill calls to update **its own rows**
in the DA master checklist. Centralizing it means each skill records status the
same way, and the **MANUAL/attestation rule** below is enforced in exactly one
place.

The executable authority for migration, gate transitions, locking, validation,
and persistence is `scripts/workday_da_state.py`. This file defines the user
interaction and evidence inputs supplied to that helper; it never authorizes
direct model edits to either state file.

Forked from the CEA `setup/shared/checklist-updater.md` with DA-scoped state
paths (`.local/connect/workday-da/tasks.md`, `.local/connect/workday-da/config.json`).
The logic is identical — only the persisted files differ — so the two skills can
evolve independently.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not narrate tool calls.

**Inputs from the calling file:**
- `STEP_ID` — the DA master checklist Step ID to update (e.g. `"DA3.1"`,
  `"DA2.4"`). See the canonical rows in the checklist template
  `src/skills/setup/workday-da/tasks.md`. A skill updates **only** the Step IDs
  it owns.
- `NEW_STATE` — `"in-progress"` \| `"done"` \| `"blocked"`.
- `CHECKPOINT_RESULT` — the flightcheck result for the row's checkpoint, one of
  `PASSED` \| `FAILED` \| `ERROR` \| `WARNING` \| `MANUAL` \|
  `NOT_CONFIGURED` \| `SKIPPED` \| `null` (null = not run yet).
- `GATE` — the row's gate type: `"prog"` \| `"manual"` \| `"attest"` \|
  `"advisory"` (from the DA master checklist row; also recorded in config per
  `config-schema.md`).
- `ACK` — *(manual/attest rows only)* `true` once the user has explicitly
  acknowledged the step and any evidence has been captured; otherwise `false`.
- `RESULT_SOURCE` — `"flightcheck"` (default) when `CHECKPOINT_RESULT` came
  from the current FlightCheck results file, or `"external"` when a
  programmatic operation produced its own structured evidence.
- `EXTERNAL_EVIDENCE` — required when `RESULT_SOURCE="external"`; a safe
  summary proving the operation's target, outcome, and verification. Never
  include credentials, tokens, or raw sensitive output.
- `GATE_EVIDENCE` — optional structured evidence returned by
  `permission-gate.md`. Preserve it under the row's `gateEvidence` field; do
  not store the object in scalar `verifiedBy`.
- `ROW_EVIDENCE` — required before a `manual`/`attest` row can complete. It is
  a safe object with `outcome`, `provenance`, `note`, and `capturedAt`;
  `provenance` identifies the source such as `flightcheck`,
  `user-acknowledgement`, or `external-operation`.

**Outputs:**
- The matching checklist item in `.local/connect/workday-da/tasks.md` is updated
  in place (checkbox + hidden `status:` field).
- The mirror record `setupStatus["{STEP_ID}"]` in
  `.local/connect/workday-da/config.json` is updated (see `config-schema.md`).

---

## Files

- **Working copy (read/write):** `.local/connect/workday-da/tasks.md` — the
  rendered, human-readable checklist. Rendered on first run from the template
  `src/skills/setup/workday-da/tasks.md` (the canonical row source). If the
  working copy doesn't exist yet, first migrate the exact legacy
  `.local/setup/workday-da/tasks.md` file when present; otherwise render it from
  the template before updating. Never maintain both paths.
- **Durable mirror:** `setupStatus` in `.local/connect/workday-da/config.json`.
  The tasks file is the view; `setupStatus` is the source of truth a later
  step reads to know what's already done.

Row shape in `tasks.md` (each item in the checklist template
`src/skills/setup/workday-da/tasks.md`): a checkbox line the user sees, followed
by an HTML comment the tooling reads.

```
- [ ] **<short title>** — <plain-language description of what the item achieves>
  <!-- id: <STEP_ID> | role: <role> | skill: <skill> | automatable: <…> | checkpoints: <IDs> | gate: <prog|manual|attest…> | status: <pending|in-progress|done|blocked> -->
```

- `- [ ]` / `- [x]` is the at-a-glance done marker.
- The hidden `id:` field is the `STEP_ID`; the hidden `status:` field carries the
  full four-state value a single checkbox can't express.
- **Never surface a Step ID, checkpoint ID, or the hidden comment to the user** —
  they see the checkbox and its description only.

---

## U.0 — Show the checkpoint result to the user (in chat)

**Timing — render this the instant a checkpoint run returns, and for a
manual/attest row *before* you ask the attestation question.** When a
`python scripts/flightcheck/cli.py --checkpoint <ID>` run just produced
`CHECKPOINT_RESULT`, surface that result to the user — the U.0 table **and** the
U.0a manual steps — before touching any state and before any attestation, so every
checkpoint run has a visible outcome. Single-checkpoint runs never open the HTML
report, so this in-chat render is the only place the user sees the outcome; never
ask a user to attest to manual steps they have not been shown. If you already
rendered this checkpoint's result this pass (per a skill's post-checkpoint display
convention), do not repeat it — proceed to U.1. The U.1–U.3 status update below
runs afterwards (once any attestation is answered) and does **not** re-display the
result.

- Skip this step when `RESULT_SOURCE="external"`; show `EXTERNAL_EVIDENCE`
  using the calling playbook's operation-specific result instead. Also skip
  when `CHECKPOINT_RESULT` is `null` (the checkpoint was not run this pass),
  or when `workspace/flightcheck/results.json` does not exist.

Read `workspace/flightcheck/results.json` — the run that led here wrote it. It has:

```json
{ "results": [ { "checkpoint_id": "...", "description": "...", "status": "..." }, ... ] }
```

If every entry is `Passed`, do not render a result table. Show one concise
sentence that the current action was verified, using the calling playbook's
customer-facing action name. Successful internal checks are evidence, not a
second customer checklist.

When any entry is not `Passed`, render a GitHub-flavoured markdown table in
chat, **one row per entry** in `results`, using `description` verbatim for
**Check** and `status` verbatim for **Status**:

```
| Check | Status |
| --- | --- |
| <description> | <status> |
```

Rules:
- **Never** include `checkpoint_id`, the Step ID, or any other internal
  identifier — there is no ID column; `description` is the only label shown.
- If a `description` or `status` contains a `|`, escape it as `\|`; collapse any
  newline to a single space.
- If `results` is empty, or every result is `Passed`, render **no** table.
- This table is **in addition to** the row's own **Message** blocks and the
  manual verification steps below (see U.0a) — it does not replace or alter them.
- Draw the table yourself in chat. Do not mention `results.json`, file paths, or
  the tools used to produce it.

---

## U.0a — Show the manual verification steps to the user (in chat)

Do this right after the U.0 table, before touching any state. A
`python scripts/flightcheck/cli.py --checkpoint <ID>` run **never opens the HTML
report** — for `MANUAL` checks the verification steps must appear **in chat**, not
in a browser popup. This routine is what puts them there.

- Skip this step when `RESULT_SOURCE="external"`; the calling playbook has
  already shown `EXTERNAL_EVIDENCE`. Also skip when `CHECKPOINT_RESULT` is
  `null`, or when `workspace/flightcheck/results.json` does not exist.

Each entry in `results.json` carries the full text of what the operator must do —
not just `description`/`status` but also the finding and the how-to:

```json
{ "checkpoint_id": "...", "description": "...", "status": "Manual",
  "result": "<the finding / what a human must verify>",
  "remediation": "<the step-by-step verification, may span multiple lines>" }
```

For **every** entry in `results` whose `status` is `Manual` (also `Warning` or
`NotConfigured`, when present), render a block in chat — one per entry, in the
order they appear — using `description` as the heading and separating the
finding from the required action:

```
**<description>**

**What FlightCheck found**

<result>

**What you need to verify**

<remediation>
```

Rules:
- Preserve every word, URL, command, warning, and ordering dependency from
  `result` and `remediation`. Do **not** summarise, shorten, re-order, or
  paraphrase the content.
- Apply presentation-only Markdown formatting so instructions are not rendered
  as dense parallel prose:
  - Preserve existing paragraphs and line breaks.
  - Render lines beginning with `Step <number>` as bold subheadings.
  - Render existing alphabetic or numeric action markers as list items.
  - When a single remediation paragraph contains inline `(1)`, `(2)`, and later
    ordered markers, split only at those markers and render the unchanged text
    as a numbered list.
  - Put standalone commands on their own indented or fenced line. Never alter a
    command while formatting it.
- Keep each action group to at most seven visible items. When more detail
  exists, first show the current action group, wait for its completion, and
  then show the next group; do not omit any instruction.
- Still **never** surface `checkpoint_id`, the Step ID, or the hidden comment.
- Do **not** open, mention, or link `report.html` — the steps live in chat now.
- If no entry has a `Manual`/`Warning`/`NotConfigured` status, render no block.
- Do not mention `results.json`, file paths, or the tools used to produce it.

---

## U.1 — Locate the item

Read `.local/connect/workday-da/tasks.md` (migrate the legacy path or render
from the template first if absent). Find the checklist item whose hidden
comment has `id:` equal to `STEP_ID`.

- If no such item exists, **stop and report** — a skill must not invent items.
  The canonical item set lives in the checklist template
  `src/skills/setup/workday-da/tasks.md`; a missing item means the template is
  out of date, not that the updater should add one.
- If `STEP_ID` is **not** owned by the calling skill, **stop** — skills update
  only their own items.

---

## U.2 — Gather deterministic transition inputs

This is the load-bearing rule. **A `MANUAL` or attestation-gated row is never
auto-completed by a flightcheck pass.** Gather the checkpoint result,
acknowledgement, row evidence, and gate evidence described below. The state
helper applies the table; do not reproduce the transition by editing files.

First apply failure precedence: for every non-advisory row,
`CHECKPOINT_RESULT = FAILED` or `ERROR` always produces `blocked`, regardless
of `ACK`, `NEW_STATE`, or gate evidence. An acknowledgement records that a
person saw or performed a step; it never overrides an objective failure.

Otherwise decide `Status` as follows:

| `GATE` | Condition | Resulting `Status` |
|--------|-----------|--------------------|
| `prog` | `CHECKPOINT_RESULT` = `PASSED` | `done` |
| `prog` | `CHECKPOINT_RESULT` = `WARNING` / `NOT_CONFIGURED` / `SKIPPED` / `MANUAL` / `null` | `in-progress` |
| `manual` / `attest` | `ACK` = `true`, `ROW_EVIDENCE` is complete, and result is not `FAILED`/`ERROR` | `done` |
| `manual` / `attest` | `ACK` = `false` or `ROW_EVIDENCE` is missing | `in-progress` |
| `advisory` | the advisory step has been run and its report shown (or attempted and skipped) | `done` |

Notes:
- An `advisory` row is not backed by a flightcheck checkpoint (`CHECKPOINT_RESULT`
  is `null`). It **never blocks** — it completes to `done` once its advisory
  output has been presented to the user, regardless of what the output found. If
  the advisory step can't run, note it and still complete the row (advisory rows
  never hold up the setup).
- A `CHECKPOINT_RESULT` of `MANUAL` means "the checkpoint reported what it could,
  but completion needs a human." It **never** maps to `done` on its own — it
  requires `ACK = true`.
- For `prog` rows, `NEW_STATE` from the caller must be consistent with
  `CHECKPOINT_RESULT`; if they conflict, the checkpoint result wins (it's the
  objective signal).
- For a `prog` row with `RESULT_SOURCE="external"`, `PASSED` is valid only when
  non-empty `EXTERNAL_EVIDENCE` is supplied. Otherwise treat the result as
  `null` and leave the row `in-progress`.

If the row is `manual`/`attest` and `ACK` is `false`, before leaving the row
`in-progress` confirm the user actually saw the manual step. (Precondition: the
manual verification steps — U.0a — for this row's checkpoint must already have been
rendered in chat. If they were not, show them now, then ask.)

Use the visible checklist title found in U.1. The confirmation must name that
specific action; never ask the generic question "Have you completed this step?"
and never preselect or recommend a successful answer.

```json
[
  {
    "header": "Confirm {VISIBLE_TITLE}",
    "question": "Did you complete and verify “{VISIBLE_TITLE}” using the requirements shown above?",
    "options": [
      { "label": "Completed and verified" },
      { "label": "Not yet or unsure" }
    ],
    "allowFreeformInput": false
  }
]
```

Only treat the row as acknowledged (`ACK = true`) on an explicit **Completed
and verified** answer after row-specific evidence has been captured. Never
infer acknowledgement from a FlightCheck pass, a bare `done`, or an answer to
a different row.

---

## U.3 — Persist through the state helper

**Persist immediately — never batch.** Invoke the deterministic helper now,
before returning to the caller or proceeding to another row:

```powershell
python scripts/workday_da_state.py --root . update-row `
  --step-id "<STEP_ID>" `
  --checkpoint-result "<CHECKPOINT_RESULT>" `
  --result-source "<flightcheck|external|user-acknowledgement|advisory>" `
  [--ack] `
  [--evidence-json '<ROW_EVIDENCE JSON>'] `
  [--gate-evidence-json '<GATE_EVIDENCE JSON>']
```

Omit `--checkpoint-result` only when the row has no checkpoint result. Include
`--ack` only after the explicit acknowledgement in U.2. Pass safe structured
evidence exactly as gathered; never include credentials, tokens, or raw
Workday employee data.

The helper validates the row against `workday-da.definition.json`, enforces the
gate table, serializes concurrent writers, atomically commits authoritative
`config.json`, derives the checklist view, preserves unrelated fields, and
regresses dependent completion when a previously completed prerequisite no
longer passes. Completed programmatic, attested, and advisory rows are recorded
as `programmatic`, `attested`, and `reviewed`, respectively. If it reports that
config was saved but the checklist could not be refreshed, run:

```powershell
python scripts/workday_da_state.py --root . reconcile
```

Return control to the calling file. Do not announce file paths or internal
mechanics to the user.
