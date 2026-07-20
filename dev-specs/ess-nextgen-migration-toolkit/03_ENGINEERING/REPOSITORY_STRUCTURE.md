# REPOSITORY_STRUCTURE.md

# ESS NextGen Migration Toolkit — Repository Structure Specification
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the canonical repository structure of the ESS NextGen Migration Toolkit.
>
> The repository layout is intentionally **fixed** for the lifetime of this project.
>
> AI agents and human contributors shall implement new functionality within this structure rather than introducing new architectural layers or reorganizing the repository.

---

# 1. Design Goals

The repository structure is designed to provide:

* Predictable implementation locations
* Strong separation of concerns
* AI-friendly navigation
* Minimal architectural churn
* Clear ownership boundaries
* Specification-driven development

The physical repository mirrors the logical architecture defined in `ARCHITECTURE.md`.

---

# 2. Repository Layout

Specifications and the buildable toolkit live in two separate trees at the repository root.

Specifications (the source of truth) live under `dev-specs/`:

```text
dev-specs/

└── ess-nextgen-migration-toolkit/

    AGENTS.md

    00_META/
    01_PRODUCT/
    02_ARCHITECTURE/
    03_ENGINEERING/
    04_EXECUTION/
```

The buildable toolkit lives under `tools/`:

```text
tools/

└── ess-nextgen-migration-toolkit/

    AGENTS.md

    src/
        constants/
        core/
            auth/
                token_provider.py
            pipelines/
                pipeline.py
                pipeline_step.py
                chained_pipeline.py
            logging/
            models/
                execution_context.py
            outbound/
                dataverse_client.py
            utils/
        modules/
            preprocessing/
            migration/
                migration_step.py
                migration_pipeline.py
                models/
                    migration_context.py
                steps/
            postprocessing/
        service/
            mtk_orchestrator.py
            toolkit.py

    output/
        session-YYYY-MM-DD_HH-MM-SS/
            migration_report.md
            session.log

    tests/

        unit/
        integration/
        golden/
        e2e/

    scripts/
        mtk.sh
        mtk.ps1

    .pre-commit-config.yaml

    .python-version

    pyproject.toml

    uv.lock

    README.md
```

---

# 3. Repository Ownership

Every folder owns exactly one architectural concern.

---

## core/

Owns framework infrastructure.

Contains:

* Pipeline Engine
* Pipeline Builder
* Pipeline Registry
* Execution Context
* Logging Framework

Never contains:

* Dataverse REST calls
* Migration rules
* ESS-specific business logic

---

## core/models/

Owns canonical domain models.

Contains only business entities shared across the framework.

Examples:

* MigrationContext
* MigrationSession
* Component
* ComponentLayer
* MigrationCandidate
* ValidationResult
* MigrationReport

Never contains:

* REST payloads
* Business logic

---

## constants/

Owns shared constants.

Examples:

* Execution Modes
* Component Types
* Solution Component Types
* Configuration Keys

Contains no executable logic.

---

## core/outbound/

Owns Dataverse communication through the generic Dataverse client.

Contains:

* Authentication
* REST API wrappers
* Serialization
* Deserialization
* Retry handling

Initially implemented as:

```text
dataverse_client.py
```

Business logic never belongs here.

---

## service/

Owns application orchestration — the top of the dependency graph and the
toolkit's entry point.

Contains:

* `mtk_orchestrator.py`

Responsibilities include:

* Initialize and coordinate a migration session
* Build the MigrationContext and select the Execution Mode
* Drive the Pipeline Engine over the pipeline-stage modules
* Coordinate progress, failures, and final results

The service layer never performs business transformations (those belong to
Migration Steps) and never contains migration rules.

---

## core/utils/

Owns framework-independent helpers.

Examples:

* Utility methods
* Generic exceptions
* Shared helper functions

Utilities remain generic and reusable.

---

## modules/

Owns pipeline-stage business logic grouped by execution phase.

Contains:

* `preprocessing/`
* `migration/`
* `postprocessing/`

Reusable service helpers outside this grouping must not contain migration rules.

---

## modules/migration/

Owns business transformations.

Contains:

* Migration Pipeline
* Pipeline Step implementations

Every Pipeline Step performs one logical transformation.

Examples:

* Runtime Provider transformation
* Template transformation
* Model Kind transformation
* Conversation Node transformation

Migration rules live exclusively in
`src/modules/migration/steps/`. Migration Steps never call Dataverse
directly.

---

## modules/preprocessing/

Owns discovery and preparation.

Responsibilities include:

* Discover ESS Agents
* Retrieve Dependencies For Uninstall
* Retrieve Solution Component Layers
* Determine migration candidates
* Load canonical components

No transformations occur here.

---

## modules/postprocessing/

Owns execution after transformation.

Responsibilities include:

* Validation
* Writeback
* Report generation

No migration rules belong here.

---

## service/mtk_orchestrator.py

The orchestration entry point and top of the dependency graph. Owns application
composition and session coordination.

Responsibilities include:

* Compose the lower layers (Pipeline Engine, modules, Dataverse client)
* Coordinate the migration session lifecycle
* Report progress and final results

The orchestrator never performs migration logic (transformations belong to
Migration Steps). For now `mtk_orchestrator.py` is a hello-world placeholder;
orchestration logic and any command surface are added later.

---

## output/

Owns generated, gitignored execution output. It sits at the toolkit root as a
sibling of `src/` (not a Python package).

Contains one timestamped **session bundle** per execution:

* `session-YYYY-MM-DD_HH-MM-SS/`
  * `migration_report.md` — customer-facing report
  * `session.log` — ESS-engineer diagnostics log

The folder is retained in version control only through a `.gitkeep` file.

---

# 4. Dependency Rules

Dependencies shall flow only in the following direction.

```text
Service

↓

Core

↓

Dataverse Client

↓

Dataverse
```

Models and Constants may be referenced by every layer.

No layer may bypass another layer.

---

# 5. Folder Ownership Matrix

| Folder                             | Responsibility                         |
| ---------------------------------- | -------------------------------------- |
| core                               | Framework execution                    |
| core/models                        | Canonical domain models                |
| core/outbound                      | Dataverse communication — the Dataverse client  |
| core/utils                         | Generic helper functionality           |
| constants                          | Shared constants                       |
| service                            | Application orchestration and entry point |
| service/mtk_orchestrator.py        | Orchestration entry point              |
| modules                    | Pipeline-stage business logic          |
| modules/preprocessing      | Discovery pipeline                     |
| modules/migration          | Business transformations               |
| modules/postprocessing     | Validation and persistence             |
| debug                              | Generated logs and reports             |

---

# 6. Specification Mapping

| Specification           | Primary Implementation Folder |
| ----------------------- | ----------------------------- |
| ARCHITECTURE.md         | core                          |
| DOMAIN_MODEL.md         | core/models                   |
| SERVICES.md             | service                       |
| DATAVERSE_CLIENT.md    | core/outbound                 |
| PIPELINES.md            | core + modules        |
| MIGRATION_RULES.md      | modules/migration     |
| DIAGNOSTICS.md          | core/logging + debug          |
| IMPLEMENTATION_GUIDE.md | Entire repository             |

---

# 7. Repository Invariants

The repository structure is considered **frozen**.

Implementation tasks shall not:

* Introduce new top-level folders.
* Move existing folders.
* Bypass architectural boundaries.
* Duplicate responsibilities across folders.
* Create alternative implementations outside the prescribed layout.

If implementation requires a structural change, the corresponding specification must be updated before implementation proceeds.

---

# 8. File Organization Rules

Each source file should:

* Have one primary responsibility.
* Contain one primary public class.
* Follow the dependency rules defined in this specification.

Avoid unrelated public classes within the same file.

---

# 9. Testing Layout

```text
tests/

    unit/

    integration/

    golden/

    e2e/
```

Unit tests mirror the `src/` directory.

Golden tests validate deterministic migration outputs.

Integration tests validate Dataverse interactions.

End-to-end tests validate complete migration workflows through the Orchestrator.

---

# 10. Logging and Reports

Each execution produces one timestamped session bundle under:

```text
output/session-YYYY-MM-DD_HH-MM-SS/
```

The bundle contains exactly two files: `migration_report.md` (customer-facing)
and `session.log` (ESS-engineer diagnostics). Session logs are written using the
framework logging abstraction; the report is rendered by the Reporter service.

Business logic must never write files directly.

---

# 11. Pre-Commit Requirements

The repository shall enforce quality gates through pre-commit hooks.

Examples include:

* Formatting
* Linting
* Type checking
* Unit test execution
* Prevention of direct `print()` statements
* Prevention of accidental debug artifacts

Logging must always use the framework logging abstraction.

---

# 11a. Dependency Management and Reproducibility

Determinism extends to the build and runtime environment: every contributor and
every customer shall be able to install and run the toolkit with identical,
pinned dependency versions.

The toolkit shall use:

* **`pyproject.toml`** — PEP 621 project metadata with the `hatchling` build
  backend. The canonical source-layout packages under `src/` are mapped
  explicitly in `[tool.hatch.build.targets.wheel]`. Developer tooling (ruff,
  mypy, pytest, pre-commit) is declared as a **PEP 735 dependency-group**
  (`[dependency-groups] dev`), **not** an optional-dependency extra. `uv`
  includes the `dev` group by default for both `uv sync` and `uv run`, so
  contributor commands such as `uv run ruff check .` work without the tool being
  pruned; customers exclude it with `--no-dev`. (An optional *extra* would be
  pruned by `uv run`'s implicit sync — a deliberate avoidance.)
* **`uv.lock`** — the locked, hashed dependency graph. This is the source of
  truth for dependency resolution and shall be committed to version control.
* **`.python-version`** — the pinned interpreter version used to resolve and run
  the toolkit.
* **`scripts/mtk.{sh,ps1}`** — the single `mtk` command dispatcher. It is
  self-sufficient and **pip-free**: `mtk start` installs `uv` if missing (its
  standalone installer requires no Python), has `uv` provision the pinned Python
  (a managed, standalone CPython — no system Python or admin rights), runs
  `uv sync` (which creates `.venv` automatically), then runs the toolkit. `pip`
  is never used. `mtk refresh` fast-forwards the current branch from its remote,
  then runs `start` (re-provision runtime — it is the customer update path, so it
  does not accept `--dev` — and launch). New operational commands are added as
  **new `mtk` subcommands**, never as new top-level scripts.
* **`mtk.sh` / `mtk.ps1`** (at the **monorepo root**, not the toolkit root) —
  the single logic-free forwarders that `exec`/invoke
  `tools/ess-nextgen-migration-toolkit/scripts/mtk.*`. They exist only so the
  command can be invoked ergonomically from the top of the monorepo
  (`./mtk.sh start`), mirroring the `./gradlew` / `./mvnw` Dataverse client convention.
  The dispatcher changes into the toolkit directory itself, so these forwarders
  need no logic. There is intentionally no second forwarder at the toolkit root.

The minimum supported Python version is declared by `requires-python` in
`pyproject.toml` and shall match `.python-version`'s major/minor floor.

Whenever dependencies change, `pyproject.toml` and `uv.lock` shall be updated and
committed together.

---

# 11b. Command Entrypoint Convention

The toolkit exposes operational commands through a **single dispatcher**, not a
proliferation of per-task scripts. This is a deliberate low-level-design (LLD)
constraint that every contributor shall follow.

The convention has two layers:

1. **One dispatcher** — `scripts/mtk.{sh,ps1}` (`mtk` = *migration tool kit*).
   It parses a subcommand (`start`, `refresh`, `help`, …) plus shared options
   (e.g. position-independent `--dev`) and routes to the matching handler. All
   real logic lives here. It also **changes the working directory into the
   toolkit root** (`cd "$(dirname "$0")/.."`) before doing anything, so every
   command operates on the toolkit regardless of where it was invoked from.
2. **A single monorepo-root forwarder** — `mtk.{sh,ps1}` at the **repository
   root** `exec`/invoke `tools/ess-nextgen-migration-toolkit/scripts/mtk.*`,
   forwarding all arguments. They contain no logic and exist only for ergonomics
   (mirroring the `./gradlew` / `./mvnw` Dataverse client pattern), letting the toolkit be
   driven from the top of the monorepo (`./mtk.sh start`). Because the dispatcher
   changes into the toolkit directory implicitly, invocation is cwd-independent.
   These two files are the **only sanctioned toolkit artifacts outside
   `tools/ess-nextgen-migration-toolkit/`** — a deliberate, documented exception
   to the otherwise strict scope boundary, justified purely as an entrypoint
   convenience. There is intentionally **no second forwarder at the toolkit
   root**: one entrypoint, one place to look.

`mtk` covers the everyday command (`start` = provision + run) and the customer
update path (`refresh` = `git pull` then `start`).
Ad-hoc developer tasks — managing dependencies (`uv add`/`uv remove`/`uv lock`),
running linters, etc. — are **not** wrapped by `mtk`: contributors `cd` into
`tools/ess-nextgen-migration-toolkit/` and run `uv …` directly there. This keeps
`uv add` editing the toolkit's own `pyproject.toml` / `uv.lock` (a bare `uv add`
from the monorepo root would target the wrong project) without growing the
dispatcher into a thin proxy over uv.

Rules:

* **New operational behavior is a new subcommand**, never a new top-level
  script. Adding `mtk scan`, `mtk doctor`, etc. keeps the surface discoverable
  (`mtk help` lists everything) and avoids the script sprawl that erodes
  determinism and onboarding clarity.
* The dispatcher and forwarder shall remain **OS-paired** (`.sh` for
  POSIX shells, `.ps1` for PowerShell) and behaviorally identical.
* The forwarder shall stay **logic-free**; if you are tempted to add logic to it,
  it belongs in `scripts/mtk.*` as a subcommand or shared helper.
* The dispatcher **always operates on the toolkit** by changing into its root
  first; commands must never depend on the caller's current directory.

> **Rationale (for any dev reasoning about this design):** a single, self-
> describing entrypoint is easier to document, test, and evolve than a folder of
> ad-hoc scripts. It gives customers one command to learn and contributors one
> place to extend, while the root forwarder removes path friction without
> duplicating logic.

---

# 12. Future Evolution

New functionality should primarily be implemented by:

* Adding new Domain Models.
* Adding new Services.
* Adding new Pipeline Steps.
* Extending `dataverse_client.py`.
* Adding corresponding tests.

Framework infrastructure should remain stable throughout the lifetime of the migration toolkit.

---

# 13. Traceability

**Consumes**

* ARCHITECTURE.md
* DOMAIN_MODEL.md
* SERVICES.md
* PIPELINES.md
* DATAVERSE_CLIENT.md

**Referenced By**

* CODING_STANDARDS.md
* IMPLEMENTATION_GUIDE.md
* TASKS.md

This repository structure is a project invariant. AI agents and contributors shall treat it as fixed architecture and implement new capabilities within its prescribed boundaries rather than reorganizing the repository.
