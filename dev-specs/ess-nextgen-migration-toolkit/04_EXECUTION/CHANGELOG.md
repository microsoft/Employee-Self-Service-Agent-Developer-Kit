# CHANGELOG.md

# ESS NextGen Migration Toolkit — Changelog

All notable changes to the ESS NextGen Migration Toolkit are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Each entry should reference the governing Migration Rule (`RULE-XXX`) and/or
task (`TASK-XXX`) where applicable, per `IMPLEMENTATION_GUIDE.md`.

## [Unreleased]

- **Pipeline framework redesign (super-pipeline + typed stages).** Reworked
  `02_ARCHITECTURE/PIPELINES.md` to v2.0: the toolkit is now a fluent
  **super-pipeline** of three stage pipelines — **Input → Migration → Output** —
  over a shared, typed `MigrationContext`. The framework is generic
  (`Pipeline[TInput, TOutput]`, `PipelineStep[TInput, TOutput]`) with a
  type-threading Builder (mapping the C# `KeyedComputeUnitBase` /
  `HeterogenousPipelineStepComputeUnitBase<TIn,TOut>` reference; C# runtime
  concerns — Autofac keyed registration, epoch versioning, per-step
  Equals/GetHashCode — intentionally not ported). The **Migration Orchestrator
  is only the composition root**. Added `PIPE-008/009/010` (PIPELINES) and
  `PIPE-007` (INVARIANTS). Added the keyed `ComponentSet` (ComponentType →
  Component[]) to `MigrationContext`. Updated TASK-002/003/006/007.
- **Session bundle diagnostics (two-file UX).** Reworked
  `03_ENGINEERING/DIAGNOSTICS.md`: every execution produces exactly one
  timestamped **session bundle** `output/session-<timestamp>/` with two files —
  `migration_report.md` (customer-facing; summary + changes + warnings sections)
  and `session.log` (ESS-engineer diagnostics). Steps accumulate into
  `MigrationContext` collectors (`Logs`, `Warnings`, `Errors`, `Changes`); a
  terminal `GenerateMigrationReport()` step renders the report via the Reporter
  service (no direct file I/O in steps). Added `DIAG-004`.
- **`debug/` → `output/` rename.** Replaced the `debug/logs` + `debug/reports`
  split with the single `output/session-<timestamp>/` bundle across specs
  (REPOSITORY_STRUCTURE, IMPLEMENTATION_GUIDE, TESTING, AGENTS, TASK-001/005/007)
  and the physical scaffold (`tools/…/output/.gitkeep`, `.gitignore`, README,
  toolkit `AGENTS.md`). Updated the instructions mirror.
- **TASK-001 — Repository Scaffold.** Created the frozen repository structure
  under `tools/ess-nextgen-migration-toolkit/` per
  `dev-specs/ess-nextgen-migration-toolkit/03_ENGINEERING/REPOSITORY_STRUCTURE.md`
  section 2: `src/` layout (`mtk.py`, constants, core with pipeline,
  orchestrator, logging, models, and outbound; service with utils and modules
  for preprocessing, migration, and postprocessing; output for session bundles),
  `tests/` layout (unit, integration, golden, e2e), `scripts/`, plus
  `pyproject.toml`, `.pre-commit-config.yaml`, `.gitignore`, and `README.md`.
  No business logic introduced.
- **Deterministic environment.** Added **pip-free** `uv`-based dependency
  management: `uv.lock` (committed source of truth), `.python-version` (pinned
  interpreter), and `scripts/setup.{sh,ps1}` one-command bootstrap that installs
  `uv` if missing, has `uv` provision the pinned Python (managed standalone
  CPython — no system Python), and runs `uv sync` (which creates `.venv`
  automatically). Added `scripts/refresh.{sh,ps1}` to pull the latest code,
  re-sync, and run. Documented in
  `dev-specs/ess-nextgen-migration-toolkit/03_ENGINEERING/REPOSITORY_STRUCTURE.md`
  section 11a and
  `dev-specs/ess-nextgen-migration-toolkit/03_ENGINEERING/CODING_STANDARDS.md`
  section 15a. Python floor raised to 3.10.
- **Single `mtk` command surface.** Consolidated provisioning + running into one
  dispatcher, `scripts/mtk.{sh,ps1}` (`mtk start [--dev]`, `mtk refresh`,
  `mtk help`), driven through a single logic-free forwarder `mtk.{sh,ps1}` at the
  **monorepo root** (`./mtk.sh <subcommand>`, mirroring `./gradlew`/`./mvnw`);
  the dispatcher changes into the toolkit directory implicitly, so invocation is
  cwd-independent. `mtk start` provisions (idempotent) **and runs** the toolkit;
  `mtk refresh` = `git pull --ff-only` then `start`, sharing the exact same
  provision-then-run path. `--dev` applies to `start` only; `refresh` is the
  customer update path and always provisions a runtime-only environment. New
  operational behavior is added as a subcommand, never a new top-level script.
  Replaces the separate `setup.{sh,ps1}` / `refresh.{sh,ps1}`. The two
  monorepo-root forwarder files are the only sanctioned toolkit artifacts outside
  the toolkit folder — a deliberate, documented scope exception. Convention
  documented in
  `dev-specs/ess-nextgen-migration-toolkit/03_ENGINEERING/REPOSITORY_STRUCTURE.md`
  section 11b and
  `dev-specs/ess-nextgen-migration-toolkit/03_ENGINEERING/CODING_STANDARDS.md`
  section 15a.
- **Dev tooling as a dependency-group.** Declared ruff/mypy/pytest/pre-commit as
  a PEP 735 `[dependency-groups] dev` (not a `[project.optional-dependencies]`
  extra) so `uv run <tool>` works for contributors without uv's implicit sync
  pruning the tool. `mtk start --dev` runs plain `uv sync` (dev included by
  default); runtime/customer paths use `uv sync --no-dev` and `uv run --no-dev`.
- **Pre-commit hard-scoped to the toolkit, auto-installed by start.** Rewrote
  `.pre-commit-config.yaml` as `local` hooks that run the locked
  ruff/ruff-format/mypy via `uv run --project tools/ess-nextgen-migration-toolkit`
  (no version drift vs. the external ruff-pre-commit/mirrors-mypy repos, which
  previously pinned far older v0.4.10/v1.10.0). Every hook is restricted with
  `files: ^tools/ess-nextgen-migration-toolkit/` so commits elsewhere in the
  monorepo are a no-op. `mtk start --dev` runs `pre-commit install` (one-time,
  per clone) so the gates fire automatically on `git commit` without contributors
  running anything by hand. Dropped the per-commit unit-test hook (tests run via
  `uv run pytest` / CI; keeps commits fast and avoids the empty-scaffold exit-5).
- **CLI-only entry point; UI layer dropped.** Removed the `ui/` architectural
  layer in favor of a single command-line entry point, `src/mtk.py` (currently a
  hello-world placeholder; subcommands and business logic land later). The CLI is
  the top architectural layer in every dependency diagram (formerly labelled
  `UI`). The remaining structure is `core` (`pipeline`, `orchestrator`,
  `logging`, `models`, `outbound`), `service` (`utils`, `modules` with
  `preprocessing`, `migration`, `postprocessing`), `constants`, and `debug`.
  Updated
  `00_META/INVARIANTS.md`, `02_ARCHITECTURE/ARCHITECTURE.md`,
  `02_ARCHITECTURE/SERVICES.md`,
  `03_ENGINEERING/REPOSITORY_STRUCTURE.md`,
  `03_ENGINEERING/CODING_STANDARDS.md`, and `AGENTS.md` accordingly.
- **Source tree finalized around core, service modules, and debug output.**
  Moved canonical models under `src/core/models/`; renamed the Dataverse
  integration folder to `src/core/outbound/` and the concept to the Dataverse
  client; changed `services/` to singular `service/`; introduced
  `src/service/modules/` for preprocessing, migration, and postprocessing;
  relocated generated logs and reports to `debug/logs/` and
  `debug/reports/`; and updated the architecture spec index to use
  `02_ARCHITECTURE/DATAVERSE_CLIENT.md`. Relaxed the old service-layer physical
  boundary: migration rules now live exclusively in
  `src/service/modules/migration/steps/`, while reusable service capabilities
  outside `service/modules/` remain rule-free. Governing structure is defined in
  `dev-specs/ess-nextgen-migration-toolkit/03_ENGINEERING/REPOSITORY_STRUCTURE.md`
  section 2 and ownership in
  `dev-specs/ess-nextgen-migration-toolkit/03_ENGINEERING/REPOSITORY_STRUCTURE.md`
  section 5.
- **Task backlog split into per-task ADO-style files.** Replaced the inline task
  bodies in `04_EXECUTION/TASKS.md` with per-task files under
  `04_EXECUTION/tasks/` (`TASK-XXX-<slug>.md`), each following a fixed structure
  (header table with ID/Workstream/Status/Consumes, Description, Acceptance
  Criteria, Deliverables, References). `TASKS.md` is now the index, linking to
  each task file via per-workstream tables. Updated the AI Execution Algorithm
  and Dependency-Based Loading Model in `AGENTS.md` to resolve a task by opening
  its file under `04_EXECUTION/tasks/`.
- **CA→DA workarounds tightened; tasks reframed around their step.** Aligned the
  deprecation marker for disabled topics to the uppercase form `[DEPRECATED]`
  across `01_PRODUCT/MIGRATION_RULES.md` (RULE-003 Handle OnActivity, RULE-004
  Handle OnGeneratedResponse — Preconditions, Transformation, and Validation),
  matching the CA Components support-in-DA analysis; the idempotency skip
  (INVARIANT MIG-005) keys on the same marker. Made the RULE-002 (Replace
  EndConversation) transformation name the target explicitly as
  `CancelAllDialogs (End All Topics)`. Reframed `TASK-010`…`TASK-013` so each
  task is defined by the Pipeline Step it delivers (e.g.
  `ReplaceEndConversationStep`, `HandleOnActivityTopicStep`,
  `HandleGeneratedResponseTopicStep`) and the transformation behavior it must
  produce, rather than pointing at the `src/service/modules/migration/steps/`
  location — the step is the implementation of the task. The physical location
  of steps remains owned by `00_META/INVARIANTS.md` and
  `03_ENGINEERING/REPOSITORY_STRUCTURE.md`, not the task files.
- **Definition of Done now requires documentation sync.** Added an explicit
  Definition of Done item in `04_EXECUTION/TASKS.md` section 5 requiring that
  documentation be updated wherever applicable — README, any affected dev-specs,
  and `CHANGELOG.md` — so specifications and implementation stay synchronized.
  This makes the doc-sync expectation already implied by `AGENTS.md`,
  `03_ENGINEERING/CODING_STANDARDS.md`, and
  `03_ENGINEERING/IMPLEMENTATION_GUIDE.md` an enforceable part of the master's
  per-task review gate.
- **`modules/` promoted to a top-level layer; `service/` is now the
  orchestration entry.** Resolved the contradiction between the Service
  invariants ("the service layer contains no migration rules") and the physical
  placement of migration steps under `service/modules/`. Moved
  `src/service/modules/` → **`src/modules/`** (sibling of `service/` and
  `core/`), moved `src/service/utils/` → **`src/core/utils/`**, dropped the
  `src/core/orchestrator/` package, and removed `src/mtk.py`. The single
  orchestration entry point is now **`src/service/mtk_orchestrator.py`**
  (hello-world placeholder); the `mtk` dispatcher (`scripts/mtk.{sh,ps1}`)
  launches it. Rewrote the layer model to `Orchestration → Pipeline → Modules →
  Dataverse Client → Dataverse` across `00_META/INVARIANTS.md` (ARCH-001,
  SERVICE-001), `02_ARCHITECTURE/ARCHITECTURE.md` (sections 4, 5.1, 7),
  `02_ARCHITECTURE/SERVICES.md` (retitled to the Service/Orchestration layer;
  the capability catalogue is now documented as responsibilities realized within
  `modules/` and `core/`, not a physical services folder),
  `03_ENGINEERING/REPOSITORY_STRUCTURE.md` (tree, ownership matrix, module
  descriptions), `03_ENGINEERING/CODING_STANDARDS.md`, `00_META/VOCABULARY.md`,
  and `AGENTS.md`. Re-pointed `TASK-001` and `TASK-003` to the new paths.
  Repurposed the former `TASK-008` "Command Line Interface" into **`TASK-999` —
  "Manual End-to-End Validation"**, a new *Workstream 3 — Final Validation* whose
  sentinel `TASK-999` ID always sorts last (the final manual sanity/sign-off gate
  on a real migration). User interaction and session-input gathering now belong
  solely to the orchestrator (`TASK-003`), eliminating the former
  CLI/orchestrator overlap. Renamed the task file to
  `TASK-999-manual-e2e-validation.md`.
- **Synced the top-level Copilot instructions mirror to the restructure and made
  it a doc-sync target.** Corrected two stale statements in
  `.github/instructions/ess-nextgen-toolkit.instructions.md`: the dependency
  direction (`UI → Core → Migration → Services → SDK → Dataverse` →
  `Orchestration → Pipeline → Modules → Dataverse Client → Dataverse`) and the
  dependency-management step (dropped the non-existent `requirements*.txt`
  exports; it is `pyproject.toml` + `uv.lock` only, per
  `03_ENGINEERING/CODING_STANDARDS.md` section 16). Added a self-guard "Keep this
  file in sync" section to that file, and listed it explicitly as a doc-sync
  target in the Definition of Done (`04_EXECUTION/TASKS.md` section 5) and in the
  Documentation Requirements (`AGENTS.md` section 15), so any change to the
  layer/dependency model, repository structure, invariants,
  dependency-management workflow, or naming conventions must update the mirror in
  the same change.
- **TASK-008 — Authentication Token Provider (new foundation task).** Added a new
  Workstream 0 task defining the toolkit's token *producer* — the single
  primitive that acquires and refreshes Dataverse access tokens — reusing the
  vacated `TASK-008` slot. The specifications keep every downstream layer as a
  token *consumer*: `AuthenticationService` only accepts a bearer token and never
  stores credentials (`02_ARCHITECTURE/SERVICES.md` section 13), and
  `AuthenticationClient` never acquires, refreshes, or persists tokens
  (`02_ARCHITECTURE/DATAVERSE_CLIENT.md` section 5, Dataverse Client-005), yet
  nothing produced the token they consume. The provider fills that gap at
  `src/core/auth/`, performs **proactive refresh** (`get_token()` returns a
  currently-valid token on every read and writeback so hour-plus sessions never
  issue an expired token), and — diverging from the `solutions/ess-maker-skills`
  reference pattern — keeps its MSAL cache **in memory only**, never persisting
  tokens, per `00_META/INVARIANTS.md` DIAG-003. Added the task file
  `TASK-008-authentication-token-provider.md` and its `TASKS.md` index row.
- **`TASK-004` consumes the Token Provider; Dataverse module renamed.** Updated
  `TASK-004` so authentication is provided externally by `TASK-008` (the client
  accepts a fresh bearer token per request and never acquires/refreshes/persists
  it), and renamed the Dataverse module `dataverse_api.py` → `dataverse_client.py`
  across the stub (`git mv`), `03_ENGINEERING/REPOSITORY_STRUCTURE.md` (tree +
  section 5 + section 12; also added the `core/auth/` package to the tree),
  `03_ENGINEERING/IMPLEMENTATION_GUIDE.md`, and the toolkit `README.md`.

### Changed

- (nothing yet)

### Fixed

- (nothing yet)
