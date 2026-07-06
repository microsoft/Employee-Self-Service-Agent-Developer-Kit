# Master-Checklist Updater (Shared)

The single routine every Workday setup skill calls to update **its own rows** in
the master checklist. Centralizing it means each skill records status the same
way, and the **MANUAL/attestation rule** below is enforced in exactly one place.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not narrate tool calls.

**Inputs from the calling file:**
- `STEP_ID` — the master setup checklist Step ID to update (e.g. `"S3.1"`, `"S4.2"`).
  See the canonical rows in the checklist template
  `src/skills/setup/workday/tasks.md`. A skill updates **only** the
  Step IDs it owns.
- `NEW_STATE` — `"in-progress"` \| `"done"` \| `"blocked"`.
- `CHECKPOINT_RESULT` — the flightcheck result for the row's checkpoint, one of
  `PASSED` \| `FAILED` \| `WARNING` \| `MANUAL` \| `null` (null = not run yet).
- `GATE` — the row's gate type: `"prog"` \| `"manual"` \| `"attest"` (from the
  master setup checklist row; also recorded in config per `config-schema.md`).
- `ACK` — *(manual/attest rows only)* `true` once the user has explicitly
  acknowledged the step and any evidence has been captured; otherwise `false`.

**Outputs:**
- The matching checklist item in `.local/setup/workday/tasks.md` is updated in
  place (checkbox + hidden `status:` field).
- The mirror record `setupStatus["{STEP_ID}"]` in
  `.local/connect/workday/config.json` is updated (see `config-schema.md`).

---

## Files

- **Working copy (read/write):** `.local/setup/workday/tasks.md` — the rendered,
  human-readable checklist. Rendered on first run from the template
  `src/skills/setup/workday/tasks.md` (the canonical row source). If the
  working copy doesn't exist yet, render it from the template before updating.
- **Durable mirror:** `setupStatus` in `.local/connect/workday/config.json`. The
  tasks file is the view; `setupStatus` is the source of truth a later skill
  reads to know what's already done.

Row shape in `tasks.md` (each item in the checklist template
`src/skills/setup/workday/tasks.md`): a checkbox line the user sees, followed by an
HTML comment the tooling reads.

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

## U.1 — Locate the item

Read `.local/setup/workday/tasks.md` (render from the template first if absent).
Find the checklist item whose hidden comment has `id:` equal to `STEP_ID`.

- If no such item exists, **stop and report** — a skill must not invent items. The
  canonical item set lives in the checklist template
  `src/skills/setup/workday/tasks.md`; a missing item means the
  template is out of date, not that the updater should add one.
- If `STEP_ID` is **not** owned by the calling skill, **stop** — skills update
  only their own items.

---

## U.2 — Determine the new Status (the MANUAL/attestation rule)

This is the load-bearing rule. **A `MANUAL` or attestation-gated row is never
auto-completed by a flightcheck pass.**

Decide `Status` as follows:

| `GATE` | Condition | Resulting `Status` |
|--------|-----------|--------------------|
| `prog` | `CHECKPOINT_RESULT` = `PASSED` | `done` |
| `prog` | `CHECKPOINT_RESULT` = `FAILED` | `blocked` |
| `prog` | `CHECKPOINT_RESULT` = `WARNING` / `null` | `in-progress` |
| `manual` / `attest` | `ACK` = `true` (user acknowledged **and** evidence captured) | `done` |
| `manual` / `attest` | `ACK` = `false`, regardless of `CHECKPOINT_RESULT` | `in-progress` (or `blocked` if `FAILED`) |

Notes:
- A `CHECKPOINT_RESULT` of `MANUAL` means "the checkpoint reported what it could,
  but completion needs a human." It **never** maps to `done` on its own — it
  requires `ACK = true`.
- For `prog` rows, `NEW_STATE` from the caller must be consistent with
  `CHECKPOINT_RESULT`; if they conflict, the checkpoint result wins (it's the
  objective signal).

If the row is `manual`/`attest` and `ACK` is `false`, before leaving the row
`in-progress` confirm the user actually saw the manual step:

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

1. Update the located item in `.local/setup/workday/tasks.md` to the state from
   U.2:
   - Set the checkbox marker: `- [x]` when the resulting status is `done`,
     otherwise `- [ ]`.
   - Set the hidden `status:` field in that item's comment to the full value
     (`pending` / `in-progress` / `done` / `blocked`).

   Leave the visible title/description and every other item untouched. Do not add
   any Step ID, checkpoint ID, or status text to the visible line — the checkbox is
   the only at-a-glance marker the user sees.
2. Update the mirror in `.local/connect/workday/config.json`:
   ```json
   {
     "setupStatus": {
       "{STEP_ID}": {
         "state": "<resulting status>",
         "checkpoint": "<the item's checkpoint ID>",
         "gate": "<prog|manual|attest>",
         "verifiedBy": "<programmatic|attested|null>"
       }
     }
   }
   ```
   Merge — do not drop other `setupStatus` keys (round-trip contract in
   `config-schema.md`).

Return control to the calling file. Do not announce file paths or internal
mechanics to the user.
