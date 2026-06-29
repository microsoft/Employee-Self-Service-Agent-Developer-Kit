# MIGRATION_RULES.md

# ESS NextGen Migration Toolkit — Migration Rules
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the canonical business migration rules implemented by the ESS NextGen Migration Toolkit.
>
> A Migration Rule specifies how a Custom Engine Agent (CA) construct is transformed, overridden, preserved, validated, or deprecated during migration to Declarative Agents (DA).
>
> Every Migration Rule maps directly to exactly one Pipeline Step.
>
> This document is intentionally a living specification and will evolve as additional MCS constructs become supported.

---

# 1. Migration Philosophy

The migration toolkit prioritizes **customer customization preservation** over aggressive automated conversion.

The toolkit shall preserve customer-authored assets wherever technically feasible.

Unless explicitly required for correctness, the migration toolkit shall never:

* Delete customer-authored components.
* Delete customer-authored business logic.
* Remove customer metadata.

Instead, unsupported constructs shall be handled using one of the following migration strategies.

| Strategy | Description                                                                              |
| -------- | ---------------------------------------------------------------------------------------- |
| Replace  | Replace an unsupported construct with a supported DA equivalent.                         |
| Override | Replace metadata or configuration with the DA equivalent while preserving the component. |
| Disable  | Preserve the component but prevent execution until manually reviewed.                    |
| Validate | No transformation required. Verify compatibility only.                                   |

This philosophy ensures migrations remain deterministic, transparent, and safe.

---

# 2. Rule Lifecycle

Every Migration Rule progresses through the following lifecycle.

```text
Discovered

↓

Analysed

↓

Specified

↓

Ready

↓

Implemented

↓

Validated
```

---

# 3. Rule Status

| Status       | Meaning                                      |
| ------------ | -------------------------------------------- |
| Ready        | Fully specified and ready for implementation |
| Implemented  | Pipeline Step implemented                    |
| Partial      | Requires manual review                       |
| Blocked      | Waiting on MCS platform support              |
| Out of Scope | Intentionally excluded                       |
| Deprecated   | No longer applicable                         |

---

# 4. Rule Categories

Migration Rules are organized into:

* Agent Metadata
* Topic Triggers
* Conversation Nodes
* AI Nodes
* Runtime Configuration
* Power Platform
* Validation

---

# 5. Rule Template

Every Migration Rule follows the same structure.

```text
Rule ID

Name

Category

Migration Strategy

Status

Priority

Source Component

Target Component

Pipeline Step

Motivation

Preconditions

Transformation

Validation

Failure Handling

User Guidance

References
```

---

# 6. Pipeline Mapping

Every Migration Rule maps directly to one Pipeline Step.

```python
MigrationPipeline()

    .use(OverrideAgentMetadataStep())

    .use(ReplaceEndConversationStep())

    .use(HandleOnActivityTopicStep())

    .use(HandleGeneratedResponseTopicStep())

    .use(ValidateSupportedComponentsStep())

    .use(...)
```

Adding a new migration capability should normally require:

* One new Migration Rule
* One new Pipeline Step
* Unit Tests
* Golden Tests

Framework modifications should rarely be required.

---

# RULE-001

## Name

Override Agent Metadata

### Category

Agent Metadata

### Migration Strategy

Override

### Status

Ready

### Priority

P0

### Pipeline Step

`OverrideAgentMetadataStep`

### Motivation

Declarative Agents require updated metadata and configuration compared to Custom Engine Agents.

These updates are deterministic and can safely overwrite package metadata.

### Preconditions

* Agent component exists.

### Transformation

Override the following metadata using the Declarative Agent package values:

* Runtime Provider
* Template
* AI Model Kind
* Agent Instructions (Overview Page)

The current implementation intentionally replaces existing Agent Instructions with the Declarative Agent instructions.

Future enhancements may introduce semantic merge capabilities when supported.

### Validation

* Runtime Provider updated.
* Template updated.
* AI Model Kind updated.
* Agent Instructions updated.
* Agent remains valid.

### Failure Handling

Abort migration.

---

# RULE-002

## Name

Replace EndConversation Node

### Category

Conversation Node

### Migration Strategy

Replace

### Status

Ready

### Priority

P0

### Source Component

EndConversation Node

### Target Component

CancelAllDialogs (End All Topics)

### Pipeline Step

`ReplaceEndConversationStep`

### Motivation

Declarative Agents do not support the EndConversation node.

ESS has validated that replacing EndConversation with CancelAllDialogs preserves the expected runtime behavior.

### Preconditions

* Topic contains one or more EndConversation nodes.

### Transformation

For every EndConversation node:

* Replace the node type with CancelAllDialogs (End All Topics).
* Preserve node connectivity.
* Preserve node metadata where applicable.

### Validation

* No EndConversation nodes remain.
* Topic graph remains valid.
* Conversation termination behavior remains correct.

### Failure Handling

Abort migration.

---

# RULE-003

## Name

Handle OnActivity Topic

### Category

Topic Trigger

### Migration Strategy

Disable

### Status

Ready

### Priority

P0

### Source Component

OnActivity Topic

### Target Component

Disabled Topic

### Pipeline Step

`HandleOnActivityTopicStep`

### Motivation

OnActivity topics are unsupported in Declarative Agents.

Customer implementations may contain arbitrary business logic which cannot be migrated automatically without changing runtime semantics.

### Preconditions

* Topic trigger type is OnActivity.
* The topic is not already migrated. A topic that is already disabled **and**
  whose title is already prefixed with `[DEPRECATED]` is considered already
  migrated and shall be skipped (idempotency — INVARIANT MIG-005).

### Transformation

The migration pipeline shall:

* Disable the topic.
* Prefix the topic title with the following marker, **only if the title is not
  already prefixed** (the prefix shall never be applied more than once):

```text
[DEPRECATED]
```

* Preserve all existing topic logic.
* Preserve all nodes.
* Preserve all expressions.
* Add a migration warning.

### Validation

* Topic is disabled.
* Topic title begins with `[DEPRECATED]`.
* Business logic remains unchanged.

### Failure Handling

Continue migration.

Generate warning.

### User Guidance

Review the deprecated topic.

Where appropriate, migrate the business logic into an OnConversationStart topic.

If this is not possible, redesign the scenario using supported Declarative Agent capabilities.

---

# RULE-004

## Name

Handle OnGeneratedResponse Topic

### Category

Topic Trigger

### Migration Strategy

Disable

### Status

Ready

### Priority

P1

### Source Component

OnGeneratedResponse Topic

### Target Component

Disabled Topic

### Pipeline Step

`HandleGeneratedResponseTopicStep`

### Motivation

The OnGeneratedResponse trigger has no Declarative Agent equivalent.

Deleting customer customizations is contrary to the migration philosophy.

Instead, preserve the implementation while preventing execution.

### Preconditions

* Topic trigger type is OnGeneratedResponse.
* The topic is not already migrated. A topic that is already disabled **and**
  whose title is already prefixed with `[DEPRECATED]` is considered already
  migrated and shall be skipped (idempotency — INVARIANT MIG-005).

### Transformation

The migration pipeline shall:

* Disable the topic.
* Prefix the topic title with the following marker, **only if the title is not
  already prefixed** (the prefix shall never be applied more than once):

```text
[DEPRECATED]
```

* Preserve all topic logic.
* Preserve all nodes.
* Generate a migration warning.

### Validation

* Topic is disabled.
* Topic title is updated.
* Topic logic remains intact.

### Failure Handling

Continue migration.

Generate warning.

### User Guidance

Review the topic.

If required, reimplement the behavior using supported Declarative Agent constructs.

Future platform capabilities may allow automatic conversion.

---

# RULE-005

## Name

Validate Supported Components

### Category

Validation

### Migration Strategy

Validate

### Status

Ready

### Priority

P0

### Pipeline Step

`ValidateSupportedComponentsStep`

### Motivation

Components already supported by Declarative Agents should remain unchanged.

The toolkit verifies compatibility without modifying customer behavior.

### Transformation

No transformation.

### Validation

Verify all supported components remain valid after migration.

### Failure Handling

Abort migration if validation fails.

---

# 7. Future Rules

Additional Migration Rules will be introduced as platform support evolves.

Examples include:

* IncludeSelectedTopics
* InvokeAIBuilderModelAction
* ConversationHistoryNode
* SearchAndSummarizeContent
* AnswerQuestionWithAI
* RecognizeIntent
* TransferConversationV2
* OnUnknownIntent
* OnPlanComplete
* OnEscalate
* File Upload
* Custom Entities
* Connected Agents

These remain **Blocked**, **Partial**, or **Out of Scope** until migration behavior is formally defined.

---

# 8. Traceability

Every Migration Rule maps directly to implementation artifacts.

| Artifact       | Convention                   |
| -------------- | ---------------------------- |
| Migration Rule | RULE-00X                     |
| Pipeline Step  | `<RuleName>Step`             |
| Unit Test      | `test_<rule_name>_step.py`   |
| Golden Test    | `test_<rule_name>_golden.py` |
| Task           | TASK-XXX                     |
| Changelog      | Rule ID reference            |

This provides complete traceability from business requirement through implementation, testing, and release history.

---

# 9. Specification Dependencies

**Consumes**

* CUSTOMER_JOURNEY.md
* DOMAIN_MODEL.md
* PIPELINES.md

**Referenced By**

* TASKS.md
* TESTING.md
* CHANGELOG.md

This document is the authoritative business specification for every Pipeline Step implemented by the ESS NextGen Migration Toolkit.
