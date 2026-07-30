# Planner — Phase 2: Interview (grounded slot-filling)

Ask the **fewest questions** that let you commit a buildable, scoped, assigned
Plan. Research (Phase 1) already proposed candidate scenarios, prerequisites,
and roles — so **propose, don't interrogate**, and only ask about a slot when
research didn't answer it. Batch by theme, one theme at a time, and stop early.

Every intent answer is stored as a **context entry** (grouped), via:

```
python scripts/planner/cli.py set-context --key <k> --value "<v>" --group <group> --description "<why>" --source User
```

## The question bank

| Ask (grounded example) | Store as `--group` |
|------------------------|--------------------|
| "In one sentence — what should this agent do, and for whom?" | `objective` |
| "Which systems hold that data — Workday, ServiceNow, SharePoint?" | `scenarioContext` (key `targetSystem`) |
| "From {system} I can support {grounded scenario list}. Which are in scope for the first wave?" | `scenarioContext` (keys `area`, `jtbd`) |
| "Employees only, or managers too?" | `scenarioContext` (key `persona`) |
| "Rolling out to a specific market or wave first (e.g. Germany, a pilot group)?" | `market` |
| "What business outcome measures success (e.g. deflect 30% of HR tickets)?" | `businessGoals` |
| "How will you know a scenario is done — pilot-ready? production-signed-off?" | `acceptanceCriteria` |
| "Is this a brand-new environment, or do you already have ESS running?" | (branch — greenfield vs enrichment) |

Questions 1–3 are almost always asked; 4–7 as scope warrants; the last is one
branch. Use scalar values (one fact per entry); group related facts rather than
nesting.

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
