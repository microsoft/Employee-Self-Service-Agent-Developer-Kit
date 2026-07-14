---
applyTo: "tools/ess-nextgen-migration-toolkit/**,dev-specs/ess-nextgen-migration-toolkit/**"
---

# ESS NextGen Migration Toolkit — Copilot instructions

These instructions apply when working anywhere inside the ESS NextGen Migration
Toolkit — its specifications (`dev-specs/ess-nextgen-migration-toolkit/`) or its
buildable code (`tools/ess-nextgen-migration-toolkit/`).

This toolkit follows **Specification-Driven Development (SDD)**: the
specifications are the source of truth, and code is one implementation of them.

## Read the canonical constitution first

The single source of truth for agent behavior is the AI Agent Operating Manual:

- [`dev-specs/ess-nextgen-migration-toolkit/AGENTS.md`](../../dev-specs/ess-nextgen-migration-toolkit/AGENTS.md)

Read and follow it in full before implementing any task. It defines the
specification classification, the dependency-based loading model, the
specification hierarchy (conflict resolution), the repository invariants, and
the implementation algorithm. Do not duplicate or fork its rules here — if
anything appears to conflict, the canonical `AGENTS.md` wins.

## Non-negotiables (summary only — the specs are authoritative)

- Every implementation originates from an approved `TASK-XXX` in
  `04_EXECUTION/TASKS.md`; resolve its `Consumes`/`References` before coding.
- One Migration Rule (`RULE-XXX`) maps to exactly one Pipeline Step.
- The toolkit is a fluent **super-pipeline** of three stage pipelines —
  Input → Migration → Output — over a shared, typed `MigrationContext`; the
  Migration Orchestrator is only the composition root (build, configure,
  execute, return). Pipelines and steps are generic:
  `Pipeline[TInput, TOutput]`, `PipelineStep[TInput, TOutput]`.
- Every execution produces one session bundle `output/session-<timestamp>/`
  with exactly two files: `migration_report.md` (customer) and `session.log`
  (ESS engineer). Steps accumulate into `MigrationContext` collectors; only the
  Logger and Reporter service write files.
- Respect architectural boundaries and dependency direction
  (Orchestration → Pipeline → Modules → Dataverse Client → Dataverse).
- Determinism is required; never delete customer customizations.
- Keep dependencies pinned and reproducible (`uv.lock` is the source of truth;
  update `pyproject.toml` and `uv.lock` together).

When in doubt, improve the specification before changing the implementation.

## Keep this file in sync

This file is a **summary mirror** of the canonical specifications, not a source
of truth. Whenever a dev-spec or code change alters what it summarizes — the
layer/dependency model, repository structure, invariants, dependency-management
workflow, or naming conventions — update this file in the same change so it
never goes stale. If it ever conflicts with
`dev-specs/ess-nextgen-migration-toolkit/AGENTS.md` or the specs it points to,
the canonical specs win and this file must be corrected.
