# ADK Plan Generation (Planner): Dev Plan

**Owner:** Harsheet Jain - ADK planner (Step 1)  
**Partner:** WeveNova backend - Plan/Task persistence (Step 2)  
**Status:** Step 1 (local-first `/planner`) implemented; Step 2 (WeveNova sync) and the roles / `/discover` / tenant-inventory seams pending

## Objective

Turn a sponsor's intent into a grounded, local-first **Plan** - a handful of
atomic Tasks, each owned by a Learn-grounded role (then a specific person) - and
keep the Plan honest by capturing what each Task actually produced.

```text
Intent -> Research (Learn) -> Interview -> Model atomic Tasks -> Assign (role -> person) -> Do work -> Capture outputs -> back-propagate
```

Today, deciding an ESS rollout and running the kit skills are disconnected. This
connects them: the Plan is authored, grounded, and enriched as Tasks complete -
and is shaped to sync to the WeveNova Plan/Task entities later (Step 2).

## MVP scope

### Step 1: Local-first planner

- Grounded Microsoft Learn research (Table-of-Contents first).
- Sponsor interview -> scenarios, systems, persona/market, goals.
- Atomic, role-based Tasks (split on every role boundary; Workday connect is
  decomposed into role Tasks read from its setup checklist).
- Flow 1 (assign a person to a grounded role) and Flow 2 ("what am I assigned?").
- Output capture (observe `.local/config.json`, or ask the assignee) with
  back-propagation so downstream Tasks read produced values off the Plan.
- Editable `ESS-scenario-plan.md` round-trip; render-only eager eval preview.

### Deferred to a separate PR (Step 2 and the seams)

- WeveNova Plan/Task persistence and cross-plan Flow 2 (the Step 2 design).
- The roles endpoint (`listHolders(role)` / `rolesOf(person)`).
- `/discover` plus tenant-inventory reads (WeveNova via an MCP). Until the
  inventory read surface stabilizes, the planner reads ids + names from
  `.local/config.json`.
- Any-of scenario dependencies (e.g. Handoff requires HR *or* IT ticketing).

## Technical approach

Reuse the existing kit skills; do not build a new engine. The planner
orchestrates and records.

1. TOC-first Learn research grounds capabilities, prerequisites, roles, and each
   prerequisite's produced-keys.
2. A local `plan.json` shaped like the WeveNova Plan/Task/Principal entities, so a
   future sync is a field copy, not a re-model.
3. A Task is `title` + `description` (+ a grounded role and `produces`/`consumes`)
   - there is no execution `action` field; the "how" lives in the description.
4. Capture fills each declared `produces` key by observing the kit state the
   action changed (a `config.json` diff) or by asking the assignee, always
   confirmed before it is pinned.
5. All structured reads/writes go through the CLI so writes are atomic and
   validated.

## Current implementation status

| Done | Remaining |
|------|-----------|
| `/planner` skill + `scripts/planner` package; local `plan.json` and editable `ESS-scenario-plan.md`. | Sync the Plan to the WeveNova Plan/Task entities (Step 2, field copy + If-Match reconcile). |
| TOC-first Learn research selection, with role/output-candidate extraction per page. | Resolve real people from a roles endpoint (today Tasks pool to a role / self-select). |
| Interview captures scenarios, systems, goals; scenario dependencies live in the open Context bag. | Add `/discover` and read the tenant inventory (ids + names) via a WeveNova MCP. |
| Atomic role-based Tasks; Workday connect modelled as multiple role Tasks from its setup checklist. | Persist the research context (`research-context.json`) and per-task Learn anchors. |
| Flow 1 (assign person to grounded role) and Flow 2 (discovery grouped by role, waiting work only). | Represent any-of scenario prerequisites (pairwise model cannot today). |
| Generic `config.json` output capture (environment, cloned agent, connections, ...) with a before-snapshot guard, plus back-propagation. | Wire the runtime `checklist[]` display state into Flow 2 if we promote step visibility. |
| Render-only eager eval preview (does not modify the eval skill). | Pilot on a real greenfield tenant and fold in fixes. |
| 108 automated tests; `ruff` clean; validated, atomic CLI writes. | |

## Work plan

| Milestone | Work | Exit criteria | Estimate |
|-----------|------|---------------|----------|
| 1. Land Step 1 (this PR) | The local-first `/planner`: research, interview, model, assign, capture, editable plan. | PR merged; 108 tests green; CI clean. | Done |
| 2. WeveNova sync | Field-copy plan/tasks/outputs to the WeveNova entities; best-effort sync with If-Match reconcile. | A Plan round-trips to WeveNova and back with no re-model. | 2-3 weeks (Step 2 team) |
| 3. Roles endpoint | `listHolders` / `rolesOf` over the `RoleSource` seam. | Flow 1 lists holders; Flow 2 resolves a person's roles. | 1-2 weeks |
| 4. `/discover` + inventory | Crawl Dataverse -> `config.json` -> WeveNova inventory; planner reads ids + names from the inventory. | Greenfield and enrichment paths are both grounded from the inventory. | 2-3 weeks |

## Engineering backlog

| Priority | Work item | Owner |
|----------|-----------|-------|
| P0 | Keep `plan.json` field-aligned to the WeveNova Plan/Task/Principal entities. | Harsheet + WeveNova |
| P0 | Ground roles and `produces` from Learn per prerequisite (no hardcoded defaults). | Harsheet |
| P0 | Confirm-before-pin output capture (observe `config.json`, else ask). | Harsheet |
| P0 | Validate every CLI write; refuse to persist an invalid Plan. | Harsheet |
| P1 | Roles endpoint contract (`listHolders` / `rolesOf`) beyond the boolean seam. | Roles-source workstream |
| P1 | `/discover` + tenant-inventory read surface (which fields, what permission). | ADK + WeveNova |
| P1 | Persist research context and per-task Learn anchors. | Harsheet |
| P2 | Any-of scenario dependency model. | Harsheet + PM |

## Ownership

| Area | Owner |
|------|-------|
| Planner skill, plan model, capture | Harsheet Jain |
| WeveNova Plan/Task persistence (Step 2) | WeveNova backend |
| Roles endpoint | Roles-source workstream |
| `/discover` + tenant inventory | ADK + WeveNova |
| Eval skill (invoked, not owned) | Eval workstream |
| Scenario selection and product acceptance | PM |

## Dependencies and decisions

The following must be confirmed before the deferred work (tracked as open
questions in the design doc, section 18):

1. The roles-endpoint enumeration contract (`listHolders` / `rolesOf`).
2. Whether to persist a raw `environmentId` GUID on `config.json` at setup, or
   resolve it on demand.
3. Flow 2 scope: local (current Plan) vs cross-plan (needs the WeveNova sync).
4. The tenant-inventory read surface - which fields it exposes (ids + names, or
   presence flags) and what permission it requires.
5. Research refresh cadence and where the research context is cached.

## Completion criteria (Step 1)

Step 1 is complete when:

- A sponsor request produces a grounded Plan of atomic, role-assigned Tasks.
- Workday connect decomposes into role-based Tasks read from its setup checklist
  (never a single "run /connect" Task).
- Flow 1 assigns a person to a grounded role; Flow 2 shows a person only the work
  still waiting on them, grouped by role.
- `/setup` output - the environment, the cloned agent, and any other id + name it
  records - is captured and back-propagates to downstream Tasks.
- The Plan stays valid on every write; the editable `ESS-scenario-plan.md` round-trips.
- The Plan works with WeveNova, the roles source, and the tenant inventory all absent.

## Key risks

| Risk | Mitigation |
|------|------------|
| The local Plan shape drifts from the WeveNova entities, turning the sync into a migration. | Keep the shapes identical to the Step 2 contract; no ADK-only scalars to reconcile. |
| Output capture mis-attributes pre-existing config as "produced by this task." | Only run the generic sweep with a real before-snapshot; otherwise pin just the recognized outputs. |
| The roles endpoint is unbuilt, blocking assignment. | Pool Tasks to a role / self-select for now; keep roles Learn-grounded and swap in the endpoint later. |
| The ESS Learn docs move again. | TOC-first crawl of the live section, with the vendored `reference/ess-docs/` snapshot as an offline fallback. |
| Scope expands to Step 2 persistence inside this PR. | Keep Step 1 local-first; sync, roles, and `/discover` land in separate PRs. |

---

**Design reference:** the full technical design (data model, flows, capture loop,
trust boundaries, open questions) is in
[`ADK-Plan-Generation-and-Task-Capture-DevDesign.md`](ADK-Plan-Generation-and-Task-Capture-DevDesign.md);
the sponsor/assignee flow diagram is rendered in
[`ess-planner-flows.png`](ess-planner-flows.png).
