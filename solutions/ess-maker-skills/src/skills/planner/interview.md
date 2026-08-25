# Planner — Phase 2: Interview (grounded slot-filling)

Ask the **fewest questions** that let you commit a buildable, scoped, assigned
Plan. Research (Phase 1) already proposed candidate scenarios, prerequisites,
and roles — so **propose, don't interrogate**, and only ask about a slot when
research didn't answer it. Batch by theme, one theme at a time, and stop early.

Every intent answer is stored as a **context entry** (grouped), via:

```
python scripts/planner/cli.py set-context --key <k> --value "<v>" --group <group> --description "<why>" --source User
```

## Ground scenario capture in the ESS catalogue

**Read `scripts/planner/scenario_catalogue.md` first.** It is the authoritative
scenario‑planning decision layer (a vendored snapshot of the ESS scenario
catalogue): the **category map**, the **default priority order + tiers**, and the
**dependency edges**. Capture the sponsor's goal by **mapping it to the
catalogue's categories** — do not invent a category, edge, priority, or order it
doesn't define, and don't force‑fit a goal that matches no ESS category (say so).
Per‑scenario detail (fields, setup, connectors, roles) is fetched from Microsoft
Learn at render time, never from the catalogue.

## The question bank — scenarios *before* systems

Capture in this order. **Build the scenario context first** — the jobs the team
should be able to self‑serve — *then* map each scenario to a system. Do **not**
ask "which system?" first and then reduce the scope to that one system's features:
that railroads the maker and silently drops whole scenario types (knowledge,
ticketing) they may have wanted.

| # | Ask | Store as |
|---|-----|----------|
| 1 | "In one sentence — what should this agent do, and for whom?" | `set-context --group objective` |
| 2 | **Scenarios (jobs‑to‑be‑done) — ask this before any system.** "What should your team be able to self‑serve? Think in outcomes, not systems." Map their answer to the **catalogue categories**: **HR Knowledge**, **HR Profile** (read/write), **Manager**, **HR Ticketing**, **IT** (knowledge + ticketing), **Handoff** — plus **extensible** scenarios (e.g. Request Time Off). Offer these, capture the sponsor's own words, and confirm which categories are in scope. | `set-context --group scenarioContext` (key `jtbd`) + `add-scenario` per category |
| 3 | **System per scenario — only after scenarios are captured.** "For **{scenario/area}**, which system holds the data?" — ground the options in the ESS native integrations from Phase‑1 research (Workday, ServiceNow HRSD/ITSM, SAP SuccessFactors); SharePoint / M365 content is a knowledge source. | `add-system --area {area} --system "{name}"` |
| 4 | "Employees only, or managers too?" | `set-context --group scenarioContext` (key `persona`) |
| 5 | "Rolling out to a specific market or wave first (e.g. India, a pilot group)?" | `set-context --group market` |
| 6 | "What business outcome measures success (e.g. deflect 30% of HR tickets)?" | `set-context --group businessGoals` |
| 7 | "How will you know a scenario is done — pilot‑ready? production‑signed‑off?" | `set-context --group acceptanceCriteria` |

**The catalogue IS the grounded scenario set — map the goal to it, don't invent.**
The categories above come from `scenario_catalogue.md`; use them to help the maker
articulate their goal, capture their own words, and confirm each in‑scope category
against Microsoft Learn (Phase 1). **Priority and order come from the catalogue's
default order** (Knowledge → Ticketing → Profile read/write → Handoff → sensitive
topics → multi‑language → mobile) and its tiers — emit that order; don't re‑derive
it. Picking a system (e.g. Workday) does **not** define the scenarios — a maker on
Workday may still want HR Knowledge and IT too, so ask Q2 first and let the answer
be broader than any one system. If a goal matches no ESS category, say so; don't
force‑fit.

**Ground the systems in Learn — don't improvise the connector list.** ESS ships
native integrations (extension packs) for a specific set of systems, each with a
Microsoft Learn page: **Workday**, **ServiceNow** (HRSD/ITSM), and **SAP
SuccessFactors**. Derive the current native set from Phase‑1 research (the
integration pages in the ESS Learn TOC — `workday`, `servicenow`,
`servicenow-hrsd-itsm`, `sapsuccessfactors`, …) rather than naming systems from
memory; that keeps it correct as Learn adds connectors. Two rules the maker's
answer must be checked against:

- **SharePoint (and other M365 content) is a *knowledge source*, not a data‑system
  connector** — capture it as the knowledge task, not a connect task.
- **A system with no native ESS connector — e.g. ADP, Jira, Dynamics 365, or a
  custom HTTP API — needs a custom Power Automate flow via `/create`, not a native
  connect task.** Flag it so Phase 3 emits a workflow (create) task, and say so to
  the maker rather than implying a native connector exists.

**Capture systems per area, not as one value.** Different areas usually use
different systems (e.g. HR knowledge on SharePoint, HR ticketing on ServiceNow
HRSD, IT ticketing on ServiceNow ITSM). Record each with its own scoped key so
they never overwrite each other:

```
python scripts/planner/cli.py add-system --area hr-knowledge --system "SharePoint (knowledge source)"
python scripts/planner/cli.py add-system --area hr-ticketing --system "ServiceNow HRSD"
python scripts/planner/cli.py add-system --area it-ticketing --system "ServiceNow ITSM"
```

**Scenarios are the maker's goal mapped to the catalogue categories.** Take the
scenarios from what the maker describes, map them to `scenario_catalogue.md`
categories, and confirm; ground each category's per‑scenario detail against
Microsoft Learn (Phase 1).

**Required before Phase 3, in this order.** (1) objective, (2) **the scenarios**
(the catalogue categories the maker wants — HR Knowledge, HR/IT Ticketing, Profile
read/write, Manager, Handoff, or an extensible one), then (3) **the system for
each scenario** are **mandatory**. Capture scenarios *before* systems — never let
a system choice narrow the scenario set. These determine the connect tasks, the
authoring tasks, and which Learn docs ground the roles. Do not skip them, and do
not end the interview (or jump to sponsor/timeframe) until scenarios and their
systems are captured. Ask 4–7 as scope warrants.

Use scalar values (one fact per entry); group related facts rather than nesting.

## Register the scenarios and expose dependencies

Register each in‑scope scenario with a stable id derived from the catalogue
category (e.g. `hr-knowledge`, `hr-profile-read`, `hr-profile-write`,
`hr-ticketing`, `it-knowledge`, `it-ticketing`, `handoff`):

```
python scripts/planner/cli.py add-scenario --id hr-ticketing --label "HR ticketing"
```

Then surface **scenario dependencies** — the catalogue's prerequisite edges
(`scenario_catalogue.md` → *Dependency order*), which the planner also ships in
`scripts/planner/planner_facts.json` (sourced from the catalogue):

- **Knowledge is the deflection foundation** — Ticketing, Profile, and Handoff
  work best after Knowledge (skipping it means more tickets created, not
  deflected).
- **Reads before writes** — enable a category's read before its write (HR Profile
  Read before HR Profile Write).
- **Handoff requires a Ticketing category** (HR or IT) — handoff escalates a ticket.

```
python scripts/planner/cli.py check-deps
```

If an in‑scope scenario depends on one that's not in scope, tell the sponsor in
plain language — "Deploy HR Knowledge before HR Ticketing so the agent deflects —
want me to add it?" — and, if they agree, register the prerequisite and record the
edge (cite the catalogue):

```
python scripts/planner/cli.py add-scenario --id hr-knowledge --label "HR knowledge"
python scripts/planner/cli.py add-scenario-dependency --scenario hr-ticketing --depends-on hr-knowledge --kind recommends --rationale "ess-catalogue.md: Knowledge is the deflection foundation"
```

Dependencies show up in the summary with a met / MISSING status and flow into task
sequencing (the knowledge task produces what the ticketing work consumes).

## Capture the enabled scenarios per category — the eval reads these off the plan

Registering a category (`hr-ticketing`) records the **area**, but not *what it
enables*. The eval (Phase 5, `src/skills/planner/evaluate.md`) reads scenarios
**off the plan** to write golden prompts — and "HR ticketing" alone isn't enough to
generate topic-level prompts (create a ticket, check a case). So for each in-scope
category, capture the **named scenarios it enables** onto the plan.

**Ground them — don't invent.** The source is the catalogue's **Named scenarios**
list per category (`scenario_catalogue.md` → *Named scenarios*), confirmed/refined
against Microsoft Learn for the chosen connector. E.g. **HR Ticketing (#32-34)**
enables *Read HR tickets*, *Create HR ticket*, *Update HR case*. Show the editor
what each in-scope category enables, confirm, then capture each enabled scenario as
a Context entry (group `scenarioCapability`, key `<category>.<slug>`):

```
python scripts/planner/cli.py set-context --key hr-ticketing.create-ticket --value "Create HR ticket" --group scenarioCapability --description "OOB HR Ticketing scenario (ESS catalogue #32-34)" --source Agent
python scripts/planner/cli.py set-context --key hr-ticketing.read-ticket   --value "Read HR tickets"  --group scenarioCapability --description "OOB HR Ticketing scenario (ESS catalogue #32-34)" --source Agent
```

**OOB vs extensible.** Capture the **OOB** named scenarios from the catalogue for
each in-scope category. Capture an **extensible** scenario (e.g. Request Time Off,
or a Workday pay/payslip specific) **only if the editor explicitly pins it** — and
then label it as extensible/custom, grounded from Learn per the connector; never
fold it into the OOB set and never invent one. Per-scenario *setup* detail (fields,
steps, connector config) still comes from Learn at render time — only the enabled
scenario **names** are captured here, as the eval's grounding.

These enabled scenarios appear in the plan (Intent → `scenarioCapability`) and are
exactly what the eager eval preview renders as golden prompts (below).

## Do NOT ask which role a Task needs

The **role** for each Task comes from the Learn docs (Phase 1), not the sponsor.
The sponsor's only assignment decision is *who* the person is (Phase 4). If a
prerequisite's role is genuinely unclear from the docs, fall back to a
conservative default (e.g. `Power Platform Administrator` — the exact WeveNova
role id) and note it — don't turn it into an interview question.

## Eager eval preview — render golden prompts once scenarios + goals are captured

**As soon as the sponsor's scenarios and goals are captured** (the `scenario` +
`scenarioCapability` groups and their `objective` / `businessGoals`), and **before**
you move on to modelling tasks (Phase 3), **render a preview of the eval** so the
sponsor sees the acceptance bar up front — exactly what "good" looks like, the way
the finished agent will be judged. Read `src/skills/planner/evaluate.md` and render
the golden prompts grouped by scenario category.

This preview **renders only — it generates nothing**: it displays the golden prompts
in chat but writes no file, creates no eval records, and pushes nothing. Actual eval
generation stays with the *Generate evaluation tests* task (topic-driven, later).
It is **non-blocking**: after rendering, continue to the stop condition and Phase 3.

## Stop condition — both satisfied

- **Sponsor-satisfied:** they've seen the proposed scenario list + goals and
  accepted them.
- **ADK-satisfied:** every in-scope scenario maps to a grounded, supported
  capability; every prerequisite has a Task; and every Task will be either
  assigned to a person or pooled to a role.

If a requested scenario isn't ESS-supported, or a prerequisite has no owner,
surface it and resolve it with the sponsor rather than emitting an unbuildable
Plan. When both hold, show the summary and go to Phase 3.
