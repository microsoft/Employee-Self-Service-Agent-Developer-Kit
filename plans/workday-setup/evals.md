# Plan: Workday evals (per-skill)

Set up evaluation test sets for the Workday functionality being enabled. Part of
[Workday Setup](./README.md).
**Depends on:** [`skill-5-install-workday-extension-pack`](./skill-5-install-workday-extension-pack.md)
and [`skill-6-create-new-topic`](./skill-6-create-new-topic.md) (topics/extension pack must exist).

## Approach (per-skill)

- **OOTB baseline eval set** for the Workday topics shipped by the extension pack.
- **`create-new-topic` auto-generates a matching eval set** for each new topic it creates,
  so coverage grows with customization.
- Reuse the existing **`src/skills/evaluations/create`** pipeline (checkpoint → write `.mcs.yml`
  → scan → dry run → push → verify) and the starter patterns in
  `src/examples/ess-samples/ESSEvaluationSamples/StarterTestSets/`.
- **Output location:** generated test sets are written as `.mcs.yml` files under
  **`my/agents/{slug}/evaluations/`** (the working-copy path the create/update/delete skills
  already use), following the existing naming convention **`{set-name}-{short-slug}.mcs.yml`**.
- **Topic-inventory discovery** uses the same onboarding/discover logic skill-2 relies on
  (`src/skills/onboarding` + `scripts/discover.py`) to enumerate the installed solution's topics
  — never a hardcoded list.

## OOTB Workday coverage (derived, not hand-listed)

**Enumerate the baseline from the installed solution's actual topics / template configs**
(the official OOTB template set), not a hardcoded list — so coverage tracks the pack as it
evolves and never drifts. (Note: *Request Time Off* is the **custom** example built in
[`skill-6`](./skill-6-create-new-topic.md), not an OOTB topic — don't bake it into the baseline.)

- Generate **Topic Triggering** tests (trigger phrases + paraphrases + negative cases) for
  each discovered OOTB topic — reliable trigger/shape smoke tests.
- **Integration Data** tests need **tenant-specific expected values**, so they can't be fully
  auto-generated from topics alone. Treat OOTB integration tests as **shape** checks by
  default; for **data-correctness**, require a sanitized test user / golden fixture with known
  expected field values (don't assert on generic placeholders like "Employee ID").

## `create-new-topic` integration

- When `create-new-topic` finishes, generate a topic-triggering (and, if it calls Workday,
  integration-data) eval set for the new topic, grouped under the appropriate area.

## Acceptance criteria

- A baseline Workday eval set exists and pushes cleanly for the OOTB topics, **derived from
  the installed solution's topic inventory** (not a hardcoded list).
- Creating a new Workday topic yields a matching eval set without a separate manual step.
- Data-correctness tests assert against a sanitized golden fixture, not generic placeholders.

## Out of scope

- Non-Workday eval categories beyond what the existing pipeline already produces.
