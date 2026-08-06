# Planner — Phase 5: Generate the theoretical eval (hand off to the eval skill)

The moment the plan is authored (Phases 1–4 done — tasks emitted and assigned),
automatically produce a **first, theoretical evaluation** from the **scenarios the
sponsor chose**, before anything is built. This turns the sponsor's intent into
concrete acceptance tests up front, so they can see what "good" looks like.

## Ownership — the planner does not own the eval skill

The planner **only invokes** the eval skill and hands it the scenarios. It does
**not** author eval content, does **not** reimplement eval logic, and does **not**
edit any eval files. Generating the tests is the eval skill's job
(`src/skills/evaluations/create/SKILL.md`); the planner just orchestrates the
hand-off (SKILL.md: "orchestrates; never re-implements").

## What "theoretical" means

There is no built agent or topics yet (greenfield), so this eval is grounded in
the **scenarios captured in the plan** — not in topic trigger phrases. It answers:
*for each scenario the sponsor picked, what should an employee be able to ask, and
how should the agent respond?* The later **Generate evaluation tests** task in the
plan is the *topic-driven* eval the eval author runs once topics exist — this
Phase-5 eval is the *scenario-driven* seed that precedes it. The task list is
unchanged; this phase just seeds it.

## Steps

1. **Read the scenarios off the plan.** Run `python scripts/planner/cli.py summary`
   (or read the plan context). The inputs are:
   - the Context entries in the **`scenario`** group (e.g. `hr-knowledge`,
     `hr-ticketing`) — the scenario areas in scope;
   - the **`scenarioCapability`** group — the **enabled scenarios per category**
     (e.g. `hr-ticketing.create-ticket` → "Create HR ticket") the interview
     captured. **These topic-level scenarios are the unit you write golden prompts
     for** — one or more prompts per enabled scenario, not just one per category;
   - the sponsor's **`jtbd`** and **`objective`**, and the success measure
     (`businessGoals`);
   - the target system per scenario — the **`system.*`** entries (e.g.
     `system.hr-ticketing` → ServiceNow HRSD) — for integration framing;
   - **`persona`** and **`market`** for tone/context.

2. **Tell the sponsor, in plain language, what's about to happen** — e.g. *"I'll
   turn the scenarios you picked into a first set of evaluation tests, so you can
   see what 'good' looks like before we build."* Never mention skills, files, the
   CLI, or command names to the sponsor.

3. **Invoke the eval skill, seeded with the plan's scenarios.** Read
   `src/skills/evaluations/create/SKILL.md` and follow it, but supply the plan's
   **scenarios as the source of truth in place of built topics** (there are none
   yet): for each scenario, generate scenario-based Topic-Triggering-style tests
   (representative employee prompts + expected behaviour), and where a scenario
   targets an external system (`system.*`), the matching integration-data cases.
   Hand it:
   - the scenario list (ids + display names) **and the enabled scenarios per
     category** (`scenarioCapability`) from the plan,
   - the sponsor's jtbd / objective / success measure,
   - the target system per scenario,
   - persona + market.

   **Run it generate-only.** Because there is no environment or built agent at
   planning time, produce the test sets into the local eval workspace and **stop
   before the Dataverse push** — do not push. (The topic-driven run pushes later.)

4. **Summarise for the sponsor** — how many scenarios were covered — and set
   expectations: this is a **first, theoretical** eval; it will be **refined and
   run against the real agent later**, which is the plan's *Generate evaluation
   tests* task, once the topics are built.

## Do / don't

- **Do** hand the eval skill the **scenarios** — that is the whole point of a
  theoretical eval.
- **Do** keep it generate-only at planning time (no environment yet → no push).
- **Don't** author eval YAML yourself or change the eval skill — you are invoking
  it, not owning it.
- **Don't** block plan creation on the eval. If in this build the eval skill
  strictly needs a built agent/topics and cannot run theoretically, say so plainly
  and note the eval will instead be produced by the *Generate evaluation tests*
  task — the plan is still complete. Then continue.

## Relationship to the "Generate evaluation tests" task

| | When | Grounded in | Push |
|---|---|---|---|
| **Phase 5 (here)** | plan authored (planning time) | the sponsor's **scenarios** | generate-only |
| **Generate evaluation tests task** | run time, after topics built | the built **topics** | pushes to Dataverse |

Phase 5 is the acceptance-tests **seed**; the task is the topic-driven **refine +
run**. Do not remove or duplicate the task — this phase precedes it.
