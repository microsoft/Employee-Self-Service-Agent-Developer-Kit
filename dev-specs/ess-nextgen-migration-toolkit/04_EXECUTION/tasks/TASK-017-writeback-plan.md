# TASK-017 — Writeback Plan (coalescing + meaningful-change guard)

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-017                  |
| Workstream | 0 — Repository Foundation |
| Status     | DONE                      |
| Consumes   | TASK-002                  |

## Description

Provide the shared **writeback accumulator** that every Transformation step (the
DA-compat step and all Migration Rules) stages its edits on, instead of appending
directly to a flat `pending_writes` list. It solves two problems that a flat list
cannot:

1. **Coalescing** — one step may target one *or more* records, and multiple steps
   (or multiple rules editing the **same field of the same record**, e.g. a
   topic's `data` YAML) must produce **one** PATCH per record, not several that
   clobber each other.
2. **Meaningful-change guard** — writeback must only fire when a field genuinely
   changes. A PATCH equal to the current value stamps a needless unmanaged
   (`Active`) overlay over a clean managed base. The plan therefore diffs the
   staged value against the original baseline and emits nothing when unchanged.

## Design

`WritebackPlan` keyed by `(entity_set, record_id)`; each `WritebackTarget` holds
the `original` baseline field values and a mutable `working` copy:

- `plan.target(entity_set, record_id, original={...})` — returns (creating on
  first touch) the record's target; the **first** baseline seen for a field wins.
- `target.get(field)` — the working value if staged, else the original (so a later
  rule reads an earlier rule's output → **chaining**).
- `target.set(field, value)` — stage a working value (unconditionally; the diff
  guards no-ops).
- `plan.pending_writes()` — derive `{"entity_set", "record_id", "changes"}`, one
  entry per record, `changes` containing **only** fields whose working value
  differs from the original; unchanged records are omitted.
- `plan.target_for(entity_set, record_id)` / `plan.targets()` — read-only lookups
  so reporting can compare a record's `original` (actual copy) against its
  `working` (final modified copy) after all steps, without a second stored copy.

`MigrationContext.writeback` is the plan; `MigrationContext.pending_writes` is a
read-only property deriving from it, so the Output stage (TASK-007) consumes the
same coalesced, no-op-guarded shape it always did.

### Architecture constraints

- Pure domain model — no Dataverse I/O, no logging, no pipeline coupling.
- Transformation steps **never** append to `pending_writes` directly; they stage
  via `context.writeback`.
- Structured fields (JSON `configuration`, YAML `data`): transforms must return
  their input unchanged on a no-op so the string diff does not false-positive.

## Acceptance Criteria

- [x] `WritebackPlan` / `WritebackTarget` under
  `src/modules/transformation/models/` and exported from the models package.
- [x] Coalescing: multiple `target()` calls for one record merge into a single
  `pending_writes` entry.
- [x] Chaining: `target.get()` returns the working value so sequential rules
  compose on the same field.
- [x] No-op guard: staging a value equal to the original produces no write;
  `changes` includes only genuinely-changed fields.
- [x] First-touch baseline wins (a later `target(..., original=...)` cannot
  clobber the diff baseline).
- [x] `target_for()` / `targets()` read-only accessors expose each record's
  actual (`original`) vs final (`working`) copy for reporting, without a second
  stored copy.
- [x] `MigrationContext.pending_writes` is derived from `context.writeback`.
- [x] `ApplyDaCompatibilityStep` (TASK-016) stages via the plan.
- [x] Quality gates pass (`ruff`, `mypy`, `pytest`; enforced in CI).

## Deliverables

- `src/modules/transformation/models/writeback_plan.py` — `WritebackPlan`,
  `WritebackTarget`
- `MigrationContext.writeback` + derived `pending_writes` property
- `ApplyDaCompatibilityStep` refactored to stage via the plan
- `tests/unit/modules/transformation/test_writeback_plan.py`

## Notes / Future

- **Overlay removal (not in scope).** If a transformed topic overlay becomes
  identical to the managed base, the ideal is to *delete* the unmanaged overlay
  (revert to base) rather than write a base-equal overlay. Today the guard only
  suppresses writes equal to the current overlay; base-equality removal is a
  future enhancement.

## References

- 02_ARCHITECTURE/PIPELINES.md — Transformation stage, writeback-plan contract
- 02_ARCHITECTURE/CUSTOMIZATION_DISCOVERY.md — §6 DA-compat, §7 writeback targeting
- 03_ENGINEERING/CODING_STANDARDS.md
- 03_ENGINEERING/TESTING.md
