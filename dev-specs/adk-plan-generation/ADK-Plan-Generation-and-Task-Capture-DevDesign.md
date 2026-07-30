# ADK `/planner` — Plan Generation, Role Assignment & Task Capture (Step 1)

How the ESS Agent Developer Kit turns a sponsor's intent into a structured, locally-stored **Plan** — grounded by *actively researching* Microsoft Learn — breaks it into atomic Tasks each **assigned to a role or a specific person**, lets a person discover the Tasks waiting on them, and keeps the Plan honest by capturing what each Task actually produced (starting with the environment `/setup` creates).

| | |
|---|---|
| **Status** | Draft for review |
| **Owner** | Harsheet Jain |
| **Audience** | ESS Agent Development Kit (ADK) engineers; WeveNova backend engineers (for the Step‑1 ↔ Step‑2 seam) |
| **Baseline** | `origin/main` of `Employee-Self-Service-Agent-Developer-Kit`, HEAD `72a24f8`. Everything described as "exists today" is verified on `main` (Appendix A). Feature‑branch code (`harsheetjain/env-discovery-inventory`, the `scripts/planner` commits) and locally‑generated runtime state are **not** ground truth. |
| **Companion** | *Plan Enrichment & Persistence* (Step 2) — the WeveNova‑side data‑modelling doc. This is Step 1 (the ADK side), written to produce exactly the shape Step 2 stores. Cross‑references are marked "Step‑2 §N" and track the **updated** Step‑2 draft (extended‑`Principal` assignment §7.4; single `Context` bag §7.1/§7.6; audit §15). |
| **Naming note** | The **command/skill** is **`/planner`** (renamed from `/plan`, which collides with VS Code's built‑in *Plan mode*). The **document it produces** is still called the **Plan** (`workspace/plan/plan.json`) — the noun matches the WeveNova `Plan` entity so the Step‑2 sync is a field copy, not a rename. In short: *the `/planner` skill authors a Plan.* |

---

## 1. Summary

A sponsor tells the ESS Maker Kit what they want — *"I want ESS to handle HR ticketing for employees, grounded in our Workday data."* Today the kit can `/connect` systems, `/create` topics, `/evaluate`, and `/flightcheck`, but it has **no notion of a plan**: nothing captures scenario intent, nothing sequences the work, nothing assigns it, and nothing remembers what a step produced.

Step 1 adds that missing brain: a new **`/planner` skill** that

1. **actively researches Microsoft Learn** — crawling the ESS documentation section via its Table of Contents (`toc.json`) — to build a fresh, grounded picture of what ESS can actually do and what each scenario requires (§7);
2. runs a short **grounded interview** to scope the rollout (§8);
3. emits a **Plan**: the sponsor's intent captured as a single open **Context bag**, plus a handful of **atomic Tasks** — *create an environment, connect Workday, author topics, generate evals* — each **assigned to a role and (optionally) a specific person** (§9, §10);
4. lets a person ask **"what am I assigned?"** and answers grouped by the roles they hold (§11); and
5. **captures what each Task produced** by observing the kit's own state after a skill runs, pinning artifacts (the `/setup` → `environmentId` hand‑off is canonical) onto the Plan so a later Task reads them straight off it (§12).

Four ideas run through the design:

- **Learn is researched at planning time, not treated as a static cache.** The planner crawls the live Learn TOC every run; the kit's vendored doc snapshot is only a seed hint and an offline safety net (§7). *(This design was written after confirming the vendored ESS Learn URL has already moved — see §7.1 — which is exactly why live research is primary.)*
- **The Plan is a local‑first, structured document with the same shape WeveNova will store.** It lives on disk under `workspace/plan/plan.json`; Step 2 lifts that shape into WeveNova with no re‑modelling (§5, §9, §15).
- **Assignment is role‑first, person‑optional, both retained.** A Task carries one extended `Principal` that can name a role, a person, or a person *acting as* a role — the model Step‑2 §7.4 settled (§10).
- **The Plan is kept honest by observing reality, not by trusting narration.** A completing Task's real side effect is detected from kit state and pinned, mirroring Step‑2 §7.3/§9 (§12).

Step 1 is the **greenfield** path — an empty tenant, plan from intent. A later flow reuses a tenant **inventory** (from a prior Plan or a `/discover` step) to *improve* an existing Plan; this doc keeps a clean seam for it (§14) but does not build it.

---

## 2. Goals & non‑goals

**Goals**

1. Add a **`/planner`** skill that generates a structured Plan from a sponsor's intent, grounded by **actively researching Microsoft Learn** (§7) and refined by a **bounded interview** (§8).
2. Represent the Plan as **atomic Tasks**, each performed by a single **action** — *usually* a kit skill, but sometimes a manual/portal/admin or external step with no kit skill — and **assignable to a role, a person, or a person acting as a role** via one extended `Principal` (§9, §10).
3. Support **Flow 1 (assign at creation):** the Task's **role is grounded from the Learn docs** (not named by the sponsor), the ADK lists the people who hold it, the sponsor picks one, and the Task is assigned to that person with the role retained (§10).
4. Support **Flow 2 (discover my work):** a person asks what they're assigned and sees Tasks **grouped by each role they hold**, covering people with more than one role (§11).
5. **Capture Task outputs** for each key a Task declares in `produces` (those keys grounded from the Learn doc, §7.6): fill each value either by **observing kit state** (the `/setup` → `environmentId` hand‑off) **or by asking the assignee** to supply it (plus any extra info they give us) — and **pin** them onto the Plan for later Tasks to read (§12).
6. Store the Plan **locally, structured, readable**, in the **same shape** WeveNova stores (Step‑2 §7), so Step 2 is a sync (§9, §15).
7. Keep the ADK **decoupled** from WeveNova, tenant inventory, **and the roles source**: the local Plan is authoritative and works with all three absent; each is an optional, swappable seam (§13, §14).
8. Do all of this **additively**, reusing the kit's patterns — the `SKILL.md` + `.prompt.md` model, the `.local/config.json` gate, the `workspace/` working copy, the `checkpoint → … → push` pipeline, the todo‑list progress tool.

**Non‑goals**

- **The WeveNova persistence schema and MCP wiring** (owned by Step 2). This doc produces the shape and defines the client‑side sync seam (§15).
- **Tenant inventory and `/discover`** (a separate workstream). Greenfield ships with the inventory contract absent (§14).
- **Building the roles source.** The role catalogue and role‑membership directory are a separate workstream (Step‑2 §7.4, open #7). This doc defines the **narrow client contract** the planner calls and ships **absent‑safe** (§10.4, §14).
- **Provisioning code for environments.** Whether `/setup` creates or binds a Dataverse environment is infra; §12 only relies on `/setup` leaving a detectable signal (`config.json`), which it already does.
- **Runtime agent behaviour.** We define the Plan the kit authors, not how the deployed ESS agent answers employees.

---

## 3. Actors and the end‑to‑end flow

| Actor | Role on the Plan | What they do | What they touch |
|---|---|---|---|
| Sponsor / agent owner | Plan author (Plan Editor) | States intent, answers the interview, **picks the person** for each Task (the role is grounded from Learn, §7/§10) | The whole Plan |
| Power Platform / IT admin | Task assignee | Runs `/setup`; confirms the produced `environmentId` (§12) | Runs a Task; artifact lands on the Plan |
| Integration owner | Task assignee | Runs `/connect` for Workday/ServiceNow | Runs a Task; connection/app artifacts land on the Plan |
| Eval author | Task assignee | Runs `/evaluate`; **reads** the `environmentId` off the Plan | Reads the Plan; eval artifact lands on the Plan |
| *Any assignee* | Task discovery | Asks the ADK **"what am I assigned?"** → sees Tasks grouped by role (§11) | Reads the Plan / synced Tasks |

**Soft assumption, not a hard one.** For the MVP we assume the sponsor who authors the Plan *also holds Power Platform admin access*, so one person can both write the Plan and run the `/setup` Task. **This is a convenience, not a design constraint.** The Task is assigned via a `Principal` that carries the (Learn‑grounded) role (§10); whether the sponsor happens to hold it is incidental. A different admin can run the Task and the same capture happens (§12). Nothing in the schema assumes a single operator.

**The two things that must be true (mirrors Step‑2 §3):** a downstream Task reads a value an earlier Task produced *without re‑discovering it*, and every actor sees the *same* Plan document.

---

## 4. What exists on `main` (the only baseline)

Verified on `origin/main` (Appendix A). The kit is a **Copilot Chat grounding workspace**, not a running service: "skills" are Markdown playbooks the chat agent reads and follows, backed by Python scripts for the deterministic parts.

- **Skill model.** Each capability is a `src/skills/<name>/SKILL.md` playbook (sometimes with `stepN.md` sub‑files and a `tasks.md` checklist), invoked by a `.github/prompts/<name>.prompt.md` slash command and routed from `.github/copilot-instructions.md`. Existing skills: `onboarding` (`/setup`), `connect`, `topics/*`, `workflows/*`, `evaluations/*`, `flightcheck`, `cleanup` (`/scan`), `troubleshoot`, `backup/restore-template-configs`. **There is no `/plan` or `/planner` skill on `main`** (`git grep` finds only a VS Code *Plan mode* tip in `menu.prompt.md`).
- **The gate + local state.** `.local/config.json` (written atomically by `scripts/setup.py`) records `setup:"complete"`, the active `agent`, the `agents[]` array, and `dataverseEndpoint`. The copilot‑instructions gate every action on this file existing. `workspace/agents/<slug>/` holds the local working copy of the deployed agent. On `main`, `workspace/` tracks only `agents/.gitkeep` and `onboarding/.gitkeep` — **no `plan/`, no `inventory/`.**
- **Grounding corpus.** `src/reference/ess-docs/` is a **vendored snapshot of MS Learn ESS docs** (snapshot dated 2026‑04‑29; `README.md` records the source URL + layout). `src/examples/ess-samples/` holds real topic/config samples.
- **The mutation pipeline.** Every change follows **Checkpoint → Local edit → Scan → Dry run → Push → Verify** (`scripts/checkpoint.py`, `scripts/push.py`). Local edits aren't live until pushed.
- **Environment awareness already exists.** `scripts/list_environments.py` and the `scripts/flightcheck/` package (`pp_admin_client.py`, `powerplatform_client.py`, `environment.py`, `licensing.py`, `graph_client.py`, …) can enumerate environments, read licensing, and probe connections. Step 1 **reuses** these.
- **Progress tracking.** Skills already drive "the todo list tool to track progress" (e.g. `evaluations/create`). `/planner` does the same.

### 4.1 What isn't on `main`, and how we treat it

An earlier branch prototyped a planner engine, a discovery package, and `workspace/plan|inventory/*.json`. **None is on `main`** — it was cleared so this design starts from the authoritative baseline. We treat it as *prior art*, never a dependency, and re‑derive the Plan shape from the durable Step‑2 contract.

---

## 5. Where Step 1 sits relative to Step 2 (and why local‑first)

```
        ┌──────────────────────  ADK  (this doc, Step 1)  ──────────────────────┐
Sponsor │  /planner  ─grounded interview─►  Plan (local, structured)             │
 intent │     ▲                                    │  workspace/plan/plan.json     │
        │     │ RESEARCH (primary)                 │  = same shape as WeveNova Plan │
        │  learn.microsoft.com  ──TOC crawl──►     │                               │
        │  src/reference/ess-docs (seed + offline) ▼                               │
        │                              Tasks (atomic; role/person via Principal)    │
        │  roles endpoint (unbuilt seam) ─holders/roles─► assign (Flow 1) / find (Flow 2)
        │  /setup ─provisions env─►  .local/config.json  ─ADK detects─► pin artifact  │
        └────────────────────────────────────────┬──────────────────────────────────┘
                                                  │  best-effort sync (§15)
                                                  ▼
        ┌────────────────────  WeveNova  (companion, Step 2)  ────────────────────┐
        │  Project → Plan → Task  (JSON-on-record) + Outputs ledger + MCP tools     │
        └────────────────────────────────────────────────────────────────────────────┘
```

**Local‑first is deliberate.** The kit already runs off local files with cloud calls layered on top. The Plan follows the same discipline: **authoritative on disk**, works with WeveNova / inventory / the roles source absent, syncs opportunistically (§15). This mirrors Step‑2's own stance (Step‑2 §6.3, Option B): *put the derived value on the dependent record; sync/refresh deliberately; never tie a read to whether the remote is up.*

---

## 6. The `/planner` skill — shape and routing

Additive, following the existing skill pattern exactly:

- **`.github/prompts/planner.prompt.md`** — the `/planner` slash command.
- **`src/skills/planner/SKILL.md`** — the playbook, with sub‑files: `research.md` (the Learn crawl, §7), `interview.md` (§8), `model.md` (the Plan schema + writer rules, §9), `assign.md` (Flow 1, §10), `mytasks.md` (Flow 2, §11), and `capture.md` (§12).
- **Routing** — add a `/planner` row to `.github/copilot-instructions.md`'s skill‑routing table and to `menu.prompt.md`.
- **Gate** — like every skill, `/planner` first reads `.local/config.json`. But it is the **one skill allowed to precede setup**: on greenfield the environment doesn't exist yet, and the first Task the planner emits is usually "run `/setup`". So if `setup` isn't complete, `/planner` still runs.
- **Progress** — the skill drives the todo‑list tool for its phases (research → interview → draft → assign → emit).

`/planner` **orchestrates**; it never re‑implements `/setup`, `/connect`, etc. A Task points at an **action** — *usually* an existing kit skill (running it is how the Task gets done), sometimes a manual/portal/external step with a grounded doc pointer (§10). This keeps `/planner` thin and every kit behaviour in one place — the discipline Step‑2 §13.2 applies to the MCP loopback.

---

## 7. Grounded research: the planner actively researches Microsoft Learn

The planner's first job, and a **primary planning activity — not a fallback**. It must reason from *what ESS actually supports today*, or it will invent scenarios the platform can't deliver and ask irrelevant questions. It does that by **crawling the live ESS Learn section**, guided by that section's Table of Contents.

### 7.1 Why live research, not the vendored cache

The kit vendored the ESS Learn docs (snapshot 2026‑04‑29). That snapshot **drifts**: verified while writing this doc, the section's old URL (`…/copilot/microsoft-365/employee-self-service`) now **404s and 301‑redirects** to a new path (`…/microsoft-365/copilot/employee-self-service`), and the live section contains pages the snapshot doesn't (`workday-simplified-setup`, `developer-kit-overview`, `facilities-*`). So the vendored docs are demoted to two supporting roles only:

- **A seed hint** — they tell the planner the section exists and roughly where.
- **An offline safety net** — if the web is unreachable, the planner grounds on the snapshot *for availability*, and says so.

Everything else is **live**. This is the correction to any "vendored‑first, web‑as‑fallback" reading: for the planner, **Learn is the primary corpus**; the snapshot is a fallback only for uptime, never for priority.

### 7.2 What a TOC is, and why it is the spine of the crawl

**TOC = Table of Contents.** Every Microsoft Learn section publishes a machine‑readable `toc.json` at its base — the same tree that renders as the left‑nav. It lists every page as nested nodes:

```jsonc
{ "items": [
  { "href": "overview", "toc_title": "Introduction to Employee Self-Service agent" },
  { "toc_title": "Integrate external systems", "children": [
      { "href": "servicenow", "toc_title": "Integrating ServiceNow",
        "children": [ { "href": "servicenow-hrsd-itsm", "toc_title": "ServiceNow HRSD and ITSM" }, … ] },
      { "toc_title": "Workday", "children": [
          { "href": "workday-simplified-setup", "toc_title": "Simplified Workday integration setup" }, … ] }
  ] }, … ] }
```

So the TOC **is** the parent/child/sibling graph, authoritative and complete, with real `href`s. The crawl fetches `toc.json` **first** and uses it as its spine — never guessing URLs, never scraping rendered nav. (The live ESS `toc.json` returns **59 pages**; §17 shows the real tree.)

### 7.3 Link taxonomy — how the planner classifies links

For any node (from the TOC, or a link found in a fetched page that resolves to a TOC `href`):

| Class | Identified by | Crawl action |
|---|---|---|
| **Child** | a node's `children[]` (e.g. `workday` → `workday-extensibility`, `workday-reports/*`) | drill in **iff the parent is relevant** to intent |
| **Sibling** | same‑level entries under one parent (`workday` ↔ `servicenow` ↔ `sapsuccessfactors`) | titles are free from the TOC; **fetch a sibling only if its title matches intent** |
| **Parent / breadcrumb** | the enclosing node / `metadata.breadcrumb_path` | used to locate the section base; not re‑fetched |
| **Related / in‑body** | markdown links inside a fetched page that **resolve to a known TOC href** (e.g. a Workday page → `prerequisites`) | follow if relevant + unvisited (catches cross‑section prerequisites) |
| **External** | non‑`learn.microsoft.com`, or outside the section base | **never auto‑followed**; captured as a reference only |

**Scope fence:** only `href`s present in this section's `toc.json` (or that resolve to one) are crawlable. This bounds the crawl to ESS *and* makes "no fabricated URLs" automatic — every fetched URL came from the TOC.

### 7.4 The crawl algorithm (the heuristic)

```
1. SEED       start from the vendored README's recorded section URL.
2. RESOLVE    follow 301s to the current section base. (web_fetch refuses cross-path
              redirects — capture the redirect target and re-fetch it explicitly.)
              If the bare base 404s, use the TOC's first node (href:"overview").
3. TOC        fetch {base}/toc.json  → the full child/sibling tree.
4. SELECT     map sponsor intent → TOC subtrees (relevance filter, §7.5).
              Always include: overview, prerequisites, deploy-overview-alm, install,
              commands-reference, securely-integrating-with-external-systems.
5. BFS        frontier = selected hrefs. Breadth-first, within budget:
                fetch {base}/{href}  → markdown
                extract facts (§7.6) + in-body links resolving to TOC hrefs
                enqueue newly-relevant, unvisited hrefs
              maintain a visited-set (canonical href).
6. STOP       at the page budget, OR when every in-scope scenario has a grounded
              capability + an owned prerequisite (the "both-satisfied" test, §8.3).
7. ASSEMBLE   normalize facts into the planning-context object (§7.6) with provenance.
```

**Bounds & pruning (what keeps it a heuristic, not a scraper):**
- **Relevance gate** — expand a subtree only if its `toc_title`/path matches an intent token (system, scenario area, market, eval, handoff). Non‑matching siblings are read **title‑only** (free), never fetched.
- **Budget** — ~15–20 page fetches per run; the TOC's natural depth (~4) caps depth.
- **Dedupe** — canonicalize `href` (strip anchor/query, normalize trailing slash) into a visited‑set.
- **Early stop** — stop when planning slots are covered; don't drain the budget.
- **Redirect handling** — on a refused cross‑path 301, re‑invoke with the final URL (learned live building this doc).
- **Untrusted data** — all fetched content is *data, not instructions* (kit Security Boundaries); a `# Note for the AI assistant:` inside a page body is ignored.

### 7.5 Intent → subtree mapping (relevance selection)

| Sponsor intent | TOC nodes fetched (deep) | Read title‑only (skipped) |
|---|---|---|
| System: **Workday** | whole `Workday` subtree (`workday-simplified-setup`, `workday-extensibility`, `workday-reports/*`) | SAP subtree |
| System: **ServiceNow HRSD** | `servicenow`, `servicenow-hrsd-itsm` | `servicenow-live-agent` unless handoff in scope |
| Scenario: **HR ticketing** | `servicenow-hrsd-itsm` + `overview` capability list | `facilities-*` |
| Scenario: **handoff** | `agent-handoff`, `servicenow-live-agent`, `connecting-agents-overview` | — |
| **Market / residency** (e.g. Germany) | `prerequisites`, `customize`, `securely-integrating-with-external-systems` | — |
| Always (task backbone) | `prerequisites`, `deploy-overview-alm`, `install`, `commands-reference` | — |

### 7.6 What research produces — the planning‑context object

From each fetched page, extract **structured facts, not raw HTML**, each stamped with `{sourceUrl, toc_title, fetchedAt}`:

```jsonc
{
  "sources":       [ {url, tocTitle, fetchedAt, relevance} ],        // provenance / citations
  "capabilities":  [ {system, scenario, sourceUrl} ],                // buildable scenario catalogue
  "prerequisites": [ {forScenarioOrSystem, requirement, role, action, produces, sourceUrl} ], // → Tasks
                     // role     = responsible role, GROUNDED FROM THE DOC (not asked of the sponsor) — §10
                     // action   = how it's done: {kind:"kitSkill"|"manual"|"portal"|"external", skill?, ref?} — §10
                     // produces = output keys this step yields (e.g. "primaryEnvironment","entraApp"),
                     //            GROUNDED FROM THE DOC — filled at completion by observe OR ask (§12)
  "constraints":   [ {note, sourceUrl} ],                            // e.g. "Workday requires Entra SSO"; residency
  "openItems":     [ {question, why} ]                               // gaps Learn didn't answer → interview Qs
}
```

This maps 1:1 onto the Plan: `capabilities → Context (group scenarioContext)`, `prerequisites → Tasks (task.action + grounded role — both extracted from the docs, §10)`, `constraints → market/acceptance Context entries`, `openItems → interview questions`. Every derived entry carries `provenance.source = "Agent"` + the source URL. The planner **caches** this object (e.g. `workspace/plan/research-context.json`) so a session is deterministic and re‑runs are cheap; it re‑crawls on explicit refresh or when intent changes, and **diffs the live TOC against the vendored snapshot** to flag drift (live wins).

### 7.7 Determinism, not search‑for‑its‑own‑sake

Mirrors Step‑2 §7.7. The value of research is a **consistent** Plan for the same intent — the planner grounds on decided facts (this integration, these supported scenarios, this prerequisite) instead of re‑inferring and drifting. Research narrows; the interview decides; the Plan records. People/role facts are **never** sourced from web research — they come from the roles endpoint + Work IQ (§10.4).

---

## 8. The interview: what questions to ask

The planner asks the **fewest questions that let it commit a buildable, scoped, assigned Plan** — and both sides must be satisfied: the **sponsor** that it captures what they want, the **ADK** that every scenario is grounded, every prerequisite has a Task, and every Task has an owner.

### 8.1 Elicitation model — grounded slot‑filling

Model it as **slot‑filling**: the planner has slots it must fill to emit a Plan; research (§7) both proposes candidate values and decides which slots apply. Ask about a slot only when (a) it's required to scope, sequence, or assign work, and (b) research didn't already answer it. Principles: **propose, don't interrogate** (react to a grounded default); **batch by theme, one theme at a time**; **stop early**.

### 8.2 The slot / question bank

Intent answers become **`Context` entries** (§9.2), grouped:

| # | Question (grounded example) | Context `group` |
|---|---|---|
| 1 | "In one sentence — what should this agent do, and for whom?" | `objective` |
| 2 | "Which systems hold that data — Workday, ServiceNow, SharePoint?" | `scenarioContext` (targetSystem) |
| 3 | "From {system} I can support {grounded scenario list}. Which are in scope for wave 1?" | `scenarioContext` (area/jtbd) |
| 4 | "Employees only, or managers too?" | `scenarioContext` (persona) |
| 5 | "Rolling out to a specific market or wave first (e.g. Germany, pilot group)?" | `market` |
| 6 | "What business outcome measures success (e.g. deflect 30% of HR tickets)?" | `businessGoals` |
| 7 | "How will you know a scenario is done — pilot‑ready? production‑signed‑off?" | `acceptanceCriteria` |
| 8 | "Brand‑new environment, or do you already have ESS running?" | (greenfield vs enrichment branch, §14) |

**Assignment question (Flow 1, per Task — §10).** The planner does **not** ask the sponsor which role a Task needs — the **role is grounded from the Learn docs** during research (§7.6). The only assignment question is *who*:
- 9. *"{title} is a **{grounded role}** task. People with that role: {list from the roles endpoint}. Assign to whom — or leave it open to the {role} pool?"* → assign a person (role retained) or leave pooled.

Questions **1–3** are almost always asked; **4–7** as scope warrants; **8** is one branch; **9** runs per Task during the assignment pass. A typical greenfield interview is **4–6 intent turns + a quick per‑task assignment pass**.

### 8.3 The "both satisfied" stop condition

End the interview when:

- **Sponsor‑satisfied:** the sponsor accepted the scenario list + goals (an explicit *"looks right"*).
- **ADK‑satisfied:** every in‑scope scenario resolves to a grounded, supported capability; every scenario's prerequisites are represented by a Task; and **every Task is either assigned to a person or pooled to a role**. No scenario has an unmet, unowned prerequisite.

If ADK‑satisfied fails (an unsupported scenario, or a prerequisite nobody will own), the planner surfaces it rather than emitting an unbuildable Plan.

---

## 9. The local Plan model (structured, on disk)

*Where the "local structured" plan is stored, for now*, plus its shape. **The shape is Step‑2's model verbatim, so Step 2 is a sync (§15), not a re‑model.** Two Step‑2 updates are reflected here: **all intent folds into one `Context` bag** (Step‑2 §7.1/§7.6), and **assignment is one extended `Principal`** (Step‑2 §7.4).

### 9.1 Storage location and files (for now)

```
workspace/
  plan/
    plan.json               # the structured Plan — the source of truth
    summary.md              # human-readable render of plan.json (for the sponsor in chat / PR)
    research-context.json   # cached Learn-research corpus (§7.6), regenerated on refresh
```

- `workspace/plan/plan.json` is the authoritative local Plan. `workspace/` is git‑ignored runtime state (like `workspace/agents/`), so the Plan is per‑maker and never accidentally committed. A `.gitkeep` seeds `workspace/plan/` on `main`.
- `summary.md` is generated (never hand‑edited): scenarios, Tasks + assignees + state, pinned outputs. This is what the sponsor sees.
- **Writer discipline:** `plan.json` is written **atomically** (temp‑file + `os.replace`), exactly like `setup.py` writes `config.json`. A small `scripts/planner/` package owns read/write/validate; the skill never hand‑serialises JSON (mirrors the `scripts/flightcheck/` package layout).

### 9.2 The schema (aligned to the updated Step‑2 §7)

```jsonc
{
  "schemaVersion": 1,
  "planId": "",            // empty until synced to WeveNova (§15); locally the file is the id
  "projectId": "",
  "status": "Draft",       // Draft → Active → Completed (master lifecycle)

  // ── ALL sponsor/agent intent lives in ONE open Context bag (Step-2 §7.1/§7.6) ──
  // objective, businessGoals, scenario/system intent, market, acceptanceCriteria — all here.
  "context": [
    { "key": "objective", "value": "ESS HR ticketing for employees on Workday", "group": "objective",
      "description": "Plain-language goal the sponsor stated",
      "provenance": { "source": "User", "addedBy": {"type":"User","id":"<sponsor oid>"}, "addedAt": "…" } },
    { "key": "deflectTickets", "value": "Deflect 30% of HR tickets in 6 months", "group": "businessGoals",
      "description": "Primary business outcome", "provenance": { "source": "User", … } },
    { "key": "area", "value": "HR-Ticketing", "group": "scenarioContext",
      "description": "ESS scenario area", "provenance": { "source": "Agent", "addedBy": {"type":"Service","id":"planner"}, … } },
    { "key": "targetSystem", "value": "ServiceNow HRSD", "group": "scenarioContext", "provenance": { "source": "Agent", … } },
    { "key": "market", "value": "DE", "group": "market",
      "description": "Market this rollout targets first",
      "provenance": { "source": "User", "addedBy": {"type":"User","id":"<sponsor>"}, "addedAt": "…",
                      "updatedBy": {"type":"User","id":"<pm>"}, "updatedAt": "…" } },   // creator + last editor
    { "key": "topTicketTypes", "value": "Resolve the top-10 HR ticket types end to end",
      "group": "acceptanceCriteria", "provenance": { "source": "User", … } }
  ],
  // Each ContextEntry: key + SCALAR value + group + description + typed provenance
  //   provenance = { source: User|Agent|Discovered, addedBy: Principal, addedAt, updatedBy?: Principal, updatedAt? }
  // Overwrite-in-place by key: a re-write preserves addedBy/addedAt, refreshes updatedBy/updatedAt.

  // ── Tasks: atomic; one extended Principal each (Step-2 §7.4) ──
  "tasks": [
    { "id": "T1", "title": "Create Power Platform environment & run setup",
      "description": "Run /setup to provision/bind the Dataverse environment.",
      "action": { "kind": "kitSkill", "skill": "onboarding" }, // HOW it's done — here a kit skill (§10)
      "assignedTo": { "type": "User", "id": "<paul oid>",  // assigned to a PERSON…
                      "user": { "oid": "<paul oid>" },
                      "role": { "roleId": "power-platform-admin" } },  // …ACTING AS a Learn-grounded role
      "state": "NotStarted",                              // NotStarted → InProgress → Completed (+ reopen)
      "produces": ["primaryEnvironment"], "consumes": [] },

    { "id": "T2", "title": "Connect Workday",
      "action": { "kind": "kitSkill", "skill": "connect" },
      "assignedTo": { "type": "Role", "id": "integration-owner",     // OPEN TO A ROLE (pool) — nobody yet
                      "role": { "roleId": "integration-owner" } },
      "state": "NotStarted", "produces": ["workdayConnection","workdayEntraApp"], "consumes": ["primaryEnvironment"],
      // OPTIONAL read-back-only step display — the skill fills this at RUNTIME from its tasks.md (§10.1).
      // Not a sub-entity, not promoted, not the Task boundary; empty until the skill runs.
      "checklist": [ { "label": "Admin setup complete", "done": false },
                     { "label": "Connection verified",  "done": false } ] },

    { "id": "T3", "title": "Generate evals",
      "action": { "kind": "kitSkill", "skill": "evaluations" },
      "assignedTo": { "type": "User", "id": "<ann oid>", "user": { "oid": "<ann oid>" },
                      "role": { "roleId": "eval-author" } },
      "state": "NotStarted", "produces": ["evalSuite"], "consumes": ["primaryEnvironment"] },

    { "id": "T4", "title": "Publish the agent",
      // NOT a kit skill — a portal/admin step; the planner points at the grounded Learn doc.
      "action": { "kind": "portal", "ref": "https://learn.microsoft.com/…/employee-self-service/publish" },
      "assignedTo": { "type": "Role", "id": "power-platform-admin", "role": { "roleId": "power-platform-admin" } },
      "state": "NotStarted", "produces": [], "consumes": ["primaryEnvironment"] }
  ],

  // ── The single artifact ledger — the "forked state" (Step-2 §7.3) ──
  "outputs": [
    // Populated by the capture loop (§12). Empty at mint. Keyed by key; supersede-on-rewrite.
    // { "key":"primaryEnvironment", "kind":"Environment",
    //   "attributes":{ "environmentId":"d3f1…", "environmentUrl":"https://…" },
    //   "inventoryRef":"Environment:d3f1…", "producedByTaskId":"T1",
    //   "provenance":{ "source":"Agent", "addedBy":{…}, "addedAt":"…" }, "state":"Active" }
  ],
  "notes": []
}
```

**Extended `Principal` — the three assignment states (Step‑2 §7.4):**

| State | `assignedTo` shape | Meaning |
|---|---|---|
| **Pool** | `{ type:"Role", id:R, role:{roleId:R} }` | Open to every holder of R; no person yet |
| **Claimed** | `{ type:"User", id:P, user:{oid:P}, role:{roleId:R} }` | A holder of R picked it up; role retained |
| **Direct‑for‑role** *(Flow 1 result)* | `{ type:"User", id:P, user:{oid:P}, role:{roleId:R} }` | Sponsor assigned P directly; role retained |
| *(plain person)* | `{ type:"User", id:P, user:{oid:P} }` | No role |

**Field‑for‑field alignment with Step 2** (so the sync is mechanical):

| Local `plan.json` | WeveNova (Step‑2) | Note |
|---|---|---|
| `context[]` (ContextEntry) | `Plan.Context[]` (§7.1/§7.6) | Single open bag; scalar values; `group`; typed provenance. Absorbs objective/goals/scenario/market/acceptance. |
| `tasks[].assignedTo` (extended Principal) | `Task.AssignedTo` Principal (`Role`/`User`) (§7.4) | Three states above; `AssignedToRoleId`/`AssignedToType` promoted server‑side. |
| `tasks[].produces/consumes` | `Task.Produces/Consumes` (§7.2) | Keys, **grounded from the Learn doc (§7.6)**; each `produces` key is filled at completion by observe‑or‑ask (§12). Phase‑2 dependency wiring. |
| `outputs[]` (PlanArtifact) | `Plan.Outputs[]` (§7.3) | `key`, `kind`, `attributes` (pinned), `inventoryRef`, `producedByTaskId`, `provenance`, `state`. |
| `tasks[].checklist[]` *(optional)* | *(client‑only)* | Read‑back‑only step display, filled by the skill at runtime from its `tasks.md` (§10.1). Not a WeveNova entity/scalar; maps into the Task description or client metadata, or is dropped, on sync. |

The ADK‑only fields are `task.action` and the optional `task.checklist[]` (§10.1). `task.action` is **how** the Task is performed: `{kind: kitSkill|manual|portal|external, skill?, ref?}` — usually a kit skill (`/setup`, `/connect`, `/evaluate`), sometimes a manual/portal/admin or external step with a grounded Learn/portal `ref` (registering an Entra app, publishing the agent). The action, the Task's role, and its `produces` keys are all **grounded from the Learn docs** during research (§7.6), not asked of the sponsor. Both fields are client execution/display detail; on sync they map into the Task description/client metadata, never a WeveNova promoted scalar.

### 9.3 Invariants (mirror Step‑2 §8)

- `outputs[].key` is unique per Plan; re‑producing a key (a `/setup` re‑run) **supersedes** the prior artifact (`state:Superseded`), never duplicates.
- The ledger is **append‑and‑supersede**, never delete — history survives for audit.
- "This task's outputs" is the ledger filtered by `producedByTaskId` — no second copy on the task (Step‑2 §7.2).
- `context[]` is **overwrite‑in‑place by key** (latest state only; provenance keeps creator + last editor) — contrast the ledger's keep‑superseded rule.
- Caps (writer‑enforced): `MaxTasks` (~50), `MaxOutputs`, `MaxContextEntries`, key/value/description length caps (following `Project.Metadata` caps).
- `checklist[]` is **optional display state**, populated at runtime by the skill (§10.1) — never the Task boundary and never a Plan sub‑entity; absent/empty is valid, and it carries no ledger‑style history.

### 9.4 Scenario dependencies live in the Context bag (no new collection)

Some scenarios must be deployed in an order the sponsor should see — the PM spec's canonical case is **HR knowledge before HR ticketing** (the agent answers from knowledge first and only creates a ticket when unresolved). This is a *scenario→scenario* dependency, distinct from the scenario→prerequisite coupling that already falls out of task `produces`/`consumes`.

Because everything intent‑shaped already lives in the **one open Context bag** (§9.2), a dependency is modelled as **more Context entries — not a new typed collection**. Adding a `scenarioDependencies` array would reintroduce exactly the typed‑field‑per‑concept burden Step‑2 collapsed away. Instead:

- A **scenario in scope** is a Context entry in group `scenario` (`key` = scenario id like `hr-ticketing`, `value` = label).
- A **dependency edge** is a Context entry in group `scenarioDependsOn` whose `key` encodes `"{dependent} -> {prerequisite}"` and whose scalar `value` is the kind (`requires` | `recommends`); the `description` carries the rationale/citation, and provenance names the source (`Agent` when the planner asserts it from the PM spec/research, `User` when the sponsor states it). Values stay scalar and keys stay unique — the same open‑bag rules as every other entry.

The planner keeps a small grounded **seed** of PM‑spec dependencies (`KNOWN_SCENARIO_DEPENDENCIES`, currently just knowledge→ticketing) so it can advise the sponsor without re‑deriving; the seed is grounding data, not Plan schema. `unmet_scenario_dependencies()` compares in‑scope scenarios against their (captured + seeded) edges and returns the ones whose prerequisite isn't in scope. **Exposure:** the interview surfaces unmet dependencies to the sponsor ("deploy HR knowledge before ticketing — add it?"), and the summary renders a *Scenario dependencies* table with a met / MISSING status, so ordering is visible to everyone on the plan. Enforcement then rides the existing task DAG (the knowledge task produces what the ticketing work consumes). Because edges are ordinary Context entries, they round‑trip, read back, and sync exactly like the rest of the bag — the intelligence is in the agent's readback, not in a rigid schema.

---

## 10. Tasks: atomic, performed by an action, assigned by a grounded role (Flow 1)

### 10.1 What "atomic" means — and why a Task is not a skill's steps

A Task is the **smallest unit that (a) one owner can complete end‑to‑end and (b) maps to a single action run to completion** — *usually* one kit skill (`/setup`, `/connect`), but sometimes a manual/portal/admin or external step with **no** kit skill (registering an Entra app in the portal, publishing the agent, a data‑residency sign‑off).

**A Task is not a skill's internal steps.** A kit skill like `connect` is itself a multi‑step procedure with its own checklist (`connect/workday/tasks.md`: *environment configured → admin setup → connection verified*) and step files (`step1/2/3.md`). Those steps sit **one plane below** the Plan — they are how a single assignee *executes* one Task in one session, owned and tracked by the skill (its `.local/connect/workday/tasks.md` state + the todo‑list), not units of the rollout. So "Connect Workday" is **one Plan Task** (`action: kitSkill connect`); its steps do **not** become sibling Tasks, and we do **not** add both "run connect" *and* its checklist items as Tasks (that double‑counts). The Plan records the Task's state and its produced artifacts (`workdayConnection`, `workdayEntraApp`) — stable **however many** internal steps ran.

Three reasons the Task stays at skill granularity, not step granularity:
- **One assignee.** Every connect step is done by the *same* person in one sitting; a Task has one assignee, so steps don't earn separate Tasks.
- **Steps are runtime‑variable and unknowable at plan time.** `connect` detects *simplified vs legacy* Workday in step1 and branches to very different step counts — you can't enumerate the steps when the Plan is authored.
- **Stability + one home for behaviour.** If the skill adds/removes a step the Plan is unaffected; the skill owns its procedure once (§6).

**The one reason to split a Task — a role boundary, never a step boundary.** Split "Connect Workday" into more than one Plan Task **only** when a portion needs a *different owner*. Research grounds a role per prerequisite (§7.6), so if the docs put *register the Entra app* on an `entra-admin`, the *Workday API‑client / ISU / security* work on a `workday-admin`, and *create the connection & verify* on an `integration-owner`, those become separate Tasks (each a slice of the skill, or a portal step). If one admin holds all of it (the MVP soft assumption, §3) it collapses to a single "Connect Workday" Task. **Role boundary = Task boundary; the skill's steps are never the boundary.**

**Step visibility without making Step first‑class.** "Step is not a first‑class entity" and stays that way — there is no Plan→Task→Step tree (rejected, §16). When the Plan needs to *show* progress inside a Task, the skill fills an optional, read‑back‑only `checklist[]` on the Task (§9.2) at runtime from its `tasks.md` — display state, not addressable entities, with no new entity and no migration.

### 10.2 Task → action + role map (grounded from Learn)

| Task (typical greenfield) | Action (`task.action`) | Produces | Consumes | Role (grounded from Learn) |
|---|---|---|---|---|
| Create/bind env & run setup | kitSkill `onboarding` (`/setup`) | `primaryEnvironment` | — | `power-platform-admin` |
| Check readiness | kitSkill `flightcheck` (`/flightcheck`) | `readinessReport` | `primaryEnvironment` | `power-platform-admin` |
| Register Entra app *(if not via connect)* | **portal** (Learn / Azure portal doc) | `entraApp` | `primaryEnvironment` | `entra-admin` |
| Connect Workday | kitSkill `connect` (`/connect`) | `workdayConnection`, `workdayEntraApp` | `primaryEnvironment` | `integration-owner` |
| Connect ServiceNow | kitSkill `connect` (`/connect`) | `servicenowConnection` | `primaryEnvironment` | `integration-owner` |
| Author scenario topics | kitSkill `topics/create` (`/create`) | `topic:<name>` | env + connections | `maker` |
| Generate evals | kitSkill `evaluations/create` (`/evaluate`) | `evalSuite` | `primaryEnvironment` | `eval-author` |
| Publish the agent | **portal/admin** (Learn publish doc) | — | built agent | `power-platform-admin` |

The planner sequences these actions; **the role in the last column and the `produces` keys are extracted from the Learn docs during research (§7.6), not hardcoded kit defaults and not asked of the sponsor.** Where a kit skill exists the Task runs it; where none does (portal/manual rows) the Task carries a grounded doc `ref` and the assignee follows it. `produces`/`consumes` drive ordering + "blocked until produced" UX (Step‑2 §7.2, phase‑2); each key is what the capture loop (§12) fills and pins.

### 10.3 Flow 1 — assign at creation (grounded role → pick a person)

The sponsor's flow. For each Task the **role is already grounded from the Learn docs** (§7.6, §10.2) — the sponsor is **not** asked to name or confirm it. The sponsor's only assignment act is picking the person:

1. **Role (grounded, not asked).** The Task already carries its role from research. The planner states it for transparency — *"this is a `{role}` task"* — but doesn't ask the sponsor to choose it.
2. **List the holders.** ADK calls the roles endpoint `listHolders(role)` → the people who hold that role.
3. **Sponsor picks a person — or pools it.**
   - Picks person **P** → write **direct‑for‑role**: `assignedTo = { type:"User", id:P, user:{oid:P}, role:{roleId:R} }`. Assigned to P, **role R retained** (so Flow 2 still groups it under R, and provenance survives).
   - "Leave it open to the role" → write **pool**: `assignedTo = { type:"Role", id:R, role:{roleId:R} }`. Any holder of R can later claim it (→ claimed state).
4. **Validate.** `isValidRole(R)` (and, on a claim, `holds(P,R)`) gate the write; absent‑safe (§10.4).

This realises Flow 1 — *"the role comes from the docs, see the people who hold it, pick one, assign to that person"* — on the extended `Principal`, keeping both the person and the (grounded) role.

### 10.4 The roles source — a narrow, unbuilt, absent‑safe seam

The roles endpoint is **unbuilt** (Step‑2 §7.4, open #7). The ADK depends only on a narrow client contract — call it `IRoleDirectory` — decoupled exactly like inventory (§14):

```
isValidRole(roleId)            -> bool                     // validate a role on write
holds(personOid, roleId)       -> bool                     // gate a claim to a real holder
listHolders(roleId)            -> [ {oid, displayName} ]   // NEW — Flow 1 (roster of a role)
rolesOf(personOid)             -> [ {roleId, displayName} ]// NEW — Flow 2 (which roles a person holds)
```

> **⚠ Contract gap to raise.** Step‑2's stated contract answers only *"is R valid?"* and *"does P hold R?"*. **Both of the user's flows need enumeration the contract doesn't yet expose:** `listHolders(R)` (Flow 1) and `rolesOf(P)` (Flow 2, the open #7 reverse lookup). These two methods must be added to the roles‑source workstream's contract.

**Absent‑safe fallbacks (greenfield / no roles source wired):**
- `listHolders` absent → the sponsor **types the person** (or leaves it pooled).
- `rolesOf` absent → the person **self‑selects** their role(s) from the catalogue (Flow 2, §11.3); or the ADK resolves the caller's AAD identity via **Work IQ `/me`** and maps oid→roles (Step‑2's option 3).
- `isValidRole` absent → **well‑formed‑id** check only; `holds` absent → returns "unknown" (never fails the write).

The single‑operator assumption is **not baked in** (§3): the Task names a role via the `Principal`; that the sponsor may hold it is incidental.

---

## 11. Task discovery: "what am I assigned?" grouped by role (Flow 2)

A person comes to the ADK and asks what's waiting on them. The answer is **grouped by each role they hold** — which naturally handles a person with more than one role.

### 11.1 The experience

A new entry point — a `/planner` branch (or a thin `/mytasks` command) — that renders:

```
You hold 2 roles.

▸ Power Platform admin
    • T1  Create environment & run setup     (assigned to you)      [NotStarted]
▸ Integration owner
    • T2  Connect Workday                     (open to your role)    [NotStarted]
    • T5  Connect ServiceNow                  (open to your role)    [NotStarted]
```

*Role as the title, its tasks beneath* — exactly the shape the sponsor's Flow 2 asked for.

### 11.2 How it resolves (the queries)

1. **Resolve the caller's roles:** `rolesOf(P) → [R1, R2, …]` (or Work IQ `/me` → oid → roles; or self‑select if the source is absent).
2. **Per role, gather Tasks** (using the promoted scalars Step‑2 §7.4 defines):
   - **Directly yours:** `assignedToId eq P and assignedToType eq 'User'` → bucket each under its retained `assignedToRoleId`.
   - **Open pool for a role you hold:** `assignedToRoleId eq Rᵢ and assignedToType eq 'Role'`.
3. **Group by role and render.** A claimed/direct Task shows under its retained role with "(assigned to you)"; a pooled Task shows with "(open to your role)" and offers a **claim** action (→ claimed state, §10.3).

Because `Principal.Role = R` is retained in **both** pooled and claimed/direct states, "every task for role R" is the single filter `assignedToRoleId eq R` — the property Step‑2 §7.4 designed for exactly this.

### 11.3 Local vs synced scope

- **Local / greenfield:** before WeveNova sync, Tasks live in `plan.json`; Flow 2 filters `tasks[]` **in memory**, scoped to the current Plan.
- **Synced / cross‑plan:** once synced, a person's Tasks can span multiple Plans/Projects, so Flow 2 runs the same filters over the **WeveNova MCP** Project/Plan/Task tools (Step‑2 §13) for a true "everything assigned to me across plans" view.

---

## 12. Capturing Task outputs & updating the Plan as work progresses

The heart of Step 1: a Task declares (from the Learn doc) the output **keys** it produces, and when the assignee finishes, the ADK fills each key — by **observing** what the action changed (e.g. `/setup` created an environment) **or by asking the assignee** — and pins it onto the Plan, always confirming with the person doing the job.

### 12.1 What drives capture: the `produces` keys, filled by observe **or** ask

Every Task declares the output **keys** it should yield in `produces`, and those keys are **grounded from the Learn doc** during research (§7.6) — not invented at completion. Capturing an output means filling a value for each declared key, by whichever of two means fits the Task, then confirming before pinning:

- **(a) Observe** *(preferred for kit‑skill Tasks that leave a signal).* A detector reads the value from the state the action actually changed — `/setup` → `environmentId` from `config.json`. This is **desired‑vs‑observed reconciliation** (the K8s spec/status split Step‑2 §6.2 borrows, applied client‑side): the value is read from the world the action changed, not from what the agent *says* — the rigor of Step‑2's event‑carried‑state‑transfer write (§9). Pinned with `provenance.source: "Agent"`.
- **(b) Ask** *(for manual/portal/external Tasks, or any output not observable from kit state).* The ADK **asks the assignee to supply the value** for the key — *"what's the Entra app id you registered?"* — and also accepts **any extra info the assignee volunteers** (captured as additional artifact attributes, or Context entries). Pinned with `provenance.source: "User"`.

So `produces` (from the doc) says *what* to capture; observe/ask says *how*; the assignee's confirmation gates every pin. Neither mode trusts free‑text narration — observe reads reality, ask records an explicit answer the assignee stands behind.

### 12.2 Observe mode, worked: the `/setup` → `environmentId` hand‑off

1. **Before.** Planner snapshots the current environment (from `config.json` + `list_environments.py`/`pp_admin_client.py`). T1 is `NotStarted`; `outputs:[]`.
2. **The assignee runs `/setup`.** It provisions/binds Dataverse and **atomically writes `.local/config.json`** (`setup:"complete"`, `dataverseEndpoint`).
3. **The ADK detects the change.** On return to `/planner`, it re‑reads `config.json`, diffs against the snapshot — a new endpoint/`environmentId` = T1 produced an environment. *(Where `config.json` lacks a raw `environmentId` GUID, resolve it once from the endpoint via the existing PP/BAP client and persist it onto `config.json` — §18.)*
4. **Confirm with the person doing the job.** The planner does **not** silently write. It asks the assignee (person P, acting as the role): *"I see `/setup` created environment `d3f1…` (`https://…`). Pin it to the plan as T1's output?"* — the "ask the role who did the job" the requirement calls for.
5. **Pin onto the ledger.** On yes, append a `PlanArtifact` to `outputs[]` (`key:primaryEnvironment`, `kind:Environment`, `attributes:{environmentId, environmentUrl}`, `inventoryRef`, `producedByTaskId:T1`, `provenance.source:Agent`, `state:Active`); T1 → `Completed`; `summary.md` re‑renders. Supersede‑by‑key handles a re‑run.
6. **Downstream reads off the Plan.** T3 (evals), a possibly different role, reads `outputs["primaryEnvironment"].attributes.environmentId` straight from `plan.json` — no re‑discovery. The reproducible hand‑off (Step‑2 §11), realised locally.

### 12.3 The observe‑mode detector registry

For mode (a), a small **detector per artifact kind** returns the `PlanArtifact`s a Task produced from before/after kit state. Detectors key off the **observed signal, not the action kind** — a portal/manual step that still touches the tenant (e.g. an Entra app registered in the Azure portal) can be observed the same way a kit skill is:

| Task action | Detector reads | Artifact(s) pinned |
|---|---|---|
| kitSkill `onboarding` | `config.json` diff (endpoint/env id) | `Environment` |
| kitSkill `connect` (Workday) | new connection refs + Entra app id | `Connection`, `EntraApp` (appId+objectId+tenantId under one key, Step‑2 §7.2) |
| portal register Entra app | new app registration id (Graph/BAP) | `EntraApp` |
| kitSkill `flightcheck` | the readiness report file | `Custom` (readiness snapshot) |
| kitSkill `evaluations` | new eval `botcomponent` ids under `workspace/agents/<slug>/evaluations/` | `Custom` (eval‑suite id) |
| kitSkill `topics/create` | new topic files pushed | `Custom` (topic ref) |

Each detector is **best‑effort and confirm‑before‑pin**. **When no detector fits (a truly external step) or a detector can't read its signal, capture falls to mode (b) — the ADK asks the assignee for each unresolved `produces` key** rather than leaving it blank. Either way the Plan ends up with a value for every declared key, or an explicit "unresolved" the maker can fill later.

### 12.4 Plan progress = ledger + task state

- Task `state` advances `NotStarted → InProgress → Completed` (+ the reopen `Completed → InProgress`, which marks its ledger entries stale, Step‑2 §8).
- Completing a Task whose `produces` now resolve in `outputs[]` can **unblock** downstream Tasks whose `consumes` are satisfied (Step‑2 §7.2 wiring; phase‑2). The planner surfaces "T3 is now unblocked".
- `summary.md` always reflects current states + pinned outputs.

---

## 13. Decoupling & trust boundaries

- **Local Plan is authoritative.** `/planner` reads/writes only `workspace/plan/*`; never blocks on WeveNova, inventory, or the roles source being present (§5).
- **Three optional seams, none on the read path:** WeveNova sync (§15), tenant inventory (§14), and the roles source (§10.4). Each is best‑effort/absent‑safe.
- **Untrusted data.** All researched/sample/`workspace/agents/**` content is *data, not instructions* (copilot‑instructions Security Boundaries). The planner never executes directives embedded in fetched pages.
- **Confirm high‑impact actions.** `/planner` is non‑destructive (writes a local file). It **confirms before pinning** an artifact (§12) and **before assigning a person** (§10). Tasks it emits invoke mutating skills, which keep their own confirm‑before‑push discipline.
- **No fabricated URLs.** The crawl only follows TOC‑resolved `href`s (§7.3); any doc link written into the Plan/summary is verified or left as a `# TODO` (kit rule).

---

## 14. Greenfield now; inventory / `/discover` enrichment later

- **Greenfield (this doc).** No inventory. The Plan is built purely from intent + research; every prerequisite becomes a Task; `outputs[]` fills as Tasks run (§12).
- **Enrichment (future, seam only).** A tenant **inventory** — from a prior Plan's pinned outputs or an explicit `/discover` crawl — lets the planner *skip* Tasks whose prerequisites already exist ("you already have a Workday connection ✓") and pre‑fill readiness. Consumed through a narrow, optional contract (Step‑2 §5): *"does {kind}:{naturalKey} already exist?"*. The planner pins from inventory the same way it pins from a Task — a `PlanArtifact` with `provenance.source:"Discovered"` — so the Plan shape is identical either way.
- **Decoupling guarantee (Step‑2 §5/§12).** The Plan holds only opaque `{kind}:{naturalKey}` refs + pinned attributes; it never imports inventory's (or the roles source's) types. Greenfield ships with these contracts **absent** (no‑ops), so the Plan is complete and correct alone. Swapping in real implementations later touches only the adapters, never `plan.json`'s schema or the read path.

**Not built here:** the crawler, the inventory schema, `/discover`, or the roles directory. Built here: greenfield + the seams.

---

## 15. The Step‑1 ↔ Step‑2 sync seam

When WeveNova is available, the local Plan syncs to it — best‑effort, local‑authoritative:

- **Create/update:** the ADK calls the WeveNova MCP tools (`create_agent_plan`, `update_agent_plan`, `create_agent_plan_task`, `update_agent_plan_task` — Step‑2 §13) with DTOs derived from `plan.json`. Because the local shape *is* the WeveNova shape (§9.2) — one `Context` bag, the extended `Principal`, the ledger — this is a field copy. `planId`/`projectId` come back and stamp onto `plan.json`.
- **Task completion with outputs:** when the capture loop pins an artifact (§12), the sync calls the "complete task with outputs" action (Step‑2 §13.3) so the WeveNova ledger matches.
- **Discovery (Flow 2):** the same MCP tools serve the `assignedToRoleId`/`assignedToId`/`assignedToType` filters for the cross‑plan "my tasks" view (§11.3).
- **Best‑effort, never blocking:** if WeveNova is down/absent, the local Plan is already correct; sync retries later. The ADK is to WeveNova what a completing Task is to inventory: it feeds it, never waits on it.

Until WeveNova + these MCP tools are live, the sync layer is a **no‑op stub** and the kit runs fully on the local Plan.

---

## 16. Alternatives considered

- **Learn as a fallback behind the vendored snapshot.** Rejected — the snapshot drifts (its URL already moved, §7.1). Research Learn live and use the snapshot only as a seed hint + offline net.
- **Scraping rendered pages for navigation.** Rejected — fragile and guess‑prone. The TOC (`toc.json`) is the authoritative, complete child/sibling graph (§7.2).
- **A fill‑in form instead of a grounded interview.** Rejected — can't scope to what ESS supports and drifts as ESS evolves. Grounded slot‑filling asks less and stays correct (§8).
- **A separate `AssignedRole` field beside `AssignedTo`.** Rejected in favour of Step‑2 §7.4's **one extended `Principal`** — a single assignee value that reads as "person P acting as role R", so every existing `Principal` reader keeps working.
- **Rewriting `AssignedTo` from role to person on claim.** Rejected — discards the role + provenance. We retain the role (§10.3), which is also what makes Flow 2 group correctly.
- **Trusting the agent's narration of what a Task did.** Rejected — we observe kit state (§12).
- **Auto‑pinning artifacts / auto‑assigning people without confirmation.** Rejected — the requirement is to *ask the person doing the job* and *let the sponsor pick*; silent writes lose provenance.
- **A bespoke plan JSON optimised for the ADK.** Rejected — divergence makes Step 2 a migration, not a sync. We keep the shapes identical for one small tax (`task.action`).
- **Each skill step as its own Plan Task.** Rejected — a skill's steps share one assignee, aren't knowable at plan time (`connect` detects simplified‑vs‑legacy Workday at runtime, changing the step set), and would blow the ~50‑task cap. One Task per skill run (or per role‑bounded slice); the skill owns its steps (§10.1).
- **Step as a first‑class entity (a Plan→Task→Step tree).** Rejected — it breaks WeveNova's flat Plan→Task model, needs a new entity + lifecycle, and buys nothing: steps need no independent assignment (all run under one assignee), and if a slice ever needs a distinct owner it becomes its own *Task* on a role boundary (§10.1). Step *visibility* is met by the read‑back‑only `Task.checklist[]` instead.
- **Naming the command `/plan`.** Rejected — collides with VS Code Plan mode. Renamed to **`/planner`** (the document stays the *Plan*).

---

## 17. Worked example (greenfield, start to finish)

1. Sponsor: *"ESS HR ticketing for employees on ServiceNow, plus read profile from Workday. Germany first."*
2. **Research.** `/planner` seeds the ESS Learn URL → follows the 301 to the current base → fetches `toc.json` (59 nodes) → selects `overview`, `prerequisites`, `deploy-overview-alm`, `install`, `commands-reference`, the **Workday** subtree, and **ServiceNow** (`servicenow`, `servicenow-hrsd-itsm`); skips SAP + facilities (title‑only). Extracts capabilities + prerequisites + constraints (Workday needs Entra SSO; a data‑residency note for DE), caches `research-context.json`.
3. **Interview.** 4 intent turns → Context entries (`objective`, `businessGoals:[deflect 30%]`, `scenarioContext:[HR-Ticketing, ServiceNow HRSD, Workday, Employee]`, `market:DE`, `acceptanceCriteria`). Sponsor accepts.
4. **Emit + assign (Flow 1).** Tasks T1 `/setup`, T2 `/connect ServiceNow`, T3 `/connect Workday`, T4 `/evaluate`, and T5 *Publish the agent* (a **portal/admin** step — no kit skill). **Each Task's role and `produces` keys come from the Learn docs** (research grounded `power-platform-admin` for setup/publish, `integration-owner` for connect, `eval-author` for evals) — the sponsor is not asked to name roles. The ADK lists holders of each grounded role; the sponsor assigns **Paul** to T1, **pools** T2/T3 to `integration-owner`, assigns **Ann** to T4, pools T5 to `power-platform-admin`. `plan.json` + `summary.md` written.
5. **Run + capture.** Paul runs `/setup` → env `d3f1…` → planner detects the `config.json` diff, asks Paul to confirm, pins the `Environment` artifact; T1 → Completed.
6. **Discover (Flow 2).** A holder of `integration-owner` asks "what am I assigned?" → sees, under *Integration owner*, T2 + T3 "(open to your role)" → claims T2 → runs `/connect` → connection/app artifacts pinned; T4 unblocks.
7. **Read‑through.** Ann runs `/evaluate`; it reads `outputs["primaryEnvironment"].environmentId` off the Plan — no re‑discovery. Eval artifact pins; T4 completes.
8. *(When WeveNova is live)* every write best‑effort‑syncs (§15); until then it all runs locally.

---

## 18. Open questions

1. ~~Command name.~~ **Decided: `/planner`** (renamed from `/plan` to avoid the VS Code Plan‑mode collision; the document stays the *Plan*).
2. **Roles‑endpoint enumeration.** The unbuilt roles source must expose **`listHolders(R)`** (Flow 1) and **`rolesOf(P)`** (Flow 2) beyond Step‑2's boolean contract (§10.4). Owner: roles‑source workstream + ADK.
3. **`environmentId` on `config.json`.** `config.json` stores `dataverseEndpoint` but not a raw `environmentId` GUID today (§12.2). Add it additively at setup time, or resolve on demand? Owner: ADK.
4. **Flow‑2 scope & command.** Local (current Plan) vs cross‑plan (needs WeveNova sync + the promoted filters); and a `/planner` branch vs a dedicated `/mytasks` command. Owner: ADK + PM.
5. **Localized TOC / market grounding.** Crawl `/en-us/` only, or the sponsor's locale (a DE market may imply `/de-de/`)? Owner: ADK + PM.
6. **Research refresh cadence & cache home.** Every run, or cached with a TTL + explicit "re‑research"? Sidecar `research-context.json` vs folded into Context provenance. Owner: ADK.
7. **Detector coverage & confidence.** Which Task kinds get automatic detectors in P0 (env only?) vs later, and how to signal low‑confidence detections (§12.3). Owner: ADK.
8. **Claiming semantics on sync.** When a pooled Task is claimed locally then synced, confirm the WeveNova write is the claimed `Principal` (`type:User, role retained`) and reconciles under If‑Match. Owner: ADK + WeveNova.
9. **Greenfield vs enrichment detection.** How the planner decides greenfield vs improving an existing deployment before an inventory/`/discover` contract exists — ask (§8 Q8), or probe the environment? Owner: ADK + PM.
10. **Grounding confidence for role / action / `produces`.** These are extracted from the Learn docs per Task (§7.6, §10, §12). When a doc doesn't clearly state the responsible role, whether a step is a kit skill vs a portal action, or what it produces, what's the fallback — a conservative default (e.g. `power-platform-admin`, `manual`, empty `produces` then ask the assignee), or ask the sponsor? Owner: ADK + PM.
11. **Step visibility — skill‑local vs `Task.checklist[]`.** Keep step progress ephemeral in the skill's own todo‑list / `.local` state (Option A, simplest), or persist it as the read‑back‑only `Task.checklist[]` filled at runtime (Option B, visible on the Plan after the session)? And if B, does the checklist sync to WeveNova or stay client‑only? Owner: ADK.

---

## Appendix A — verified `main` baseline

Verified on `origin/main`, HEAD `72a24f8`, worktree cleaned to match `main`:

- Skills under `src/skills/`: `onboarding`, `connect` (+ `azure/`, `servicenow/`, `workday/`), `topics/*`, `workflows/*`, `evaluations/*`, `flightcheck`, `cleanup`, `troubleshoot`, `backup/restore-template-configs`. **No `plan`/`planner` skill.**
- Prompts under `.github/prompts/`: `setup, connect, create, update, delete, scan, review, evaluate, flightcheck, push, troubleshoot, backup/restore-template-configs, menu`. **No `plan`/`planner` prompt** (only a VS Code Plan‑mode tip in `menu.prompt.md`).
- `scripts/`: `setup.py` (writes `.local/config.json` atomically — `setup:"complete"`, `agent`, `agents[]`, `dataverseEndpoint`), `fetch_and_setup.py`, `list_environments.py`, `discover.py`, `checkpoint.py`, `push.py`, `extract.py`, `evaluate_evals.py`, `emit_capability.py`, `adk_telemetry.py`, plus the `scripts/flightcheck/` package (`pp_admin_client.py`, `powerplatform_client.py`, `environment.py`, `licensing.py`, `graph_client.py`, `connections.py`, `cli.py`, …). **No `scripts/planner/`, no `scripts/discovery/`.**
- `workspace/` tracks only `agents/.gitkeep` and `onboarding/.gitkeep`. **No `plan/`, no `inventory/`.**
- Grounding: `src/reference/ess-docs/` (vendored MS Learn ESS snapshot, 2026‑04‑29) and `src/examples/ess-samples/`.
- Pipeline: `Checkpoint → Local edit → Scan → Dry run → Push → Verify`.

**Live Learn facts verified while writing (§7):** the ESS Learn section moved — old URL `…/copilot/microsoft-365/employee-self-service` 404s and 301‑redirects to `…/microsoft-365/copilot/employee-self-service`; its `toc.json` returns **59 pages** across sections *Deploy*, *Integrate external systems* (SAP / Workday / ServiceNow subtrees), *Extend*, and operations pages. This drift is the concrete reason Learn is researched live, not read from the snapshot.

**Not on `main`, prior art only:** the `scripts/planner` engine, the discovery package, and `workspace/plan|inventory/*.json` — feature‑branch/local. The Plan shape is re‑derived from the Step‑2 contract.

## Appendix B — quick reference

**Task → action → artifact → role (grounded from Learn)**

| Task | Action | Produces | Consumes | Role (from Learn) | Capture (§12) |
|---|---|---|---|---|---|
| Create/bind env & setup | kitSkill `onboarding` (`/setup`) | `primaryEnvironment` | — | `power-platform-admin` | observe: `config.json` diff |
| Readiness check | kitSkill `flightcheck` (`/flightcheck`) | `readinessReport` | `primaryEnvironment` | `power-platform-admin` | observe: readiness file |
| Connect Workday | kitSkill `connect` (`/connect`) | `workdayConnection`, `workdayEntraApp` | `primaryEnvironment` | `integration-owner` | observe: conn refs + app id |
| Connect ServiceNow | kitSkill `connect` (`/connect`) | `servicenowConnection` | `primaryEnvironment` | `integration-owner` | observe: conn refs |
| Author topics | kitSkill `topics/create` (`/create`) | `topic:<name>` | env + connections | `maker` | observe: pushed topic files |
| Generate evals | kitSkill `evaluations/create` (`/evaluate`) | `evalSuite` | `primaryEnvironment` | `eval-author` | observe: new eval ids |
| Publish the agent | portal/admin (Learn doc) | — | built agent | `power-platform-admin` | ask assignee |

**Assignment `Principal` states:** Pool `{type:Role,id:R,role:{R}}` · Claimed/Direct `{type:User,id:P,user:{P},role:{R}}` · Plain person `{type:User,id:P,user:{P}}`.

**Roles endpoint (unbuilt seam):** `isValidRole(R)` · `holds(P,R)` · **`listHolders(R)`** (Flow 1) · **`rolesOf(P)`** (Flow 2) — absent‑safe (§10.4).

**Discovery filters (Flow 2):** every task for role R → `assignedToRoleId eq R`; unclaimed pool → `+ assignedToType eq 'Role'`; my direct tasks → `assignedToId eq P and assignedToType eq 'User'`.
