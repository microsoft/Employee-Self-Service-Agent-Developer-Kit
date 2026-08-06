# Eval-Scenario Format (Step 1: the eval contract)

This is the format that starts everything in the eval-driven topic maker. One
eval scenario is the eval contract for one topic. It is the artifact the maker
approves before any topic file is written. It does two jobs:

1. It drives generation. The generator reads it to create or update a simple
   topic.
2. It defines success. The evals in it become the runtime tests that prove the
   topic works. The topic is complete only after its required runtime evals pass.

This version (schemaVersion 2) is aligned to the PM's "ADK Topic Creator:
Interactions and Intended Evals" proposal. The vocabulary here maps directly to
the eval tables in that document.

A scenario is a small YAML file, authored by a PM or engineer and read by a
machine. This version supports Phase 1 topics only: informational responses,
clarification, routing, and handoff without an external-system call. See the
`examples/` folder for a complete example, and
`../../solutions/ess-maker-skills/src/skills/topics/create-eval-driven/eval-scenario.schema.json`
for the machine-checkable version used by `/create`.

## The flow this format sits in

1. The maker describes the intended employee outcome.
2. Topic Creator checks the request is supported and the required dependencies
   are available (see `dependencyChecks`).
3. Topic Creator drafts the intended evals (this file's `evals`).
4. The maker reviews and approves the eval contract.
5. Topic Creator creates or updates the topic and writes the approved eval
   files.
6. It validates, shows the diff, and requires confirmation before pushing.
7. The topic is complete only after its required runtime evals pass.

If a required dependency is missing, Topic Creator explains the blocker and the
next setup action. It does not invent the dependency or report the topic as
created.

The command supplies the operation:

- `/create` creates a new simple topic.
- `/update` edits one existing simple topic in place.

The contract does not expose an operation field to the maker. Workday,
ServiceNow, SAP, connector-backed, and flow-backed topics remain on the existing
legacy create and update paths until the Phase 2 PR.

## Fields

### Identity

| Field | Required | What it is |
|-------|----------|------------|
| `schemaVersion` | yes | Format version. `2`. |
| `id` | yes | Stable kebab-case id, e.g. `workday-request-time-off`. |
| `name` | yes | Human title. |
| `intent` | yes | The intended employee outcome, in the maker's words. |
| `topicType` | yes | `informational`, `clarification`, `routing`, or `handoff`. Inferred by the kit. |
| `phase` | yes | Must be `1`. |
| `persona` | yes | Who uses it: `employee`, `manager`, `admin`, or `support`. |
| `references` | no | One path or a list of source eval, topic, doc, or system-of-record paths. |
| `sourceContent` | for informational and guidance topics | Approved response, link, or guidance the topic must use verbatim. Its absence is a generation blocker. |

### `dependencyChecks`

Preconditions checked before generation or before push. Each has a `condition`, an
optional `blocks` (`generation` or `push`, default `generation`), and a `behavior`
describing the blocker and the next setup action.

Recommended condition values, matching the PM's blocked and unsupported cases:

| Condition | Blocks | Example |
|-----------|--------|---------|
| `missing-source-content` | generation | An informational topic with no approved response or link |
| `dev-target-unavailable` | push | The development environment or permission is unavailable |

### `evals` (the eval contract)

The intended evals the maker approves. Each row has a `category` and exactly
one trigger: `input` (single-turn), `turns` (multi-turn), or `condition` (a
non-prompt situation). Single-turn and condition rows also carry a top-level
`expectedOutput`; multi-turn rows carry the expected outcome inside each turn
instead.

| Field | Required | What it is |
|-------|----------|------------|
| `category` | yes | One of the categories in the table below. |
| `input` | one of input/turns/condition | Single-turn user prompt. |
| `turns` | one of input/turns/condition | Ordered turns; each has `input` and optional `expectedOutput`. |
| `condition` | one of input/turns/condition | A non-prompt situation, e.g. "The approved guidance is unavailable". |
| `expectedOutput` | yes for `input` and `condition` rows | The expected outcome, in plain language. Not used at the row level for `turns` rows. |
| `required` | no | Whether this eval must pass for the topic to be complete. Defaults to `true`. |
| `threshold` | no | Semantic match bar, 0 to 1. Defaults to `0.7`. |

#### Eval categories, mapped to the PM's labels

| Category | PM label(s) | Meaning |
|----------|-------------|---------|
| `directTrigger` | Direct trigger, Exact case, Complete request | Fires on a direct request and returns the right result. |
| `paraphrase` | Paraphrase | Fires on a reworded request. |
| `nonTrigger` | Non-trigger | Does not invoke this topic. |
| `clarification` | Clarification | Asks which supported option applies. |
| `missingInput` | Missing input(s) | Collects only the missing required value. |
| `correctedInput` | Corrected input | Uses a value the user corrects before confirmation. |
| `confirmation` | Confirmation | Confirms the interpreted request and submits once on confirm. |
| `cancellation` | Cancellation | User cancels or declines; no action is taken. |
| `disambiguation` | Multiple matches, Case selection | Asks the user to pick from more than one match. |
| `notFound` | Missing case, Unsupported route, Unsupported region | The requested item or route does not exist; report it without inventing. |
| `emptyOptionalField` | Empty optional field | An optional field is unavailable; return the rest without inventing a value. |
| `actionBoundary` | Action boundary, Mutation boundary | Does not claim to perform an unsupported action; routes to the supported topic when available. |
| `regression` | Regression | Existing behavior still passes after an `update`. |

#### Multi-turn and the runtime caveat

Multi-turn rows (`turns`) mirror the `conversationNumber` grouping in the repo's
multi-turn eval template. The platform's native multi-turn eval import runs
General Quality only and does not compare each turn's response, so per-turn
`expectedOutput` assertions are validated by the runtime harness (the Playwright
run), not by native semantic-compare evals. Single-turn rows are the ones that
map to native `CompareMeaning`.

## How the format feeds the later steps

- `sourceContent`, `triggers` in `evals`, and `intent` feed topic creation or
  update.
- `dependencyChecks` feed the gate that runs before generation and before push.
- `evals` become the approved eval files and the runtime tests handed to the
  Playwright run.

## Relationship to existing formats and the PM spec

Aligned with:

- The PM's "ADK Topic Creator: Interactions and Intended Evals" proposal. The
  `evals` categories map one to one to its eval tables (see the mapping above),
  and `dependencyChecks` cover its blocked and unsupported cases.
- Evaluation rows (`EvaluationData`: `input` plus `expectedOutput` plus a
  threshold). Single-turn evals copy this shape.
- The multi-turn eval template (turns grouped by `conversationNumber`).
- The sample topic request issue form's generic fields (area/ISV, scenario,
  utterances, references).

Deliberately left out (specific to the samples contribution flow):

- Request type (New vs Fix), topic folder (PascalCase under `samples/`), and
  sub-grouping (Employee / Manager / Extended). This flow creates new topics in
  a live agent's `topics/` folder, and `persona` covers the intended user.

## Open points to confirm with the team

1. YAML is the default, matching the rest of the kit. Confirm before we build
   tooling around it.
2. The eval category list is derived from the PM proposal (status: Proposed).
   Confirm it is complete, or extend it as new scenarios appear.
3. Confirm with Nkem that a runtime row (`input` or `turns` or `condition` plus
   `expectedOutput`) carries everything the Playwright harness needs.
