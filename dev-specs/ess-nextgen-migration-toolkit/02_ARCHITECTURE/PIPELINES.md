# PIPELINES.md

# ESS NextGen Migration Toolkit — Pipeline Framework Specification
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the Pipeline Framework used by the ESS NextGen Migration Toolkit.
>
> The Pipeline Framework provides a deterministic, extensible execution engine for migration workflows.
>
> Business transformations are implemented as independent Pipeline Steps that are composed into executable Pipelines.
>
> The framework itself is completely independent of ESS-specific migration logic.

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
- Validate pipeline configuration

---

## Fluent API

```python
pipeline = (
    Pipeline.builder("Migration")

        .use(DiscoverComponents())

        .use(AnalyzeOwnership())

        .use(LoadComponents())

        .use(OverrideAgentMetadataStep())

        .use(ReplaceEndConversationStep())

        .use(ValidateMigration())

        .use(Writeback())

        .build()
)
```

The builder creates immutable executable pipelines.

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

    supported_modes = [PREVIEW, MIGRATE]

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
trigger type constants are defined under `constants/`.

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
- Components
- Migration Candidates
- Diagnostics
- Reports
- Configuration

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

    supported_modes = [
        DISCOVER,
        PREVIEW,
        MIGRATE
    ]
```

Example

```python
class Writeback(PipelineStep):

    supported_modes = [
        MIGRATE
    ]
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

# 16. Pipeline Categories

The framework supports multiple Pipeline types.

## Discovery Pipeline

Responsibilities

- Discover components
- Analyze ownership

---

## Migration Pipeline

Responsibilities

- Execute Migration Steps

---

## Validation Pipeline

Responsibilities

- Validate transformed artifacts

---

## Persistence Pipeline

Responsibilities

- Persist migrated artifacts

---

## Reporting Pipeline

Responsibilities

- Generate reports

The Migration Orchestrator composes these pipelines into an execution workflow.

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
