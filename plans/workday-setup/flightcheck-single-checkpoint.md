# Plan: Flightcheck single-checkpoint invocation

**Standalone, integration-agnostic.** No Workday dependency — this benefits every
integration and can ship on its own. Part of the [Workday Setup](./README.md)
initiative because every setup skill relies on it for atomic verification.

## Problem

Flightcheck today runs only by **broad scope** (`full`, `workday`, `authentication`,
`environment`, …) via `scripts/flightcheck/cli.py`. The kit needs to "validate atomic
pieces of the setup" — verify exactly one checkpoint at a time, right after the step that
produces it.

Two real constraints make naive isolation infeasible (verified in the code):
- **Checks are registered per *category function*, not per checkpoint.** A single function in
  `runner.py` emits many `CheckResult`s, and several share state across checkpoints
  (e.g. `WD-PKG-001` caches `_workday_package_flavor` / `_workday_connection_refs` consumed by
  later Workday checks; `external_systems.py` sets `_workday_flows`). You cannot "run only the
  check that produces `WD-CONN-012`" without first running its in-category prerequisites.
- **`cli.py` requires `.local/config.json` + a Dataverse endpoint before any check runs.** An
  Entra-only or Workday-manual checkpoint would fail at startup even though it needs no
  Dataverse.

## Goal

Let any single checkpoint be executed and reported on its own, so each setup skill can
verify just its own atomic outcome.

## Changes

### New: checkpoint registry *(the load-bearing piece)*
- Introduce a **static registry** mapping each **checkpoint ID → owning category function →
  required clients (`graph` / `dataverse` / `pp_admin` / `pva` / none) → required config →
  prerequisite checkpoint IDs**.
- It is the single source of truth for `--list-checkpoints` (read statically, no broad run)
  and for resolving exactly what a single `--checkpoint` needs to initialize and hydrate.

### `scripts/flightcheck/cli.py`
- Add `--checkpoint <ID>` — run exactly one checkpoint by ID and report only its result.
- Add `--list-checkpoints` — print all known checkpoint IDs (+ category, priority, roles)
  from the registry so skills/users can discover valid IDs (no broad run required).
- **Initialize only the clients/config the target checkpoint declares.** An Entra-only
  checkpoint must run with **no Dataverse endpoint configured** — relax the global
  `.local/config.json` / `dataverseEndpoint` precondition to a **per-checkpoint** requirement
  driven by the registry.
- `--checkpoint` is mutually exclusive with `--scope`; unknown/invalid ID → clear error
  listing valid IDs.
- Keep all existing scopes and behavior unchanged (additive only).

### `scripts/flightcheck/runner.py`
- Resolve the target via the registry, **run its prerequisite checkpoints first to hydrate
  shared state** (the bootstrap chain), then the owning function, then **filter the emitted
  results down to the target ID**. (Granular per-check execution is *not* required —
  hydrate-then-filter is the contract.)
- Preserve the existing `CheckResult` shape and `MANUAL` status semantics (a manual checkpoint
  reports what it can and does **not** fail readiness). A `MANUAL` result is **not** row
  completion — acknowledgement is handled by the checklist (see
  [`master-checklist.md`](./master-checklist.md)).
- Ensure single-checkpoint mode returns the same structured result/remediation/doc-link as
  full-scope mode.

### `src/reference/ess-docs/flightcheck/validation-matrix.md`
- Document the new `--checkpoint` / `--list-checkpoints` usage.
- (Workday-specific checkpoint IDs are added by [`master-checklist.md`](./master-checklist.md)
  and the per-skill plans, not here.)

## Acceptance criteria

- `flightcheck --list-checkpoints` lists every checkpoint ID from the registry (no broad run).
- `flightcheck --checkpoint <ID>` hydrates declared prerequisites, runs only the target, and
  prints a single structured result — **without** requiring clients the checkpoint doesn't
  need (e.g. an Entra-only ID runs with no Dataverse endpoint configured).
- Unknown ID → clear error naming valid IDs; non-zero exit.
- Existing `--scope` runs are unchanged in behavior.
- A `MANUAL` checkpoint run in isolation reports `MANUAL` and exits success (doesn't fail readiness).

## Out of scope

- New scopes or new Workday checkpoints (those live in other plans).
- Any change to how checkpoints are *defined* beyond the registry + single-ID selection.
- Refactoring every check into an independently-registered unit (the registry's
  hydrate-then-filter model deliberately avoids that larger rewrite).
