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
- **Checks are registered per *category function*, not per checkpoint.** A single category
  function (defined in `checks/*.py` — e.g. `checks/workday.py`'s `run_workday_checks`, and
  registered into the runner by `cli.py`) emits many `CheckResult`s, and several share state across checkpoints
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
- Introduce a **static registry** — new module **`scripts/flightcheck/registry.py`** — mapping
  each **checkpoint ID → owning category function → required clients (`graph` / `dataverse` /
  `pp_admin` / `pva` / none) → required config → prerequisite checkpoint IDs**.
- It is the single source of truth for `--list-checkpoints` (read statically, no broad run)
  and for resolving exactly what a single `--checkpoint` needs to initialize and hydrate.
- **Scope: the ESS + Workday *setup* checkpoints, not the entire flightcheck surface.** The
  registry owns exactly the checkpoint IDs the setup skills emit or reuse (the
  [`master-checklist`](./master-checklist.md) registry/mint table) plus the dynamic families those
  setup-relevant category functions emit on a simplified full run. Other integrations — ServiceNow
  `SN-*`, graph-connector `EXT-*`, `SAP-*`, and the pre-existing `ENV-003`/`ENV-004` (+
  `ENV-004-OR/UR/UC` detail) environment rows — remain validated by the existing `--scope` runs and
  are **out of registry scope**; this feature exists to validate atomic pieces of the *setup*.
- **Support family/prefix entries for dynamically-numbered IDs.** Some checkpoints are emitted
  with data-driven numeric suffixes. Within setup scope the dynamic families are: `WD-FLOW-{n}`
  (`checks/workday.py`'s `_check_flow_status`, one per discovered flow); `WD-CONN-{n}` (the generic
  connection enumerator `check_connector_connections(checkpoint_prefix="WD-CONN", …)` in
  `checks/connections.py` emits `WD-CONN-001` summary + `WD-CONN-{i+2:03d}` per discovered Workday
  connection); `WD-WF-{n}` (per workflow — emitted but skipped on the simplified flavor, registered
  for completeness); the legacy `WD-ENV-*` (banned for simplified, registered so the family
  resolves); and the per-topic `TOPIC-TRIGGER-{n}` / `TOPIC-INTEGRATION-{n}` (skill-6). The registry
  **cannot enumerate these exact IDs ahead of time**, so it registers each as a **family/prefix**
  (e.g. `WD-FLOW-*`, `WD-CONN-*`) keyed to the owning function + clients/config/prereqs. Resolution
  rules: `--checkpoint WD-FLOW-*` runs the whole family; an exact dynamic ID
  (`--checkpoint WD-FLOW-002`) resolves to its family entry by **longest-prefix match**, runs the
  family, then filters to that one emitted ID. **Exact entries resolve first**, so the reused fixed
  IDs `WD-CONN-010` / `WD-CONN-012` / `WD-CONN-102` and the new `WD-CONN-AUTH-001` stay exact-match
  entries while `WD-CONN-*` absorbs the dynamic per-connection (and any other pre-existing
  `WD-CONN-NNN`) detail rows — the two coexist cleanly. (A pre-existing source quirk: the
  zero-padded enumerator could emit `WD-CONN-010`/`WD-CONN-012` if a tenant ever had ≥9/≥11 Workday
  connections, colliding with the fixed literals — exact-first still resolves correctly, the
  simplified path fingerprints a single `ff0df` reference so `n` stays tiny in practice, and fixing
  the enumerator's numbering is out of scope for this plan.)
- **Resolve prerequisites transitively.** A target's required clients/config is the **union of
  its own declared needs and those of every prerequisite in its transitive closure** — a
  checkpoint that declares no Dataverse can still have a Dataverse-backed prerequisite, so naive
  one-level resolution would under-initialize and crash. Walk the full prereq chain.
- **Validate the graph at load.** On startup (and in a unit test) assert the prereq graph is
  **acyclic** (a cycle = a bootstrap deadlock) and that **every referenced prerequisite ID (or
  family)** exists in the registry. Fail fast with a precise message if not.

### `scripts/flightcheck/cli.py`
- Add `--checkpoint <ID>` — run exactly one checkpoint by ID and report only its result.
- Add `--list-checkpoints` — print all **registered setup** checkpoint IDs **and families** (+ category,
  priority, roles) from the registry so skills/users can discover valid IDs (no broad run
  required). Dynamic families print as `WD-FLOW-*` (not fabricated concrete numbers).
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
  results down to the target**. For an exact ID, filter to that ID; for a **family** target
  (`WD-FLOW-*`) keep all emitted IDs in the family; for an exact dynamic ID (`WD-FLOW-002`) keep
  just that one. (Granular per-check execution is *not* required — hydrate-then-filter is the
  contract.)
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

- `flightcheck --list-checkpoints` lists every **registered setup** checkpoint ID and family from
  the registry (no broad run) — the ESS+Workday setup surface, not other integrations' checkpoints
  (which remain reachable via `--scope`).
- `flightcheck --checkpoint <ID>` hydrates declared prerequisites, runs only the target, and
  prints a single structured result — **without** requiring clients the checkpoint doesn't
  need (e.g. an Entra-only ID runs with no Dataverse endpoint configured).
- Client/config initialization covers the **transitive closure** of the target's prerequisites,
  not just its own first-level declarations.
- A unit test (**`tests/flightcheck/test_registry.py`**) asserts the prereq graph is **acyclic**
  and that every prerequisite ID **or family** resolves.
- A **drift test** (**`tests/flightcheck/test_registry_drift.py`**) runs a full check and asserts
  the registry covers every **setup-owned** checkpoint ID emitted — so the setup registry never
  silently drifts from what the setup category functions emit. It is **scoped, not a global
  `registry ⊇ all-emitted` assertion**: the registry declares an explicit **owned-prefix
  allow-list** (`ENV-001`, `ENV-002`, `ENV-CAPACITY`, `ESS-SOLN`, `WD-PKG`, `WD-CONN`, `WD-FLOW`,
  `WD-WF`, `WD-ENV`, `WD-ENTRA`, `WD-ASSIGN`, `WD-TENANT`, `WD-API-CLIENT`, `WD-REST`, `WD-NET`,
  `DV-CONN`, `TOPIC-TRIGGER`, `TOPIC-INTEGRATION`). For each emitted ID: (1) **resolve via the
  registry's own resolution** — exact entry first; **only if none**, longest-prefix match against a
  registered family (the emitter **zero-pads**, so `WD-FLOW-001` / `WD-CONN-003` / `WD-WF-002`
  resolve to `WD-FLOW-*` / `WD-CONN-*` / `WD-WF-*`); (2) if it resolves → **pass**; (3) if it does
  **not** resolve **and** its prefix is in the owned allow-list → **FAIL** (an added/renamed setup
  checkpoint nobody registered); (4) if it does not resolve and is **outside** the allow-list →
  **ignore** (it belongs to another integration — e.g. `SN-CONN-*`, `SN-FLOW-*`, `EXT-002-*`,
  `SAP-*`, or the pre-existing `ENV-003`/`ENV-004` + `ENV-004-OR/UR/UC` rows — validated via
  `--scope`, not this registry). The runner's synthetic `{category[:3].upper()}-ERR` exception
  sentinels (emitted by `scripts/flightcheck/runner.py` only on an unhandled category exception) are
  **always ignored** — they are error markers, not checkpoints. **Never blanket-strip a trailing
  `-\d+`** — that would fabricate bogus families and mis-bucket fixed IDs such as `WD-CONN-012`,
  `ENV-001`, or `WD-REST-001`/`WD-REST-002` (which would also collide into a single non-existent
  `WD-REST` family). Because owned IDs are also emitted conditionally inside large category
  functions (e.g. before a no-Workday early-return), this test still catches an added/renamed setup
  checkpoint that nobody registered.
- Unknown ID → clear error naming valid IDs; non-zero exit.
- Existing `--scope` runs are unchanged in behavior.
- A `MANUAL` checkpoint run in isolation reports `MANUAL` and exits success (doesn't fail readiness).

## Out of scope

- New scopes or new Workday checkpoints (those live in other plans).
- Any change to how checkpoints are *defined* beyond the registry + single-ID selection.
- Refactoring every check into an independently-registered unit (the registry's
  hydrate-then-filter model deliberately avoids that larger rewrite).
