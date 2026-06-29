# ESS NextGen Migration Toolkit — Specifications

This directory is the **source of truth** for the ESS NextGen Migration
Toolkit. The repository follows **Specification-Driven Development (SDD)**:
specifications define the system, and code is one implementation of those
specifications.

> **Where is the code?** The buildable toolkit (`src/`, `tests/`, etc.) lives
> under `tools/ess-nextgen-migration-toolkit/`. These specifications live here
> under `dev-specs/ess-nextgen-migration-toolkit/`. See
> `03_ENGINEERING/REPOSITORY_STRUCTURE.md`.

## Start here

Read [`AGENTS.md`](AGENTS.md) first — it is the orchestrator and defines the
specification classification and the dependency-based loading model that tells
you which documents to read for a given task.

## Specification layers

| Layer            | Folder            | Documents |
| ---------------- | ----------------- | --------- |
| Meta             | `00_META/`        | `PROJECT.md`, `INVARIANTS.md`, `VOCABULARY.md`, `ROADMAP.md` |
| Product          | `01_PRODUCT/`     | `CUSTOMER_JOURNEY.md`, `MIGRATION_MODES.md`, `MIGRATION_RULES.md` |
| Architecture     | `02_ARCHITECTURE/`| `ARCHITECTURE.md`, `DOMAIN_MODEL.md`, `SERVICES.md`, `PIPELINES.md`, `DATAVERSE_CLIENT.md` |
| Engineering      | `03_ENGINEERING/` | `REPOSITORY_STRUCTURE.md`, `CODING_STANDARDS.md`, `DIAGNOSTICS.md`, `TESTING.md`, `IMPLEMENTATION_GUIDE.md` |
| Execution        | `04_EXECUTION/`   | `TASKS.md`, `CHANGELOG.md` |

## Working in this repository

1. Read `AGENTS.md` (Phase 0).
2. Resolve your task in `04_EXECUTION/TASKS.md` (`TASK-XXX`).
3. Resolve any governing rule in `01_PRODUCT/MIGRATION_RULES.md` (`RULE-XXX`).
4. Read the task's `References` specifications, plus the Constitution
   (`00_META/PROJECT.md`, `INVARIANTS.md`, `VOCABULARY.md`).
5. Implement, test, update `TASKS.md`, and update `04_EXECUTION/CHANGELOG.md`.

Specifications are authoritative. If implementation requires a behavioral or
structural change, update the specification first.
