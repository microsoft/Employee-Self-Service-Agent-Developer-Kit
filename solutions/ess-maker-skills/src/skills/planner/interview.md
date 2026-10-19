# Planner — Phase 2: Interview (grounded slot-filling)

Ask the **fewest questions** that let you commit a buildable, scoped, assigned
Plan — then **generate the plan from sensible defaults and let the sponsor edit
it**, rather than interrogating every slot up front. Research (Phase 1) already
proposed candidate scenarios, prerequisites, and roles — so **propose, don't
interrogate**.

**The question budget: three short turns, then build.** Only three things are
worth asking before you generate a plan — ask each as one batched turn, then stop
and build:

1. **Goal + success** (one sentence).
2. **Scenarios** — the jobs employees self-serve, and (lightly) what's off the table.
3. **The system behind each scenario area.**

This is a ceiling, not three mandatory questions. Read the request and existing
plan first; acknowledge already-clear choices instead of reconfirming them.
For example, "Plan ESS HR with Workday profile updates" already supplies HR, a
scenario, and its system. Set `set-agent-name --name EmployeeSelfServiceHRDA`
without asking HR or IT again. Use `EmployeeSelfServiceITDA` for an explicit IT
target; ask only if the target agent really is ambiguous.

Before Q1, give the short plan definition and journey in `SKILL.md`. For every
offered choice, explain the employee outcome, what it needs, and what work it
adds. Offer peer scenarios, not a base bundle beside an unexplained "add ticketing."

**Everything else is assumed, not asked.** Persona, market/wave, the success
*measure*, the acceptance bar, and the *per-scenario detail within a category*
(e.g. which Workday fields an employee can view or update) are **defaulted** from
the catalogue and sensible norms, stated in one readback line, written onto the
plan as editable assumptions (`--source Agent`), and surfaced as **follow-up edit
options** once the sponsor has seen the plan and the eval preview. Do **not** turn
any of them into an interview question. Asking the sponsor to hand-pick Workday
view/update fields — or to name a deflection % and a done-bar — before they've seen
a plan is exactly the over-interrogation this flow exists to avoid: a sponsor who
wants something different edits it on the plan.

**Frontload the goals, render the bar early.** Lead with what success looks like
and the handful of scenarios employees actually ask about, so you can **render the
golden-prompt preview within the first couple of turns** — the acceptance bar, up
front — then pin the systems right after. Goals are the non-negotiable; the systems
behind them can be refined once the sponsor has seen the bar.

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
| 1 | **Goal + success, together.** "In one sentence — what should this agent do, and for whom? And what does success look like — fewer support tickets, faster policy answers, or something else?" (The success half seeds the default success measure below — you won't ask for it separately.) | `set-context --group objective` |
| 2 | **Scenarios (jobs‑to‑be‑done) — ask this before any system.** "Which 2–3 things do employees ask about most?" (e.g. *"How many vacation days do I have?"*, *"Reset my password"*, *"Update my phone number"*) — then widen: "Which scenarios are you thinking about beyond that?" To prioritise, offer a starting point: "Pick a focus — HR or IT — and expand from there. Where do employees feel the most friction today?" Map their answer to the **catalogue categories**: **HR Knowledge**, **HR Profile** (read/write), **Manager**, **HR Ticketing**, **IT** (knowledge + ticketing), **Handoff** — plus **extensible** scenarios (e.g. Request Time Off). Offer these, capture the sponsor's own words, and confirm which categories are in scope. | `set-context --group scenarioContext` (key `jtbd`) + `add-scenario` per category |
| 3 | **System per scenario — only after scenarios are captured.** "For **{scenario/area}**, which system holds the data?" — ground the options in the ESS native integrations from Phase‑1 research (Workday, ServiceNow HRSD/ITSM, SAP SuccessFactors); SharePoint / M365 content is a knowledge source. | `add-system --area {area} --system "{name}"` |

That is the whole interview before you build. **Don't ask a fourth kind of
question** — default the rest and let the sponsor edit it on the generated plan.

### Render the option-based questions as selectable — not free text

Q1 (goal + success) is open-ended, so ask it as free text. **Q2 (scenarios) and Q3
(system) are option-based — present them as selectable options with
`vscode_askQuestions`, exactly like the rest of the kit, never as a bare "type your
answer" prompt.** Both are **multi-select** (`multiSelect: true`) — a maker normally
wants several scenarios, and an area can touch more than one system — so render these
as **checkboxes, not radio buttons**. Keep `allowFreeformInput: true` on both so the
sponsor can also add something not listed; the final answer combines their checkbox
selections and anything they type.

**Q2 — scenarios (the jobs to self-serve).** Offer the catalogue categories as
options and let the sponsor **check every job that applies** (picking several is
normal), adding anything missing via freeform:

```json
[
  {
    "header": "What should employees self-serve?",
    "question": "Which of these do employees ask about most? Select all that apply — you can add more in your own words.",
    "multiSelect": true,
    "options": [
      { "label": "HR Knowledge", "description": "Answer policy and benefits questions from approved HR documents; needs a knowledge source, not personal HR records.", "recommended": true },
      { "label": "HR Profile — view", "description": "Show an employee their own HR details or leave balance; adds an HR-system connection and identity/access configuration." },
      { "label": "HR Profile — update", "description": "Let employees change supported personal details; needs profile access plus approved write-back permissions and testing." },
      { "label": "HR Ticketing", "description": "Create and track HR requests; adds a case-management connection. This is a separate scenario, not an unexplained add-on bundle." },
      { "label": "IT (knowledge + ticketing)", "description": "Answer IT questions and create or track IT tickets; needs approved IT content and an IT service-management system." },
      { "label": "Manager", "description": "Support managers with approved team information or actions; needs manager authorization and additional governance." },
      { "label": "Handoff", "description": "Escalate an unresolved conversation to a live agent; needs ticketing and a supported handoff channel." },
      { "label": "Not sure yet", "description": "Save the scope decision as pending and show a suggested starting point; you can refine it later." },
      { "label": "Something else", "description": "Describe another employee outcome; we'll check support and call out any custom work before committing to it." }
    ],
    "allowFreeformInput": true
  }
]
```

**Q3 — the systems behind each scenario area.** Ask once per captured area (or once
across all areas), grounding the options in the ESS native integrations (Phase 1) and
letting the sponsor **check every system in play** — an area can span more than one
(e.g. HR profile on Workday *and* HR tickets on ServiceNow HRSD). SharePoint / M365 is
a knowledge source, and anything with no native connector needs a custom flow via
`/create`:

```json
[
  {
    "header": "Which systems hold {area} data?",
    "question": "For {scenario/area}, which systems hold the data? Select all that apply.",
    "multiSelect": true,
    "options": [
      { "label": "Workday", "description": "HR profile data or supported HR actions; a supported integration that needs Workday, identity, and Power Platform setup." },
      { "label": "ServiceNow HRSD", "description": "HR case/request management; needs the HRSD integration and a ServiceNow administrator." },
      { "label": "ServiceNow ITSM", "description": "IT ticket management; needs the ITSM integration and a ServiceNow administrator." },
      { "label": "SAP SuccessFactors", "description": "HR data or supported HR actions; needs the SuccessFactors integration and system-admin configuration." },
      { "label": "SharePoint / M365", "description": "Approved documents or intranet pages for knowledge answers; not a connector for personal HR records or write-backs." },
      { "label": "Not sure yet", "description": "Keep the scenario in scope and record the system as pending. Only its system-specific work needs to wait." },
      { "label": "Something else", "description": "Name the system if known; we'll check support. A system without a native integration needs a scoped custom flow." }
    ],
    "allowFreeformInput": true
  }
]
```

Map **each** thing they check (or type) back to the catalogue categories and the
native connector set exactly as the table rows above describe — multi-select only
changes *how* you ask, not what you capture or how you ground it. Several scenarios or
systems in one answer is expected; capture every one (systems are still recorded per
area, never overwriting each other).

### If the sponsor isn't sure — record a pending decision, don't guess

"Not sure", "I don't know yet", or "we haven't decided" is a **valid answer**.
Save it, acknowledge it once, and continue. Silence is not consent to a system
choice. A recommendation is not a confirmed customer fact.

- **Uncertain scope (Q2)** → keep any already-selected scenarios. Record
  `set-context --key scope --value "Scenario selection pending" --group pendingDecision`
  and present a clearly labeled catalogue-based suggestion, not a silently
  confirmed scope. Build the common foundation and review work now.
- **Unknown system (Q3)** → run
  `add-system --area <scenario-id> --pending`. This persists a `pendingDecision`
  entry with the same `system.<area>` key used when resolved. Keep the requested
  scenario: do not substitute SharePoint, guess Workday from research, or turn a
  profile update into a knowledge-only experience. Say: "I'll leave the system
  pending. We can finish the plan now; that integration waits until it is known."
- **Some systems known, others uncertain** → record all confirmed selections in
  one `add-system` call with repeated `--system` arguments. Save a separate
  `pendingDecision` for the missing area/additional system. Never include "Not sure"
  as a system name or overwrite confirmed selections with that choice.
- **Unknown owner** → keep the grounded role and record `owner.<role-id>` in
  `pendingDecision`. Explain what they own and that independent work can continue.

Do not re-ask deferred questions on resume or block drafting, sharing, or activation
of unrelated ready work. Use the dependency gates in `model.md` for affected
execution only. When the maker supplies a system later, `add-system --area ...`
replaces that pending entry; refine only the affected tasks and evals.

### Assume these — never ask them up front

For each, use the sponsor's own words if Q1–Q3 already answered it (keep
`--source User`); otherwise default it **silently**, mark it `--source Agent`, state
it in the one-line readback, and expose it as a follow-up edit (below):

| Slot | Default (unless the goal already said otherwise) | Store as |
|------|-----|----------|
| **Persona** | Employees only (managers deferred) | `set-context --group scenarioContext` (key `persona`) |
| **Market / wave** | Whatever market the sponsor already named (a city/pilot group); else "no specific wave" | `set-context --group market` |
| **Success measure** | A clearly-labeled target tied to the Q1 success picture (e.g. *"deflect ~30% of HR tickets"*), marked as an assumption to adjust | `set-context --group businessGoals` |
| **Acceptance bar** | "Pilot-ready — configured, tested, ready for a controlled pilot" | `set-context --group acceptanceCriteria` |
| **Enabled scenarios per category** | The **full OOB named-scenario set** for each in-scope category from the catalogue (below) — not a hand-picked subset | `set-context --group scenarioCapability` |

The sponsor first sees a **complete plan + acceptance bar**, then adjusts — instead
of answering a questionnaire to produce one.

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
python scripts/planner/cli.py add-system --area hr-profile-read --system "Workday" --system "SAP SuccessFactors"
python scripts/planner/cli.py add-system --area hr-profile-write --pending
```

**Scenarios are the maker's goal mapped to the catalogue categories.** Take the
scenarios from what the maker describes, map them to `scenario_catalogue.md`
categories, and confirm; ground each category's per‑scenario detail against
Microsoft Learn (Phase 1).

**Capture before Phase 3, in this order.** (1) objective, (2) **the scenarios**
(the catalogue categories the maker wants — HR Knowledge, HR/IT Ticketing, Profile
read/write, Manager, Handoff, or an extensible one), then (3) **the system for
each scenario or an explicit pending decision**. Capture scenarios *before* systems — never let
a system choice narrow the scenario set. These determine the connect tasks, the
authoring tasks, and which Learn docs ground the roles. Do not skip them, and do
not keep interviewing after the maker defers a decision. Everything beyond these three (persona, market, success
measure, acceptance bar, and the per-category detail) is **defaulted, not asked** —
see *Assume these* above; the sponsor edits it on the generated plan.

Use scalar values (one fact per entry); group related facts rather than nesting.

**Capture what's off the table — only if they said so.** Q2 already invites this
("anything off the table for now?"). If the sponsor named a boundary (write-backs,
escalations, manager scenarios), record it so both the golden-prompt preview and
the plan respect it (the eval **drops** out-of-scope work —
`src/skills/planner/evaluate.md`). If they didn't, default to none and move on; they
can add a boundary on the plan later:

```
python scripts/planner/cli.py set-context --key outOfScope --value "No manager scenarios; no write-backs this wave" --group scenarioContext --description "Explicitly out of scope for this wave" --source User
```

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

## Enabled scenarios per category — default the full OOB set (don't ask field-by-field)

Registering a category (`hr-ticketing`) records the **area**, but not *what it
enables*. The eval (Phase 5, `src/skills/planner/evaluate.md`) reads scenarios
**off the plan** to write golden prompts — and "HR ticketing" alone isn't enough to
generate topic-level prompts (create a ticket, check a case). So for each in-scope
category, capture the **named scenarios it enables** onto the plan — by **defaulting
to the catalogue's full OOB named-scenario set** for that category, not by asking the
sponsor to hand-pick fields or operations.

**Ground them — don't invent, don't interrogate.** The source is the catalogue's
**Named scenarios** list per category (`scenario_catalogue.md` → *Named scenarios*),
confirmed/refined against Microsoft Learn for the chosen connector. E.g. **HR
Ticketing (#32-34)** enables *Read HR tickets*, *Create HR ticket*, *Update HR
case*; **HR Profile read** enables that connector's standard profile fields (on
Workday: core job details, employment & contact, compensation), **HR Profile write**
its standard editable fields (e.g. personal email, phone). Capture the **whole** OOB
set for each in-scope category as Context entries — do **not** ask the sponsor which
fields or which operations are in scope. They see the full set on the plan and in
the eval preview and **trim it there** if they want less (group `scenarioCapability`,
key `<category>.<slug>`):

```
python scripts/planner/cli.py set-context --key hr-ticketing.create-ticket --value "Create HR ticket" --group scenarioCapability --description "OOB HR Ticketing scenario (ESS catalogue #32-34)" --source Agent
python scripts/planner/cli.py set-context --key hr-ticketing.read-ticket   --value "Read HR tickets"  --group scenarioCapability --description "OOB HR Ticketing scenario (ESS catalogue #32-34)" --source Agent
```

**OOB vs extensible.** Capture the **OOB** named scenarios from the catalogue for
each in-scope category **by default — without asking the sponsor to pick**. Capture
an **extensible** scenario (e.g. Request Time Off,
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
conservative default (e.g. `power-platform-admin`) and note it — don't turn it
into an interview question.

## Eager eval preview — render golden prompts once scenarios + goals are captured

**As soon as the sponsor's scenarios and goals are captured** (the `scenario` +
`scenarioCapability` groups and their `objective` / `businessGoals`), and **before**
you move on to modelling tasks (Phase 3), **render a preview of the eval** so the
sponsor sees the acceptance bar up front — exactly what "good" looks like, the way
the finished agent will be judged. Read `src/skills/planner/evaluate.md` and render
the golden prompts grouped by scenario category.

Generate and persist draft scenario cases using `evaluate.md`; show only a few
representative examples with their expected behavior, not a wall of prompts.
Native test generation runs within the guided flow once topics and permissions
are available. Do not require the maker to discover a separate `/evaluate` command.
This is **non-blocking**: continue to Phase 3 without demanding an extra approval
turn for the planning draft. Approval is still required before topic/push mutations.

This is the **golden-prompts-in-the-first-couple-of-turns** moment the flow is
built around: goals first, the bar rendered early, then systems and dependencies
captured right after. Rendering the bar does **not** wait for every system to be
pinned — scenarios + goals are enough to show what "good" looks like.

## After the plan is shown — stop, and name the next steps (don't run them)

**Showing the plan is the end of the turn.** Once the plan is modelled and presented
locally (the download link **then** the grouped task checklist — `SKILL.md` →
*Building the plan*), **stop there** — the plan stays in the maker's workspace and is
**not** stored to the shared space until the sponsor asks to share it. Do **not**:

- fire a blocking "What would you like to do next?" question (no `ask_user`, no
  numbered menu) — the plan the sponsor just received is the deliverable, not a
  prompt for more input;
- start assigning roles, open the edit round-trip, or run any other follow-up on
  your own. The plan is complete as-is.

Instead, close with an explicit, scannable **Next steps** readout — plain language,
no form, no blocking question — so the sponsor sees exactly what they can do next and
picks when ready. Make the three paths obvious. Model it on the kit's style:

> Your plan's saved locally and ready to download above. **Next steps — just say the
> word:** **1) Edit** the scope or any assumption, **2) Share** it to save it to the
> shared space and **activate** it when it's ready (editing is easiest *before* you
> share), and **3) Assign the roles to people** once it's active, so each owner can
> see their tasks.

Then **end the turn.** Act on a follow-up **only when the sponsor replies asking for
it** in a later turn:

1. **Assign roles to people.** The plan ships with every task grounded to a **role**
   but **not yet assigned to a person** — no named owners yet. If (and only if) the
   sponsor asks, run Phase 4 (`src/skills/planner/assign.md`) / the roles attestation
   flow (`src/skills/roles/nudge.md` → `src/skills/roles/attest.md`). Otherwise the
   roles stay unassigned — that's a complete, valid state, not a gap to chase.
2. **Edit the plan / its assumptions.** The measure, acceptance bar, persona, and
   per-category detail were **assumed**, so they're trivial to change on request.
   When the sponsor asks for a change — scope (add/drop a scenario category, or trim
   the enabled scenarios, e.g. "only let employees update phone, not email"), the
   system behind an area, the success measure (20% vs 30% deflection), the acceptance
   bar (pilot-ready vs production-signed-off), or persona/market (include managers,
   change the wave) — apply it through the edit round-trip
   (`src/skills/planner/edit.md`): state it as context/scenario edits, re-render, and
   re-show the plan (and, if scope changed, re-render the eval preview).

This "generate, show, then refine/assign **only when asked**" loop is what replaces
front-loaded interrogation — the suggestion invites the sponsor; it never interrogates
them.

## Stop condition — enough to generate, then edit

You have enough to **generate** the plan as soon as the objective and known scope
are captured, with missing scope/systems explicitly marked **pending**. Don't keep interviewing for the defaulted slots —
generate the plan, render the eval preview, and present both; the sponsor then
assigns roles or **edits** from there (the follow-ups above).

- **ADK-satisfied:** every in-scope scenario maps to a grounded, supported
  capability; every prerequisite has a Task; and every Task is grounded to a role
  (assigned to a person later, or left open to the role for now).
- **Sponsor-in-control:** the sponsor sees the full plan + the acceptance bar and
  can assign roles or change any assumption (scope, systems, measure, persona,
  fields) via a follow-up — acceptance is the edit loop, not a pre-build
  questionnaire.

If support is unknown or an owner is missing, record a pending decision and identify
the affected work; do not assert unsupported capabilities or stop the whole plan. When the
ADK-satisfied bar holds, show the summary + eval preview and go to Phase 3.
