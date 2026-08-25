# Planner — Phase 5: Preview the scenario eval (render golden prompts — don't generate)

As soon as the sponsor's **scenarios and goals** are captured, render a **preview**
of the evaluation — the golden prompts the finished agent will be judged on — so the
sponsor sees the **acceptance bar up front**, before anything is built. This is
invoked **eagerly** from the interview (Phase 2, before modelling tasks), and can be
re-shown at plan-authored time if the scope changed.

**Render-only — nothing is generated.** This preview *displays* the golden prompts in
chat. It **writes no files, creates no eval records, and pushes nothing.** It is a
picture of "what good looks like", not the eval itself. The **actual** eval is
generated later by the plan's *Generate evaluation tests* task (topic-driven), once
topics are built — that task is unchanged; this preview just shows the bar early.

## Ownership — the planner does not own the eval skill

The planner does **not** author eval content, does **not** run the eval skill's
generate/scan/push pipeline, and does **not** edit any eval files
(`src/skills/evaluations/create/SKILL.md` stays untouched). It only **renders a
preview** from the scenarios the plan already captured (SKILL.md: "orchestrates;
never re-implements"). Real generation belongs to the eval skill / the
*Generate evaluation tests* task.

## What it's grounded in

There is no built agent or topics yet (greenfield), so the preview is grounded in the
**scenarios captured in the plan** — not in topic trigger phrases. It answers: *for
each scenario the sponsor picked, what would an employee ask, and how should the agent
respond?*

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
   turn the scenarios you picked into a first set of example test prompts, so you can
   see what 'good' looks like before we build."* Never mention skills, files, the
   CLI, or command names to the sponsor.

3. **Render the golden prompts, grouped by scenario category.** For each in-scope
   category, write **2–5 natural employee prompts per enabled scenario**
   (`scenarioCapability`) — phrased the way a real employee would ask, grounded in
   `persona` / `market`; where a scenario targets an external system (`system.*`),
   include an integration-flavoured prompt. **Bias selection to the goals**
   (`objective` / `businessGoals` / `jtbd`) and **drop anything the sponsor put out
   of scope** (e.g. "no manager scenarios", "writes beyond phone/email off the
   table"). Aim for a compact set (~15–25 prompts for a typical 3–4 category
   rollout). Give each group a human label from the category + its enabled scenarios
   (e.g. **HR KNOWLEDGE**, **HR TICKETING**, **PROFILE UPDATES**, **HANDOFF**).

   Then render it in chat — a short "thinking" line, the grouped prompts, a
   dependencies note, and next steps:

   > Thinking — turning your {N} scenario areas + goals into example test prompts…
   >
   > Here's a set of **{total} example prompts** across your {N} areas — this is the
   > bar your agent will be judged against. Tell me if you want to edit, cut, or add.
   >
   > **{CATEGORY 1 LABEL}**
   > "{prompt}"
   > "{prompt}"
   >
   > **{CATEGORY 2 LABEL}**
   > "{prompt}"
   > …
   >
   > **Quick note on dependencies** (from `check-deps` / the catalogue):
   > - {e.g. "Profile writes need governance sign-off before they'll pass."}
   >
   > **Next:** if the scope looks right I'll finish the deployment plan; otherwise
   > tell me what to change.

   **Render-only — persist nothing.** Do **not** write a CSV or any file, do **not**
   create eval records, and do **not** push to Dataverse. This is a visual preview;
   the actual eval is generated later by the *Generate evaluation tests* task.

4. **Set expectations, and let them edit.** Say this is a **preview** of the
   acceptance bar — the actual tests get **generated and run against the real agent
   later** by the plan's *Generate evaluation tests* task, once topics are built. If
   the sponsor wants to add/cut/reword prompts, just **re-render** the updated list —
   still persisting nothing.

## When it runs — eagerly, and non-blocking

Render this the moment scenarios + goals are captured (invoked from the interview,
`src/skills/planner/interview.md`, before Phase 3), so the sponsor sees the bar
early. It is **non-blocking**: after rendering, continue authoring the plan. You may
re-render at plan-authored time if the scope changed.

## Do / don't

- **Do** render the preview from the **scenarios the plan already captured** — don't
  ask the sponsor to repeat them.
- **Do** keep it **render-only**: no files, no eval records, no push.
- **Don't** run or modify the eval skill's generate/scan/push pipeline, and don't
  author eval YAML — the eval skill stays untouched; you are previewing, not
  generating.
- **Don't** block the plan on it. If you can't render a useful preview, say so
  plainly and move on — the *Generate evaluation tests* task still covers the real
  eval.

## Relationship to the "Generate evaluation tests" task

| | When | Grounded in | Generates? |
|---|---|---|---|
| **This preview** | scenarios+goals captured (planning time) | the sponsor's **scenarios** | **No** — renders only |
| **Generate evaluation tests task** | run time, after topics built | the built **topics** | Yes — generates + pushes |

The preview shows the bar early; the task does the real generation. Do not remove or
duplicate the task — this preview precedes it.
