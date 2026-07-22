# PIPELINES.md

# ESS NextGen Migration Toolkit — Pipeline Framework Specification
**Status:** Draft v2.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the Pipeline Framework used by the ESS NextGen Migration Toolkit.
>
> The Pipeline Framework provides a deterministic, extensible execution engine for migration workflows.
>
> Business transformations are implemented as independent, strongly-typed Pipeline Steps that are composed into executable Pipelines.
>
> The framework itself is completely independent of ESS-specific migration logic.

> **The toolkit is a super-pipeline (v2.0)**
>
> The product itself *is* a single deterministic, fluent super-pipeline composed
> of three independently-extensible **stage pipelines**, each responsible for a
> single concern:
>
> ```
> Input Pipeline          (src/modules/preprocessing/)
>       ↓
> Transformation Pipeline (src/modules/transformation/)
>       ↓
> Output Pipeline         (src/modules/postprocessing/)
> ```
>
> The composition is expressed fluently through `ChainedPipeline` (the generic
> super-pipeline in `core/pipelines/`), composed directly by the orchestrator:
>
> ```python
> ChainedPipeline[MigrationContext]()
>     .add(build_input_pipeline(logger))
>     .add(build_transformation_pipeline(logger))
>     .add(build_output_pipeline(logger))
> ```
>
> **Each stage receives the output of the previous stage and operates over the
> shared `MigrationContext`.** The Input Pipeline builds and enriches the
> context (including the homogeneous keyed `ComponentSet` of customer-owned
> components); the Transformation Pipeline applies deterministic business
> transformations to it; the Output Pipeline validates, persists, and reports on
> it.
>
> **The Migration Orchestrator is only the composition root.** It builds the
> chained pipeline, configures the execution mode (READONLY / WRITEBACK),
> executes it, and returns the resulting reports and diagnostics. Orchestration
> concerns are kept strictly separate from pipeline behaviour — the orchestrator
> is *not* the primary abstraction; the chained pipeline is.
>
> **Typed framework foundation.** The reusable framework is generic —
> `Pipeline[TInput, TOutput]` and `PipelineStep[TInput, TOutput]` — so the
> Builder can type-thread steps and support type-changing steps where genuinely
> needed. The generic super-pipeline composition is likewise framework, not
> product: `ChainedPipeline[TContext]` (in `core/pipelines/`) composes an ordered
> sequence of context-preserving stage pipelines and runs them left to right,
> with no ESS or domain naming. The orchestrator composes `ChainedPipeline`
> directly with `.add()` — no subclass needed. The
> three ESS stage pipelines instantiate the generic `Pipeline` foundation over
> the shared `MigrationContext` (`Pipeline[MigrationContext, MigrationContext]`),
> which threads through the whole chained pipeline. (The generic `TInput, TOutput`
> signature is the analogue of the C# `HeterogenousPipelineStepComputeUnitBase
> <TInput, TOutput>`; a stage pipeline is the analogue of
> `KeyedComputeUnitBase<...>`. C# runtime concerns — Autofac keyed registration,
> `floorEpoch`/`currentEpoch` versioning, per-step `Equals`/`GetHashCode` — are
> intentionally out of scope and not ported.)

---

# 1. Purpose

The Pipeline Framework is responsible for coordinating migration execution.

Rather than embedding migration logic inside procedural scripts, the framework executes a sequence of independently developed Pipeline Steps against a shared MigrationContext.

This provides:

- Deterministic execution
- Extensibility
- Testability
- Reusability
- Separation of concerns

---

# 2. Design Principles

## PIPE-001

Pipeline execution is deterministic.

Given identical inputs, identical outputs must always be produced.

---

## PIPE-002

Pipeline Steps are independent.

Each step performs exactly one logical responsibility.

---

## PIPE-003

Pipeline Steps are composable.

Steps may be added, removed, or reordered without modifying the Pipeline Engine.

---

## PIPE-004

The Pipeline Engine contains no migration logic.

---

## PIPE-005

Business transformations belong exclusively to Migration Steps.

---

## PIPE-006

Execution Mode selection belongs to Pipeline Steps, not the Pipeline Engine.

---

## PIPE-007

Pipeline execution is fail-fast.

A failed step terminates the pipeline unless explicitly configured otherwise.

---

## PIPE-008

Pipelines and Pipeline Steps are strongly typed.

The framework foundation is generic — `Pipeline[TInput, TOutput]` and
`PipelineStep[TInput, TOutput]`. The Pipeline Builder type-threads adjacent
steps so that the output type of one step is the input type of the next; an
incompatible composition is a construction-time error, not a runtime error. The
three ESS stage pipelines instantiate this foundation over the shared
`MigrationContext`.

---

## PIPE-009

A stage pipeline threads the shared `MigrationContext`.

Within a stage, each step receives the `MigrationContext` produced by the prior
step, enriches it, and passes it on. A step may Read, Enrich, or Validate the
context; a step may never replace the context with an unrelated type nor smuggle
state outside it. The context is the only object shared between steps.

---

## PIPE-010

The toolkit is a super-pipeline of three stages.

Migration executes as **Input → Migration → Output**, each a stage pipeline over
the shared `MigrationContext`. The Migration Orchestrator is only the
composition root: it builds the super-pipeline, configures the execution mode,
executes it, and returns reports and diagnostics. A stage never reaches into
another stage's steps.

---

# 3. Pipeline Architecture

```
Migration Orchestrator
          │
          ▼
     Pipeline Engine
          │
          ▼
     Pipeline Builder
          │
          ▼
Registered Pipeline Steps
          │
          ▼
Migration Context
```

The Pipeline Engine coordinates execution.

Pipeline Steps implement behavior.

---

# 4. Core Components

The Pipeline Framework consists of six primary components.

```
Pipeline Engine

↓

Pipeline Builder

↓

Pipeline Step

↓

Pipeline Registry

↓

Pipeline Context

↓

Pipeline Result
```

---

# 5. Pipeline Engine

## Purpose

Execute a configured Pipeline.

---

## Responsibilities

- Validate pipeline
- Execute Pipeline Steps
- Maintain execution order
- Propagate failures
- Record diagnostics
- Produce Pipeline Result

---

## Owns

Execution lifecycle.

---

## Never

- Transform components
- Call Dataverse
- Perform persistence

---

# 6. Pipeline Builder

## Purpose

Construct executable pipelines.

---

## Responsibilities

- Register Pipeline Steps
- Configure execution order
- Type-thread adjacent steps (`step[n].output == step[n+1].input`)
- Validate pipeline configuration

---

## Fluent API

Each stage pipeline is built fluently over the shared `MigrationContext`. The
generic Builder (`Pipeline.builder(name, *, input_type=...)` → `Pipeline[TInput, TOutput]`)
type-threads every `.use(step)`; the ESS stages instantiate it as
`Pipeline[MigrationContext, MigrationContext]`, so each step reads the context
produced by the prior step and returns the enriched context.

```python
# Input Pipeline (src/modules/preprocessing/) — authenticates, selects the ESS
# Agent, verifies the ALM preferred solution, and discovers customer
# customizations, enriching the canonical MigrationContext.
input_pipeline = (
    InputPipeline()
        .use(GatherInputWithAuthStep())          # first 3 steps are fixed-order
        .use(AgentSelectionStep())
        .use(GatherALMCustomerInputStep())       # GetPreferredSolution cross-check
        .use(RetrieveAgentConfigurationStep())   # bot record + gpt.default component
        .use(RetrieveCustomizationsStep())       # deps + componentlayers classification
)

# Transformation Pipeline (src/modules/transformation/) — one Step per rule.
transformation_pipeline = (
    TransformationPipeline()
        .use(ApplyDaCompatibilityStep())         # CA→DA model/template/config rewrite
        .use(OverrideAgentMetadataStep())        # RULE-001
        .use(ReplaceEndConversationStep())       # RULE-002
        .use(HandleOnActivityTopicStep())        # RULE-003
        .use(HandleGeneratedResponseTopicStep()) # RULE-004
)

# Output Pipeline (src/modules/postprocessing/) — validate, persist, and render
# the two-file session bundle.
output_pipeline = (
    OutputPipeline()
        .use(ValidateMigration())
        .use(Writeback())                    # WRITEBACK mode only
        .use(GenerateMigrationReport())      # renders customer-facing migration_report.md
)
# session.log is streamed live by the framework Logger across all stages —
# it is not a pipeline step.
```

### The super-pipeline

The product itself is a single fluent chained pipeline that composes the three
stages. Each stage receives the output of the previous stage over the shared
`MigrationContext`. The orchestrator composes `ChainedPipeline` directly — no
subclass needed:

```python
toolkit = (
    ChainedPipeline[MigrationContext]()
        .add(input_pipeline)
        .add(transformation_pipeline)
        .add(output_pipeline)
)

result = toolkit.run(context)   # context.mode set (READONLY | WRITEBACK)
```

The Builder creates immutable executable pipelines. The **Migration Orchestrator
is only the composition root** — it assembles the super-pipeline above,
configures the execution mode, executes it, and returns the reports and
diagnostics (see section 16). Adding a future migration capability normally
requires only a new Migration Rule, a new Pipeline Step, and its registration in
the Transformation Pipeline — the surrounding framework is unchanged.

> **Note — where the C# reference maps.** A stage pipeline
> (`Pipeline[TInput, TOutput]`) is the analogue of the C#
> `KeyedComputeUnitBase<...>` (a whole module compute), and
> `PipelineStep[TInput, TOutput]` is the analogue of
> `HeterogenousPipelineStepComputeUnitBase<TInput, TOutput>` (a single typed step
> compute). The C# runtime concerns — Autofac keyed registration,
> `floorEpoch`/`currentEpoch` versioning, and per-step `Equals`/`GetHashCode` —
> are intentionally **out of scope** for a batch migration tool and are not
> ported.

---

# 7. Pipeline Step

## Purpose

Encapsulate one unit of migration work.

Every Pipeline Step performs exactly one responsibility.

---

## Contract

Every Pipeline Step implements:

```python
class PipelineStep:

    name()

    description()

    supported_modes()

    can_execute(context)

    execute(context)

    validate(context)
```

---

## Responsibilities

- Read MigrationContext
- Perform one logical action
- Update MigrationContext
- Emit Diagnostics

---

## Never

- Perform unrelated work
- Modify execution order
- Call other Pipeline Steps

---

## Component Selection

A Pipeline Step targets components by inspecting the canonical `Component`
model rather than by type-specialized classes.

Each Step declares the component types it applies to and selects matching
components by filtering on `Component.ComponentType` (and, where relevant, on
trigger type — e.g. `OnActivity`, `OnGeneratedResponse`). This selection is
performed inside `can_execute(context)`:

```python
class HandleOnActivityTopicStep(PipelineStep):

    supported_modes = ("READONLY", "WRITEBACK")

    def can_execute(self, context):
        return any(
            c.ComponentType == ComponentType.TOPIC
            and c.Metadata.TriggerType == TriggerType.ON_ACTIVITY
            for c in context.Components
        )

    def execute(self, context):
        for component in context.Components:
            if (
                component.ComponentType == ComponentType.TOPIC
                and component.Metadata.TriggerType == TriggerType.ON_ACTIVITY
            ):
                ...  # transform the canonical model only
```

If `can_execute(context)` returns `False`, the Pipeline Engine skips the Step.

This keeps the framework open for extension (new Steps filter on existing
canonical models) and closed for modification (the `Component` model and
Pipeline Engine remain unchanged when new Steps are added). Component type and
trigger type constants are defined in `service/constants.py`.

---

# 8. Pipeline Registry

## Purpose

Maintain registered Pipeline Steps.

---

## Responsibilities

- Register Steps
- Resolve execution order
- Detect duplicates
- Validate configuration

---

## Registration Example

```python
registry.register(OverrideAgentMetadataStep())

registry.register(ReplaceEndConversationStep())

registry.register(HandleOnActivityTopicStep())
```

The Pipeline Engine executes registered steps.

---

# 9. Migration Context

The MigrationContext is the only object shared between Pipeline Steps.

Pipeline Steps communicate exclusively through MigrationContext.

---

## Contains

- Session
- Environment
- Agent
- Components (including the keyed `ComponentSet`)
- Migration Candidates
- Diagnostic collectors — Logs, Warnings, Errors, Changes
- Reports
- Configuration

The Diagnostic collectors (`Logs`, `Warnings`, `Errors`, `Changes`) are the
accumulation buffers that steps append to; the Output Pipeline's terminal
`GenerateMigrationReport()` step renders `migration_report.md` from them (see
DIAGNOSTICS.md section 5).

---

## Rules

Pipeline Steps may:

- Read Context
- Enrich Context
- Validate Context

Pipeline Steps may never replace the Context.

---

# 10. Execution Modes

Execution Modes are determined by the Pipeline Step.

The Pipeline Engine does not branch on execution mode.

Example

```python
class DiscoverComponents(PipelineStep):

    supported_modes = ("READONLY", "WRITEBACK")
```

Example

```python
class Writeback(PipelineStep):

    supported_modes = ("WRITEBACK",)
```

The Pipeline Engine automatically skips unsupported steps.

---

# 11. Pipeline Lifecycle

Every Pipeline execution follows the same lifecycle.

```
Build Pipeline
        │
        ▼
Validate Pipeline
        │
        ▼
Initialize Context
        │
        ▼
Execute Steps
        │
        ▼
Validate Results
        │
        ▼
Complete
```

---

# 12. Pipeline Execution Flow

```
Migration Context
        │
        ▼
Pipeline Step

↓

can_execute()

↓

execute()

↓

validate()

↓

Updated Context
```

The updated Context becomes the input to the next Pipeline Step.

---

# 13. Error Handling

Failures propagate upward.

```
Pipeline Step

↓

Pipeline Engine

↓

Migration Orchestrator

↓

User
```

Pipeline Steps never suppress failures.

---

# 14. Diagnostics

Every Pipeline Step emits diagnostics through the Diagnostics Service.

Pipeline Steps never:

- print()
- write files
- write console output

Diagnostics remain centralized.

---

# 15. Extension Points

The Pipeline Framework is designed for extension.

Supported extension points include:

## Pipeline Step

Adds business behavior.

---

## Validator

Adds additional validation.

---

## Pipeline Listener

Observes execution.

Examples:

- Timing
- Metrics
- Progress

---

## Pipeline Hook

Executes framework callbacks.

Examples:

- Before Pipeline
- After Pipeline
- Before Step
- After Step

---

# 16. Stage Pipelines and the Super-Pipeline

The toolkit is composed of three **stage pipelines**, each a `Pipeline` over the
shared `MigrationContext`.

## Input Pipeline (`src/modules/preprocessing/`)

Responsibilities

- Discover the target ESS Agent
- Retrieve migration dependencies and Solution Component Layers
- Resolve customer-owned customizations
- Load canonical Domain Models and build the keyed `ComponentSet`
- Produce the enriched `MigrationContext`

## Transformation Pipeline (`src/modules/transformation/`)

Responsibilities

- Execute Transformation Steps (one Step per rule) — deterministic business
  transformations only. The first Step, `ApplyDaCompatibilityStep`, performs the
  CA→DA model/template/config rewrite; the remaining Steps implement the
  Migration Rules (RULE-001..004).

## Output Pipeline (`src/modules/postprocessing/`)

Responsibilities

- Validate migrated artifacts
- Persist supported transformations to Dataverse (WRITEBACK mode only)
- Render the customer-facing `migration_report.md`
- (The engineering `session.log` is streamed by the Logger, not a step)

## The Super-Pipeline

The Migration Orchestrator (`src/service/mtk_orchestrator.py`) is the
**composition root** only. It assembles the three stages into the chained
pipeline, configures the execution mode, executes it, and returns the
reports and diagnostics. The orchestrator composes `ChainedPipeline` directly:

```python
ChainedPipeline[MigrationContext]()
    .add(input_pipeline)
    .add(transformation_pipeline)
    .add(output_pipeline)
```

The final outputs of the toolkit are the two files of the session bundle:

- `migration_report.md` — customer-facing (all modes; the product in
  Discover/Preview)
- `session.log` — ESS-engineer-facing diagnostics

In Migrate mode the customer environment is additionally updated. Orchestration
concerns stay strictly separate from pipeline behaviour — the super-pipeline is
the primary abstraction; the orchestrator merely builds, configures, executes,
and returns.

---

# 17. Pipeline Ownership

| Component | Owns |
|------------|------|
| Pipeline Engine | Execution |
| Pipeline Builder | Construction |
| Pipeline Registry | Registration |
| Pipeline Step | One logical operation |
| Migration Context | Shared execution state |
| Pipeline Result | Execution outcome |

---

# 18. Future Evolution

Adding new migration capabilities should typically require only:

- New Pipeline Step
- Registration with the Pipeline Builder
- Unit Tests

Framework modifications should rarely be required.

The framework is intentionally Open for Extension and Closed for Modification.

---

# 19. Traceability

**Consumes**

- ARCHITECTURE.md
- DOMAIN_MODEL.md
- SERVICES.md
- MIGRATION_MODES.md
- INVARIANTS.md

**Referenced By**

- MIGRATION_RULES.md
- DATAVERSE_CLIENT.md
- TASKS.md
- TESTING.md

The Pipeline Framework is the execution engine of the ESS NextGen Migration Toolkit.

It provides the reusable infrastructure upon which all migration behavior is implemented.
