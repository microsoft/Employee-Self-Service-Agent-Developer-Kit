# CHANGELOG.md

# ESS NextGen Migration Toolkit — Changelog

All notable changes to the ESS NextGen Migration Toolkit are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Each entry should reference the governing Migration Rule (`RULE-XXX`) and/or
task (`TASK-XXX`) where applicable, per `IMPLEMENTATION_GUIDE.md`.

## [Unreleased]

- **TASK-011 DONE — RULE-002: Replace EndConversation node.** Added
  `ReplaceEndConversationStep` (`src/modules/transformation/steps/`), registered in
  `build_transformation_pipeline` after `ApplyDaCompatibilityStep`. It iterates
  `context.customizations` (the discovered Topic-V2 topics) and, per topic, rewrites
  every `kind: EndConversation` node to `kind: CancelAllDialogs` (End All Topics)
  in the topic's `data` YAML — a node-anchored line substitution that preserves the
  list-item prefix, indentation, node ids, and all other logic (no YAML round-trip,
  so untouched topics stay byte-identical). Edits are staged on the `WritebackPlan`
  (chaining-aware via `target_for`), so a topic with no EndConversation node
  produces no write. `supported_modes=("READONLY","WRITEBACK")`. Added unit tests
  (pure transform + step wiring + chaining) and a golden test
  (`tests/golden/test_replace_end_conversation_golden.py`).

- **TASK-007 DONE — Output pipeline validation + generic Dataverse writeback +
  report rendering.** Replaced the postprocessing pass-through with
  `ValidateMigration`, `Writeback`, and `GenerateMigrationReport` steps. The
  Writeback step consumes the already-coalesced/no-op-guarded
  `context.pending_writes` list and maps each entry directly to
  `DataverseClient.update(entity_set, record_id, changes)` in WRITEBACK mode only;
  READONLY is skipped by `MigrationPipelineStep` mode-gating. When
  `context.preferred_solution` is set, Writeback passes the generic
  `MSCRM.SolutionUniqueName` per-request header into the Dataverse client, which
  now supports optional update headers without embedding ESS-specific logic.
  `GenerateMigrationReport` renders `migration_report.md` via
  `Reporter(logger.session_manager).render(context)`, preserving the two-file
  session bundle.

- **TASK-017 DONE — Writeback plan (coalescing + meaningful-change guard).** Added
  `WritebackPlan` / `WritebackTarget`
  (`src/modules/transformation/models/writeback_plan.py`), the shared accumulator
  that every Transformation step now stages its edits on instead of appending to a
  flat list. Keyed by `(entity_set, record_id)`, it gives **coalescing** (one PATCH
  per record even when multiple steps/rules touch it), **chaining**
  (`target.get()` returns the working value so rules compose on the same field),
  and a **meaningful-change guard** (`pending_writes` derives by diffing working vs
  original, so an unchanged value produces no write — no needless unmanaged
  `Active` overlay over a clean managed base). `MigrationContext.pending_writes` is
  now a read-only property deriving from `context.writeback`, so TASK-007's Output
  contract is unchanged. Refactored `ApplyDaCompatibilityStep` (TASK-016) to stage
  via the plan; reshaped TASK-011/012/013 (RULE-002/003/004) to consume
  `context.customizations` topics and stage via the plan (with the concrete
  pattern + golden-test expectations) so a worker can pick them up. Updated
  `PIPELINES.md` (writeback-plan contract), `CUSTOMIZATION_DISCOVERY.md` §6–7
  (incl. a future "overlay removal" note), and TASK-007/016 boundaries.

- **Customization discovery: corrected the live Dataverse calls + rewrote the
  classifier (TASK-006).** Brought `RetrieveCustomizationsStep` in line with the
  live API after end-to-end bring-up:
  - **`RetrieveDependenciesForUninstallWithMetadata` takes `SolutionId` (GUID),
    not `SolutionUniqueName`** — the base solution's unique name is resolved to
    its `solutionid` first, and `DataverseClient.call_function` now inlines a
    GUID-shaped value as an unquoted `Edm.Guid` literal (other values stay
    single-quoted strings).
  - **`msdyn_componentlayers` is fetched one component at a time**, pairing
    `msdyn_componentid` with `msdyn_solutioncomponentname` (from the dependency's
    `dependentcomponententitylogicalname`). The virtual table needs the
    solutioncomponentname and silently drops all-but-a-couple rows when ids are
    OR-ed, so the earlier chunked-OR bulk fetch was replaced with sequential
    per-id reads (each retriable on 429 via `Retry-After`).
  - **Dropped the ~1900 `msdyn_overwritetime` sentinel rule** (net-new topics read
    ~1900 too, so it was unreliable). Classification now keeps a component when it
    is **customized** (more than one layer, or a lone layer in a non-OOB solution)
    AND **migratable** (componenttype in `ALLOWED_BOT_COMPONENT_TYPES` = Topic V2,
    schemaname matches an `ESS_AGENT_SCHEMANAMES` HR/IT prefix). Added
    `OOB_ESS_SOLUTIONS` (base HR/IT + 11 extension packs), `BOT_COMPONENT_TYPE_LABELS`
    (full option-set catalog), `ALLOWED_BOT_COMPONENT_TYPES`, and
    `ESS_AGENT_SCHEMANAMES` to `service/constants.py`.
  - **Hydrated model:** kept components become `CustomizationComponent`
    (`modules/transformation/models/`) with top-level `component_id`,
    `schemaname`, `name`, `component_type`, `component_type_label`, `data`, and raw
    `layers`, so Transformation/Output consume the fields without re-parsing
    `msdyn_componentjson`. `context.component_layers` and `context.customizations`
    are now keyed by component id; added `context.customized_dependencies` (the
    raw dependency infos for the kept components).
  - Updated `02_ARCHITECTURE/CUSTOMIZATION_DISCOVERY.md` §3–4 and TASK-006.

- **CLI: consolidated `mtk start` + `mtk refresh` into a single `mtk run`.**
  Removes the start/refresh confusion. One command, two modes selected by `--dev`:
  - **customer** (`mtk run`, no `--dev`): **runs from a pristine checkout of
    `origin/main`** — `git fetch` + `git checkout -f origin/main` (detached) +
    `git clean -fd` — so the working tree exactly matches reviewed `main`
    (gitignored runtime state `.venv`/`.local`/`output/` preserved), then
    provisions runtime-only and runs. **Local commits and branches are never
    touched** (no branch is reset or deleted — earlier iterations used
    `checkout -f -B main`, which could orphan local `main` commits; the detached
    checkout fixes that). **Guarded against silent data loss:** only *uncommitted
    changes* + *untracked files* are ever discarded — it proceeds without asking
    only when the work tree is clean, otherwise it prints exactly what it will
    discard and requires an interactive `yes` (or `--yes`), and **refuses in a
    non-interactive shell**.
  - **contributor** (`mtk run --dev`): provisions runtime + dev tooling, installs
    hooks, and **skips** the reset (contributors manage their own branches).
  `--mode readonly|writeback` works with both. Updated `scripts/mtk.sh`,
  `scripts/mtk.ps1`, the monorepo-root forwarders, `.pre-commit-config.yaml`,
  the toolkit `README`,
  `REPOSITORY_STRUCTURE.md` §11a/§11b, `CODING_STANDARDS.md`, and TASK-003/009/015/016.
  Also reconciled remaining middle-stage naming "Migration Pipeline" →
  "Transformation Pipeline" across `ARCHITECTURE.md`, `PIPELINES.md`,
  `VOCABULARY.md`, `IMPLEMENTATION_GUIDE.md`.
- **TASK-003 DONE — orchestrator execution-mode selection + summary + error
  handling.** `mtk_orchestrator.main()` now parses `--mode readonly|writeback`
  (`_resolve_mode`; accepts `--mode X` / `--mode=X`, case-insensitive; invalid →
  friendly `SystemExit`) and applies it to `MigrationContext.mode` (default
  `READONLY`). On success it logs a one-line summary (mode, agent, changes/
  warnings/errors, bundle path); on failure it logs a user-friendly `LogError`
  (with the session-log path) and always closes the logger. The `mtk.sh` and
  `mtk.ps1` dispatchers parse and forward `--mode` (and `-Mode`). Added
  `_resolve_mode` / `_log_summary` unit tests.
- **Consolidated the RULE-001 / DA-compat overlap.** `ApplyDaCompatibilityStep`
  (TASK-016) and RULE-001 (TASK-010) overlapped on Template + Model Kind. Split
  them cleanly: TASK-016 keeps the foundational DA-compat *nomenclature* rewrite
  (Template, Model Kind, config — DONE); RULE-001 / TASK-010 is re-scoped to
  **only** the Agent Instructions override (TODO, future
  `OverrideAgentInstructionsStep`). Renamed RULE-001 "Override Agent Metadata" →
  "Override Agent Instructions" and its step `OverrideAgentMetadataStep` →
  `OverrideAgentInstructionsStep`; updated `MIGRATION_RULES.md`, `PIPELINES.md`,
  `DIAGNOSTICS.md`, `CODING_STANDARDS.md`, `IMPLEMENTATION_GUIDE.md`, and the
  TASKS.md index.
- **CI: run the toolkit gates + unit tests on GitHub Actions.** Added
  `.github/workflows/mtk-toolkit-ci.yml`, a dedicated workflow (path-filtered to
  `tools/ess-nextgen-migration-toolkit/**`) that runs `uv sync --frozen`, then
  `ruff check`, `ruff format --check`, `mypy src`, and `pytest` on push/PR to
  `main`. Mirrors the local pre-commit gates and adds unit-test execution in CI.
  Updated `REPOSITORY_STRUCTURE.md` §11 (Quality Gates: Pre-Commit + CI).
- **Report filename is now a `SessionManager` constructor arg; core default is
  neutral.** `core/logging/session_manager.py` no longer hardcodes
  `migration_report.md` — it takes `report_filename` (default the neutral
  `telemetry_report.md`) so the generic framework carries no product vocabulary.
  `Logger.start_session` forwards the name; the ESS orchestrator passes
  `service.constants.REPORT_FILENAME = "migration_report.md"`. The `output_root`
  base folder handling is unchanged. Gates green.
- **Reporter moved out of `core/` into the service layer.** The customer-facing
  report renderer (`Reporter`) — which hardcodes ESS report titles and the
  `migration_report.md` shape — moved from `src/core/logging/reporter.py` to
  `src/service/reporter.py`. `core/logging` now contains only the generic
  streaming Logger + SessionManager, so the framework carries no migration
  vocabulary. Updated `mtk_orchestrator.py` (imports Reporter from
  `service.reporter`), `service/__init__.py` (re-exports it), moved the Reporter
  unit tests to `tests/unit/service/test_reporter.py`, and synced the specs
  (`DIAGNOSTICS.md`, `REPOSITORY_STRUCTURE.md`, TASK-005/007). No behavioural
  change; gates green.
- **Generalized the framework base context; `ExecutionMode` moved to the domain.**
  To keep `core/` product-agnostic and extractable, the base
  `ExecutionContext` (`src/core/models/execution_context.py`) no longer defines
  or holds the migration-specific `ExecutionMode` enum — it now carries only a
  generic opaque `mode: str` plus the diagnostic collectors. The
  `ExecutionMode` StrEnum (READONLY/WRITEBACK) moved to the ESS domain at
  `src/modules/transformation/models/execution_mode.py`; `MigrationContext`
  supplies it and defaults `mode` to `READONLY`. Updated the three readers
  (`reporter.py`, `migration_step.py`, `mtk_orchestrator.py`) to read
  `context.mode`, plus tests and the specs that cited the old location
  (`REPOSITORY_STRUCTURE.md` core/models section, `DOMAIN_MODEL.md`,
  `MIGRATION_MODES.md`, `PIPELINES.md`, `AGENTS.md`, TASK-003/007/009/015). No
  behavioural change; gates green.
- **Modes model sanitized to the two technical `ExecutionMode` values
  (READONLY / WRITEBACK).** `01_PRODUCT/MIGRATION_MODES.md` is now authoritative
  on the two modes the code actually implements; the three customer-journey
  *intents* (Discover / Preview / Migrate) are kept only as journey language that
  maps onto them (Discover + Preview → `READONLY`, Migrate → `WRITEBACK`). The
  sole behavioural difference is the persistence step (`supported_modes=("WRITEBACK",)`).
  Removed the stale `DISCOVER/PREVIEW/MIGRATE` execution-mode nomenclature from
  `MIGRATION_MODES.md`, `AGENTS.md` §9, `DIAGNOSTICS.md` §10-12, `ROADMAP.md`
  stages, `PROJECT.md` §7, `CUSTOMER_JOURNEY.md`, and two code docstrings
  (`execution_context.py`, `migration_step.py`). Also sanitized
  `01_PRODUCT/MIGRATION_RULES.md` §6 (`MigrationPipeline()` →
  `TransformationPipeline()`, added the foundational `ApplyDaCompatibilityStep`
  ahead of the rule steps, cross-referenced RULE-001's template/model overlap).
- **Module rename: `migration/` → `transformation/`, plus customization-discovery
  specs.** Renamed the middle pipeline stage folder `src/modules/migration/` →
  `src/modules/transformation/` (builder `build_migration_pipeline` →
  `build_transformation_pipeline`, `migration_pipeline.py` →
  `transformation_pipeline.py`); the `MigrationContext` and `MigrationPipelineStep`
  type/file names are intentionally retained. Added a new architecture spec
  `02_ARCHITECTURE/CUSTOMIZATION_DISCOVERY.md` documenting solution resolution by
  vertical → `RetrieveDependenciesForUninstallWithMetadata` → `msdyn_componentlayers`
  → the ~1900 sentinel classification rule → the three idempotent DA-compatibility
  transforms. Synced `PIPELINES.md`, `REPOSITORY_STRUCTURE.md`, `SERVICES.md`,
  `INVARIANTS.md`, `VOCABULARY.md`, `IMPLEMENTATION_GUIDE.md`, both `AGENTS.md`
  nav tables, and the toolkit `README.md`. Reframed **TASK-006** (Input: agent
  config + customization discovery, ACTIVE), unblocked **TASK-007** (Output:
  applies `pending_writes`, WRITEBACK + preferred-solution targeting, TODO), and
  added **TASK-016** (Transformation: DA-compatibility rewrite / `ApplyDaCompatibilityStep`,
  ACTIVE). (TASK-006, TASK-007, TASK-016)
- **TASK-015 input-pipeline review refinements.** Consolidated environment
  prompting + MSAL authentication into `GatherInputWithAuthStep`, renamed agent
  discovery to `AgentSelectionStep`, added `GatherPreferredSolutionStep`, and
  moved shared auth/input step constants into `src/constants/auth.py`. The
  toolkit now clearly prompts for the full Dataverse environment URL and records
  the optional preferred solution up front for later writeback scenarios.
- **Super-pipeline base/product split (framework vs ESS product).** Split the
  fluent super-pipeline into a generic, product-agnostic base and the ESS
  product subclass: `StagedPipeline[TContext]` now lives in `core/pipeline/`
  (`staged.py`) as the reusable append-only N-stage composition, and
  `EssMigrationToolkit` moved to `service/` (`toolkit.py`) where it **inherits**
  `StagedPipeline` and adds the named `.input()/.migrate()/.output()` stages plus
  the "all three stages required" rule (via the `_ordered_stages()` hook).
  Consumers now import `from service import EssMigrationToolkit`. Keeps
  domain-flavoured composition out of `core/`. Updated
  `02_ARCHITECTURE/PIPELINES.md`, `03_ENGINEERING/REPOSITORY_STRUCTURE.md`, and
  TASK-002/003. (TASK-002)
- **Customer-channel method rename (clarity).** Renamed the two customer-channel
  Logger methods to be intent-revealing: `LogFancy` → **`LogChange`** (records a
  successful transformation → `context.Changes` → `## Changes`) and
  `LogCustomer` → **`LogAdvisory`** (records a manual-review advisory →
  `context.Warnings`/`Errors`/`Logs` by `severity` → `## Warnings`). Engineer
  channel (`LogDebug`/`LogInfo`/`LogWarning`/`LogError`) unchanged. Updated
  `03_ENGINEERING/DIAGNOSTICS.md` (section 6.2 + mapping table) and TASK-005.
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
- **Source tree finalized around core, service modules, and output.**
  Moved canonical models under `src/core/models/`; renamed the Dataverse
  integration folder to `src/core/outbound/` and the concept to the Dataverse
  client; changed `services/` to singular `service/`; introduced
  `src/service/modules/` for preprocessing, migration, and postprocessing;
  relocated generated output to `output/session-<timestamp>/`
  (later refined to the two-file session bundle); and updated the architecture
  spec index to use
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

- **TASK-004 — Typed Dataverse Web API client.** Implemented
  `src/core/outbound/dataverse_client.py` with per-request token acquisition,
  required OData headers, GET-only retry/backoff, `@odata.nextLink`
  pagination, HTTPS validation, and typed outbound exceptions. Added unit tests
  for token acquisition, pagination, retry behavior, non-retried writes, and
  error mapping. (`TASK-004`)

### Changed

- (nothing yet)

### Fixed

- (nothing yet)
