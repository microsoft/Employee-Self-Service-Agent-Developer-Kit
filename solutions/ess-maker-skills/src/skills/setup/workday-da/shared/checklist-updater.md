# Master-Checklist Updater (DA)

The single routine every DA Workday setup skill calls to update **its own rows**
in the DA master checklist. Centralizing it means each skill records status the
same way, and the **MANUAL/attestation rule** below is enforced in exactly one
place.

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

Render a GitHub-flavoured markdown table in chat, **one row per entry** in
`results`, using `description` verbatim for **Check** and `status` verbatim for
**Status**:

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
- If `results` is empty, render **no** table.
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
order they appear — using `description` as the heading, then `result`, then
`remediation`:

```
**<description>**

<result>

<remediation>
```

Rules:
- Copy `result` and `remediation` **verbatim** — keep the numbered/bulleted steps
  and every line break. Do **not** summarise, shorten, re-order, or paraphrase the
  steps; the operator follows them exactly.
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

## U.2 — Determine the new Status (the MANUAL/attestation rule)

This is the load-bearing rule. **A `MANUAL` or attestation-gated row is never
auto-completed by a flightcheck pass.**

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

```json
[
  {
    "header": "Confirm step",
    "question": "Have you completed this step and is the evidence captured?",
    "options": [
      { "label": "Yes, it's done", "recommended": true },
      { "label": "Not yet" }
    ],
    "allowFreeformInput": false
  }
]
```

Only treat the row as acknowledged (`ACK = true`) on an explicit "Yes, it's
done". Never infer acknowledgement from a flightcheck pass.

---

## U.3 — Write the item + mirror

**Persist immediately — never batch.** Write **both** files below **now**, as part
of this call, before returning control to the caller and before the caller proceeds
to its next row. A completed row must be durable the instant its checkpoint passes,
so that if a later row in the same skill errors, the progress already made is not
lost — the orchestrator resumes from the first non-`done` row in `setupStatus`.

1. Update the located item in `.local/connect/workday-da/tasks.md` to the state
   from U.2:
   - Set the checkbox marker: `- [x]` when the resulting status is `done`,
     otherwise `- [ ]`.
   - Set the hidden `status:` field in that item's comment to the full value
     (`pending` / `in-progress` / `done` / `blocked`).

   Leave the visible title/description and every other item untouched. Do not add
   any Step ID, checkpoint ID, or status text to the visible line — the checkbox is
   the only at-a-glance marker the user sees.
2. Update the mirror in `.local/connect/workday-da/config.json`:
   ```json
   {
     "setupStatus": {
       "{STEP_ID}": {
         "state": "<resulting status>",
         "checkpoint": "<the item's checkpoint ID>",
         "gate": "<prog|manual|attest|advisory>",
         "verifiedBy": "<programmatic|attested|reviewed|null>",
         "evidence": {
           "outcome": "<checkpoint status or operation outcome>",
           "provenance": "<flightcheck|user-acknowledgement|external-operation|advisory>",
           "note": "<safe evidence summary>",
           "capturedAt": "<UTC timestamp>"
         },
         "gateEvidence": {
           "method": "<programmatic|attested>",
           "outcome": "<pass|stop>",
           "provenance": "<role-query|user-attestation>",
           "note": "<safe role evidence summary>",
           "capturedAt": "<UTC timestamp>"
         }
       }
     }
   }
   ```
   Set scalar `verifiedBy` from the resulting completed state:
   - `programmatic` for a completed `prog` row,
   - `attested` for a completed `manual`/`attest` row,
   - `reviewed` for a completed `advisory` row,
   - `null` for any row that is not `done`.

   Persist `ROW_EVIDENCE` as `evidence` and `GATE_EVIDENCE` as
   `gateEvidence` when supplied. Merge these fields with the existing row;
   never replace `verifiedBy` with an object. When a row regresses to
   `in-progress` or `blocked`, clear stale completion `verifiedBy` and
   `evidence`, while retaining current failure evidence and any still-valid
   `gateEvidence`.
   Merge — do not drop other `setupStatus` keys (round-trip contract in
   `config-schema.md`).

Return control to the calling file. Do not announce file paths or internal
mechanics to the user.
