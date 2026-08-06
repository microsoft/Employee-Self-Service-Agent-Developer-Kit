# Eval-Driven Topic Maker: Dev Plan

**Owner:** Srikanth - topic generation  
**Partner:** Nkem - Playwright runtime validation  
**Status:** Phase 1 create and update implemented; update live validation pending

## Objective

Create or update simple ESS topics from an approved evaluation scenario and use
the same scenario to prove that the topic works.

```text
Eval scenario -> Generate topic and evals -> Validate -> Run in Playwright -> Pass or fail
```

Today, topic creation and evaluation are separate. This work connects them so
that expected behavior is defined before the topic is created.

## MVP scope

### Phase 1: Simple topics

Support topics that do not call an external system:

- Informational responses
- Clarification
- Routing
- Handoff

### Deferred to a separate PR

Workday, ServiceNow, SAP, connector-backed, and flow-backed topics remain on
their existing create and update paths. Eval-driven integration support,
template configurations, connector validation, and backend fixtures are Phase
2 work.

## Technical approach

Reuse the current topic-creation and evaluation capabilities. Do not build a new
generation engine.

The new flow will:

1. Read and validate a structured eval scenario.
2. Check that required content and dependencies are available.
3. Generate native Copilot Studio eval files.
4. Create or update the simple topic.
5. Produce a machine-readable runtime manifest for Playwright.
6. Run existing static validation.
7. Return runtime pass/fail results for each required eval.

## Current implementation status

| Done | Remaining |
|------|-----------|
| `/create` routes simple topic requests, scenario files, and eval files to the eval-driven flow. | Exercise `/update` against a real extracted agent. |
| Integration create requests preserve the existing topic-create path. | Connect the runtime manifest to Nkem's Playwright pipeline. |
| `/update` routes simple topics to an eval-driven update flow and preserves the legacy integration path. | Consume and display Playwright pass/fail results. |
| Plain requests and native evals are normalized into an approvable scenario contract. | Run the Phase 1 create and update pilots. |
| Scenario validation is limited to Phase 1 topic types. | Run the Phase 1 create and update pilots. |
| Approved scenarios generate native single-turn and multi-turn eval files. | Add fixes discovered during live-agent testing. |
| A runtime manifest links the topic and every required eval. | Finalize the Playwright result handoff. |
| Focused automated tests cover validation, routing, materialization, traceability, and stale-file cleanup. | Add fixes discovered during live-agent and runtime testing. |

## Work plan

| Milestone | Work | Exit criteria | Estimate |
|-----------|------|---------------|----------|
| 1. Finalize contracts | Agree on the eval-scenario schema, supported eval categories, Playwright runtime manifest, and result format. | PM, topic-generation owner, and runtime owner approve the contracts. | 1 week |
| 2. Build Phase 1 generator | Validate scenarios and generate simple topics, native eval files, and the runtime manifest without interactive discovery. | A simple-topic scenario produces valid and traceable artifacts. | 2 weeks |
| 3. Connect runtime validation | Pass the runtime manifest to Playwright and return clear results for required evals. | A Phase 1 topic runs end to end and reports pass or fail. | 1-2 weeks |
| 4. Harden and pilot | Add automated tests, failure reporting, telemetry, documentation, and pilot fixes. | Phase 1 create and update pilots meet the completion criteria below. | 1 week |

**Planning estimate:** 5-6 weeks for one primary engineer, with runtime work
completed in parallel where possible.

## Engineering backlog

| Priority | Work item | Owner |
|----------|-----------|-------|
| P0 | Finalize and version the eval-scenario schema. | Srikanth + PM |
| P0 | Define the Playwright runtime-manifest and result contracts. | Srikanth + Nkem |
| P0 | Add scenario validation with clear error messages. | Srikanth |
| P0 | Convert scenario evals into native Copilot Studio eval files. | Srikanth |
| P0 | Add a scenario-driven entry point to the existing topic generator. | Srikanth |
| P0 | Generate a traceable runtime manifest with required evals. | Srikanth |
| P0 | Read the manifest and return structured runtime results. | Nkem |
| P0 | Complete the Phase 1 end-to-end golden path. | Srikanth + Nkem |
| P1 | Add dependency gates for missing approved content. | Srikanth |
| P1 | Run a pilot and fix reliability issues. | Engineering |

## Ownership

| Area | Owner |
|------|-------|
| Eval-scenario schema and validation | Srikanth |
| Topic and eval generation | Srikanth |
| Runtime manifest generation | Srikanth |
| Playwright execution and runtime results | Nkem |
| Scenario selection and product acceptance | PM |
| Schedule, staffing, and risk management | EM |

## Dependencies and decisions

The following must be confirmed before implementation:

1. Use the existing live-agent topic generator as the MVP base.
2. Use YAML for the eval-scenario contract.
3. Agree on the exact Playwright input and result formats.
4. Select one Phase 1 create and one Phase 1 update golden scenario.

## Completion criteria

The MVP is complete when:

- Invalid or unsupported scenarios stop before topic generation.
- A valid scenario generates the topic, native evals, and runtime manifest.
- Every generated artifact can be traced to the source scenario.
- Existing static validation passes.
- Missing dependencies produce a clear blocker and next action.
- Playwright reports results for every required eval.
- A topic is not marked complete when a required eval fails.
- The Phase 1 golden scenarios pass end to end.
- A Phase 1 update modifies the existing topic and creates or refreshes only
  scenario-owned evals.
- Existing interactive topic creation continues to work.

## Key risks

| Risk | Mitigation |
|------|------------|
| Topic generation and Playwright use different expectations. | Generate both outputs from the same approved scenario and preserve eval IDs. |
| The existing generator is tightly coupled to user interaction. | Add a thin scenario adapter and reuse current generation logic. |
| Integration complexity delays Phase 1. | Keep integrations on the legacy paths and deliver them in a separate PR. |
| Scope expands to every topic type. | Keep the Phase 1 topic-type allowlist explicit. |
