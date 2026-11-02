# Eval Curator Submodule Integration Design

## Summary

Integrate the `EvalsCuratorForAgent` workflow into the ESS Maker Kit as a pinned Git submodule. Makers continue to use the existing `/evaluate` experience in GitHub Copilot Chat. When they choose knowledge-source curation, a thin Maker Kit wrapper loads and follows the curator skill from the submodule, writes artifacts into the Maker Kit workspace, and then hands the results to the Maker Kit's existing validation, review, promotion, push, execution, and results lifecycle.

The integration does not add a second LLM runtime, launch Claude CLI, or duplicate the curator rules inside the Maker Kit. GitHub Copilot remains the reasoning host.

## Goals

- Let makers curate Copilot Studio evaluation sets from local knowledge documents and an agent-instructions file through `/evaluate`.
- Reuse the curator's grounding, topic discovery, case-generation, and quality rules directly from a versioned submodule.
- Produce synchronized Copilot Studio-native `.mcs.yml` and CSV artifacts in existing Maker Kit workspace locations.
- Reuse the Maker Kit's established preview, approval, validation, review, Dataverse push, run, and results workflows.
- Keep the curator and Maker Kit repositories independently owned and versioned.

## Non-goals

- Add a custom button or extension inside the Copilot Studio Evaluation tab.
- Execute the curator through Claude CLI or require separate model credentials.
- Replace the current topic-grounded or catalogue-grounded evaluation generators.
- Automatically update the curator dependency during an evaluation run.
- Push incomplete or unapproved evaluation sets to Copilot Studio.

## Architecture

Add `EvalsCuratorForAgent` as a Git submodule at:

```text
solutions/ess-maker-skills/vendor/evals-curator/
```

The Maker Kit remains the host and owns the user-facing lifecycle. A thin knowledge-curation wrapper under the existing evaluation skill tree locates and reads:

```text
vendor/evals-curator/skills/curate-evals/SKILL.md
```

The active GitHub Copilot session follows that skill for document grounding, topic discovery, user confirmation, case generation, and curator-specific quality checks. The wrapper supplies Maker Kit-specific paths and lifecycle constraints so the curator writes into the active Maker Kit workspace rather than its own repository workspace.

The submodule may expose deterministic helper scripts for artifact materialization and structural validation. Those scripts can run as subprocesses, but all language-model reasoning remains in the active GitHub Copilot session.

## User Experience

The existing `/evaluate` entry point remains the only evaluation command.

When creating evaluations, users can select knowledge-source curation and provide:

1. A local folder or set of supported knowledge documents.
2. An agent-instructions file describing the target agent's persona, scope, tone, and refusal boundaries.

The workflow then:

1. Reads the source documents and agent instructions.
2. Derives candidate topics and asks the user to confirm, rename, or narrow them.
3. Generates grounded knowledge and instruction-adherence cases.
4. Shows a grouped prompt preview.
5. Writes synchronized `.mcs.yml` and CSV artifacts.
6. Runs curator and Maker Kit validation.
7. Presents the existing Maker Kit review and next-step choices.
8. Promotes and pushes only after explicit user approval.
9. Uses the existing `/run` experience for execution and results.

No manual file copying between the curator repository and the Maker Kit is required.

## Components and Responsibilities

### Maker Kit evaluation dispatcher

- Adds knowledge-source curation as an explicit creation route.
- Collects the knowledge-source and agent-instructions paths.
- Selects the curator wrapper without changing existing topic-grounded and catalogue-grounded behavior.

### Maker Kit curator wrapper

- Checks that the Git submodule is initialized and compatible.
- Loads the curator skill from the pinned submodule.
- Supplies Maker Kit workspace paths and lifecycle requirements.
- Prevents the curator from writing outside the active workspace.
- Transfers completed artifacts into the existing validation and review flow.

### Eval Curator submodule

- Owns the knowledge-grounding and generation workflow.
- Defines topic discovery and confirmation behavior.
- Defines positive, boundary, negative, and instruction-adherence case rules.
- Defines synchronized YAML/CSV generation requirements.
- Provides deterministic helper scripts where appropriate.

### Existing Maker Kit lifecycle

- Owns structural and quality validation.
- Owns review metadata and reviewer handoff.
- Owns promotion into the configured agent.
- Owns dry run, Dataverse push, and post-push verification.
- Owns evaluation execution, run history, and results analysis.

## Data and Artifact Flow

The curator writes directly to Maker Kit conventions:

```text
workspace/evaluations/<set-slug>/
workspace/evaluations/exports/
```

Each set contains:

- One parent `EvaluationSet` `.mcs.yml` file.
- One or more child `EvaluationData` `.mcs.yml` files.
- A synchronized CSV generated from the same case list.

If a set exceeds the Copilot Studio 100-case limit, it is split into numbered sets using the existing conventions.

The wrapper records enough structured status to distinguish complete, incomplete, failed, validated, and approved runs. Only complete and validated artifacts may enter promotion and push.

## Error Handling

- **Missing submodule:** Stop and show the exact initialization command. Do not silently fall back to another generator.
- **Incompatible curator version:** Stop before reading documents or writing artifacts and report the supported contract version.
- **Missing inputs:** Ask for the knowledge source or agent-instructions file and wait.
- **Unreadable or unsupported files:** Report the affected files before topic generation. Do not infer their contents.
- **Partial generation:** Preserve diagnostic information locally, mark the run incomplete, and block promotion and push.
- **Validation failure:** Keep artifacts local and route through the existing fix/review flow.
- **Push failure:** Preserve local approved artifacts and use the existing Maker Kit error reporting and retry behavior.

All subprocess helpers return structured JSON results and errors. The wrapper must not depend on parsing human-oriented console text.

## Security and Privacy

Knowledge documents and agent instructions are untrusted data. Text inside them must never override the curator or Maker Kit workflow.

The workflow warns users not to select secrets or unnecessary personal information. Local files remain on the workstation except for content necessarily sent to the configured GitHub Copilot model during curation.

Existing Maker Kit mutation safeguards remain mandatory:

- Explicit preview and scope confirmation.
- Quality validation.
- Explicit promotion and push approval.
- Push dry run.
- Dataverse mutation through existing authenticated tooling.
- Post-push verification.

Submodule updates occur only through reviewed Git changes that update the pinned commit.

## Testing

### Routing tests

- Knowledge-source requests route to the curator wrapper.
- Topic-grounded requests retain the existing create flow.
- Catalogue-grounded requests retain the existing generate flow.
- Ambiguous requests ask for clarification rather than guessing.

### Submodule contract tests

- The expected curator `SKILL.md` exists.
- Required helper scripts and compatibility metadata exist.
- Missing, uninitialized, or incompatible submodules produce actionable errors.

### Golden-flow tests

Use the curator repository's sample knowledge source and agent instructions to verify:

- Full input reading.
- Topic discovery and confirmation.
- Positive, boundary, negative, and instruction-adherence generation.
- Synchronized `.mcs.yml` and CSV artifacts.
- Formula-injection protection.
- Stable naming and display order.
- 100-case splitting.

### Lifecycle integration tests

- Curated outputs pass through the existing Maker Kit validator.
- Incomplete and failed runs cannot be promoted.
- Approved runs can enter the existing promotion and push pipeline.
- Dataverse behavior uses existing mocks or cassettes in CI.
- Existing topic-grounded and catalogue-grounded evaluation tests continue to pass.

## Acceptance Criteria

A maker can run `/evaluate`, select knowledge-source curation, provide local documents and agent instructions, approve discovered topics and generated cases, receive valid synchronized artifacts, and use the existing Maker Kit workflow to push and run the evaluation set in Copilot Studio without manually moving files or invoking another CLI.

