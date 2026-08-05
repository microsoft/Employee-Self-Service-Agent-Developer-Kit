# Planner — Phase 2: Interview (grounded slot-filling)

Ask the **fewest questions** that let you commit a buildable, scoped, assigned
Plan. Research (Phase 1) already proposed candidate scenarios, prerequisites,
and roles — so **propose, don't interrogate**, and only ask about a slot when
research didn't answer it. Batch by theme, one theme at a time, and stop early.

Every intent answer is stored as a **context entry** (grouped), via:

```
python scripts/planner/cli.py set-context --key <k> --value "<v>" --group <group> --description "<why>" --source User
```

## The question bank — scenarios *before* systems

Capture in this order. **Build the scenario context first** — the jobs the team
should be able to self‑serve — *then* map each scenario to a system. Do **not**
ask "which system?" first and then reduce the scope to that one system's features:
that railroads the maker and silently drops whole scenario types (knowledge,
ticketing) they may have wanted.

| # | Ask | Store as |
|---|-----|----------|
| 1 | "In one sentence — what should this agent do, and for whom?" | `set-context --group objective` |
| 2 | **Scenarios (jobs‑to‑be‑done) — ask this before any system.** "What should your team be able to self‑serve? Think in outcomes, not systems. ESS commonly covers **HR knowledge** (answer policy / FAQ questions), **HR ticketing** (raise & track HR cases), **IT ticketing** (IT support), and **specific data actions** (e.g. view time‑off balance, request time off, view pay). Which of these — in your words? Anything else?" | `set-context --group scenarioContext` (key `jtbd`) + `add-scenario` per area |
| 3 | **System per scenario — only after scenarios are captured.** "For **{scenario/area}**, which system holds the data?" — ground the options in the ESS native integrations from Phase‑1 research (Workday, ServiceNow HRSD/ITSM, SAP SuccessFactors); SharePoint / M365 content is a knowledge source. | `add-system --area {area} --system "{name}"` |
| 4 | "Employees only, or managers too?" | `set-context --group scenarioContext` (key `persona`) |
| 5 | "Rolling out to a specific market or wave first (e.g. India, a pilot group)?" | `set-context --group market` |
| 6 | "What business outcome measures success (e.g. deflect 30% of HR tickets)?" | `set-context --group businessGoals` |
| 7 | "How will you know a scenario is done — pilot‑ready? production‑signed‑off?" | `set-context --group acceptanceCriteria` |
| 8 | "Is this a brand‑new environment, or do you already have ESS running?" | (branch — greenfield vs enrichment) |

**The scenario examples in Q2 (knowledge / HR ticketing / IT ticketing / data
actions) are prompts, not a fixed catalogue.** They're grounded in what ESS ships
(HR + IT starters, knowledge sources, ServiceNow HRSD/ITSM) and the PM spec's
knowledge‑vs‑ticketing framing — use them to help the maker *articulate* their
scenarios, then capture the maker's own words and confirm each against Microsoft
Learn (Phase 1). Picking a system (e.g. Workday) does **not** define the scenarios
— a maker on Workday may still want HR knowledge and IT ticketing too, so ask Q2
first and let the answer be broader than any one system. If the maker names
something ESS doesn't support, say so; don't force‑fit.

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

**Scenarios come from the maker, grounded in Learn — never from a fixed list.**
Take the scenarios from what the maker describes and confirm them; ground the
details (prerequisites, roles, systems) against Microsoft Learn (Phase 1). The Q2
examples are prompts to help them articulate — capture their own words.

**Required before Phase 3, in this order.** (1) objective, (2) **the scenarios /
jobs‑to‑be‑done** (knowledge, ticketing, IT, data actions — whatever the maker
wants), then (3) **the system for each scenario** are **mandatory**. Capture
scenarios *before* systems — never let a system choice narrow the scenario set.
These determine the connect tasks, the authoring tasks, and which Learn docs
ground the roles. Do not skip them, and do not end the interview (or jump to
sponsor/timeframe) until scenarios and their systems are captured. Ask 4–8 as
scope warrants. For each chosen system you emit a connect task in Phase 3; for
each scenario you register it (below) and author tasks.

Questions 1–3 are almost always asked; 4–7 as scope warrants; the last is one
branch. Use scalar values (one fact per entry); group related facts rather than
nesting.

## Register the scenarios and expose dependencies

As the sponsor picks scenarios, register each one so the plan knows what's in
scope. Use a stable, conventional id derived from the maker's own scenario (e.g.
`hr-knowledge`, `hr-ticketing`, `it-ticketing`) — the id is just a handle, not a
menu you pick from:

```
python scripts/planner/cli.py add-scenario --id hr-ticketing --label "HR ticketing"
```

Then check for **scenario dependencies** — cases where one scenario should be
deployed before another. The planner ships a small set of *known* dependencies in
`scripts/planner/planner_facts.json` (each with an explicit `source`). One is
**knowledge before ticketing** — deploy knowledge first so the agent answers from
knowledge and only opens a ticket when unresolved (deflection). Treat this as
design guidance, not a verbatim spec requirement, unless a citation is confirmed.
Surface any met/unmet dependencies:

```
python scripts/planner/cli.py check-deps
```

If a selected scenario depends on one that's not in scope, tell the sponsor in
plain language — "To get the deflection benefit, deploy HR knowledge before HR
ticketing — want me to add it?" — and, if they agree, register the prerequisite
scenario and record the edge (cite the real source; don't attribute it to the PM
spec unless you can point to it):

```
python scripts/planner/cli.py add-scenario --id hr-knowledge --label "HR knowledge"
python scripts/planner/cli.py add-scenario-dependency --scenario hr-ticketing --depends-on hr-knowledge --kind requires --rationale "Deflection: answer from knowledge before opening a ticket"
```

Dependencies are stored as ordinary intent in the open plan and show up in the
summary with a met / MISSING status, so the ordering is visible to everyone and
flows into task sequencing (the knowledge task produces what the ticketing work
consumes).

## Do NOT ask which role a Task needs

The **role** for each Task comes from the Learn docs (Phase 1), not the sponsor.
The sponsor's only assignment decision is *who* the person is (Phase 4). If a
prerequisite's role is genuinely unclear from the docs, fall back to a
conservative default (e.g. `power-platform-admin`) and note it — don't turn it
into an interview question.

## Stop condition — both satisfied

- **Sponsor-satisfied:** they've seen the proposed scenario list + goals and
  accepted them.
- **ADK-satisfied:** every in-scope scenario maps to a grounded, supported
  capability; every prerequisite has a Task; and every Task will be either
  assigned to a person or pooled to a role.

If a requested scenario isn't ESS-supported, or a prerequisite has no owner,
surface it and resolve it with the sponsor rather than emitting an unbuildable
Plan. When both hold, show the summary and go to Phase 3.
