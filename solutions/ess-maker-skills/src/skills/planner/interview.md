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

| Ask (grounded example) | Store as |
|------------------------|----------|
| "In one sentence — what should this agent do, and for whom?" | `set-context --group objective` |
| "Which system holds the data for **{area}** — e.g. Workday, ServiceNow, SharePoint?" — ask **per area**, once you know the areas | `add-system --area {area} --system "{name}"` |
| "Which business scenarios are in scope for the first wave?" — capture the maker's own words; ground each against Microsoft Learn (Phase 1). Do **not** offer a fixed menu. | `set-context --group scenarioContext` (keys `area`, `jtbd`) |
| "Employees only, or managers too?" | `set-context --group scenarioContext` (key `persona`) |
| "Rolling out to a specific market or wave first (e.g. Germany, a pilot group)?" | `set-context --group market` |
| "What business outcome measures success (e.g. deflect 30% of HR tickets)?" | `set-context --group businessGoals` |
| "How will you know a scenario is done — pilot-ready? production-signed-off?" | `set-context --group acceptanceCriteria` |
| "Is this a brand-new environment, or do you already have ESS running?" | (branch — greenfield vs enrichment) |

**Capture systems per area, not as one value.** A rollout usually has different
systems per area (e.g. HR knowledge on SharePoint, HR ticketing on ServiceNow
HRSD, IT ticketing on ServiceNow ITSM). Record each with its own scoped key so
they never overwrite each other:

```
python scripts/planner/cli.py add-system --area hr-knowledge --system "SharePoint"
python scripts/planner/cli.py add-system --area hr-ticketing --system "ServiceNow HRSD"
python scripts/planner/cli.py add-system --area it-ticketing --system "ServiceNow ITSM"
```

**Scenarios come from the maker, grounded in Learn — never from a fixed list.**
Take the scenarios from what the maker describes and confirm them; ground the
details (prerequisites, roles, systems) against Microsoft Learn (Phase 1). Do not
present a canonical menu of supported scenarios — there isn't one.

**Required before Phase 3.** Questions 1–3 (objective, **which system per area**,
**which scenarios**) are **mandatory** — they determine the connect tasks, the
authoring tasks, and which Learn docs ground the roles. Do not skip them, and do
not end the interview (or jump to unrelated questions like sponsor/timeframe)
until systems and scenarios are captured. Ask 4–7 as scope warrants. For each
chosen system you will emit a connect task in Phase 3; for each scenario you
register it (below) and author tasks.

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
