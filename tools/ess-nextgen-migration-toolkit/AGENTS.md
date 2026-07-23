# AGENTS.md

# ESS NextGen Migration Toolkit — AI Agent Operating Manual

> **Canonical location notice**
>
> This repository follows **Specification-Driven Development (SDD)**, and the
> AI Agent Operating Manual is a specification. To avoid two divergent
> constitutions, the **single source of truth** for agent behavior lives with
> the specifications, not in this build tree.
>
> **Canonical file:**
> [`dev-specs/ess-nextgen-migration-toolkit/AGENTS.md`](../../dev-specs/ess-nextgen-migration-toolkit/AGENTS.md)
>
> Read and follow the canonical `AGENTS.md` in full before implementing any
> task. Do not duplicate or fork its rules here.

---

# How the repository is organized

* **Specifications (source of truth)** live at the repository root under
  `dev-specs/ess-nextgen-migration-toolkit/`:

  ```text
  00_META/        PROJECT.md, INVARIANTS.md, VOCABULARY.md, ROADMAP.md, AGENTS.md
  01_PRODUCT/     CUSTOMER_JOURNEY.md, MIGRATION_MODES.md, MIGRATION_RULES.md
  02_ARCHITECTURE/ ARCHITECTURE.md, DOMAIN_MODEL.md, SERVICES.md, PIPELINES.md, DATAVERSE_CLIENT.md
  03_ENGINEERING/ REPOSITORY_STRUCTURE.md, CODING_STANDARDS.md, DIAGNOSTICS.md, TESTING.md, IMPLEMENTATION_GUIDE.md
  04_EXECUTION/   TASKS.md, CHANGELOG.md
  ```

* **The buildable toolkit (implementation)** lives here under
  `tools/ess-nextgen-migration-toolkit/` (`src/`, `tests/`, `scripts/`, etc.),
  with generated output under `output/session-<timestamp>/`, as defined by
  [`REPOSITORY_STRUCTURE.md`](../../dev-specs/ess-nextgen-migration-toolkit/03_ENGINEERING/REPOSITORY_STRUCTURE.md).

## Implementation navigation

| Concern               | Implementation location                         |
| --------------------- | ----------------------------------------------- |
| Pipeline framework    | `src/core/pipelines/`                           |
| Dataverse APIs        | `src/core/outbound/`                            |
| Domain Models         | `src/core/models/` + `src/modules/transformation/models/` |
| Migration Rules       | `src/modules/transformation/steps/`             |
| Migration Step base   | `src/modules/transformation/migration_step.py`  |
| Input Pipeline        | `src/modules/preprocessing/`                    |
| Output Pipeline       | `src/modules/postprocessing/`                   |
| Orchestrator          | `src/service/mtk_orchestrator.py`               |
| Constants             | `src/service/constants.py`                      |
| Utilities             | `src/core/utils/`                               |
| Diagnostics (Logger, sessions) | `src/core/logging/`                    |
| Report renderer       | `src/service/reporter.py`                       |
| Execution modes       | `src/modules/transformation/models/execution_mode.py` |
| CLI dispatcher        | `scripts/mtk.sh` / `scripts/mtk.ps1` (`mtk run`) |
| Generated output      | `output/session-<timestamp>/`                   |

---

# Required reading order

Follow the reading order and specification hierarchy defined in the canonical
`AGENTS.md` and in
[`IMPLEMENTATION_GUIDE.md`](../../dev-specs/ess-nextgen-migration-toolkit/03_ENGINEERING/IMPLEMENTATION_GUIDE.md).

This pointer file intentionally contains no independent rules. If anything here
appears to conflict with the canonical `AGENTS.md`, the canonical file wins.
