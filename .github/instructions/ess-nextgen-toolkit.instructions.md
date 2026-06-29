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
- Respect architectural boundaries and dependency direction
  (UI → Core → Migration → Services → SDK → Dataverse).
- Determinism is required; never delete customer customizations.
- Keep dependencies pinned and reproducible (`uv.lock` is the source of truth;
  update `pyproject.toml` + `uv.lock` + the `requirements*.txt` exports together).

When in doubt, improve the specification before changing the implementation.
