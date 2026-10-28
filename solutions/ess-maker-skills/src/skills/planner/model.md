# Planner — Phase 3: Model the Tasks

> **Planner session entry:** Follow `src/skills/planner/SKILL.md` -> **Intent gate**,
> then **Gate** for the workspace bootstrap on first Planner use. Reuse its successful result
> in the same chat and workspace before continuing this flow.
> Apply its **Communication rules** to every reply and next-step handoff.

Turn the grounded prerequisite graph (Phase 2) into **atomic Tasks**. A Task is
the smallest unit one owner can complete end-to-end. Each Task is described by a
**title** and a **description** — nothing else is needed to understand it.

Do not replicate catalogue prose or the same caveat across plan context entries.
The shared record has a 25,600-byte aggregate storage limit including server-added
metadata; per-field validity is not enough. Let `export-remote-plan` pack generated
workstream metadata and check the final budget (`sync.md`). Do not drop required
tasks, dependencies, or scope to make metadata fit.

Add each Task with:

```
python scripts/planner/cli.py add-task --id <T#> \
  --title "<the outcome, never the command — 'Set up the environment', not 'Run /setup'>" \
  --description "<self-explanatory: what to do and how — including which command to run, e.g. 'Run /connect to connect Workday to the ESS agent and follow its steps'>" \
  --role <attestable-role> \
  [--produces <key,key>] [--consumes <key,key>]
```

**Title names the outcome; the description names the how (including the command).**
The plan the sponsor sees lists tasks by **title + role only** — the description
renders **only in the detailed brief** when an assignee engages the task
(`plan_model._render_tasks`; `mytasks.md` → *Brief the task in detail*). So:

- **Title = the outcome, never the command.** "Set up the environment", not
  "Run /setup"; "Connect Workday", not "Run /connect". A reader scanning the plan
  sees results, not kit commands.
- **Description = what to do and how, including which command to run** — say it in
  prose ("run `/connect`", "in the Power Platform admin center, register an Entra
  app…"). Because the description is brief-only, naming the command here reveals it
  exactly when the assignee asks (opens the task), not in the plan overview.
- **Do not** encode the "how" in structured fields like an action/kit-skill type —
  those are not task data; the description carries it. (The setup task is identified
  by what it **produces**, below — not by any skill field.)
- **One skill run completes one _or more_ tasks.** When the assignee runs the skill,
  capture closes **every** plan task that run fully produced — e.g. a single
  `/setup` run records the environment and clones the agent, completing both the
  environment task and the base-agent task if the plan splits them (`capture.md`).

**The description names the how; the _detailed_ steps are enriched from Learn on
start — so keep the Learn anchor.** Keep the description a clear, self-contained
summary (what to do, which command or portal step); don't try to inline every
step — steps drift and go stale. When an assignee picks the task up, Flow 2 renders
the full how-to by **handing off to the named kit skill** (`/setup`, `/connect`,
`/create`, `/evaluate`) or **fetching the step's Microsoft Learn page fresh** for a
portal/manual step (`src/skills/planner/mytasks.md` → *Brief the task in detail*).
For that to work, keep each task's **grounding Learn page URL** in the research
context (§7.6, `prerequisites[].sourceUrl`) — that anchor is what the brief
enriches from at render time. Mantra: **enrich from Learn**, don't freeze steps
into the plan.

**Every Task is assigned to a role at creation — the role that should be able to
pick it up — and that role is _sourced from the Learn link_, never invented.** The
`--role` and `--produces` values come from the **Learn page for that prerequisite**
(Phase 2; the `research --extract` step surfaces the role candidates). Ground the
role, then set `--role` to its **attestable** id (the mapping under *A Task is not
a skill's steps* below) — the shared planner only accepts attestable roles, so a
raw grounded slug leaves the Task unassignable. Keep the
Learn page URL in your research notes (it lives in the research context, §7.6 —
not as a task field). `--role` assigns the Task to that role for now (any holder can
pick it up, Flow 2); Phase 4 assigns the actual person.

> **Person comes later.** Today the role is unassigned and the sponsor picks a person
> (Phase 4, Flow 1). A future step resolves *who holds the role* from an external
> roles API (the `roles.py` `RoleSource` seam — `list_holders(role)`), and a Task
> can then be assigned a **user together with the role** (`assign --role R
> --person <oid>`). Do not hardcode people; keep the role Learn-grounded.

## Pending decisions are not a global planning gate

Keep an unknown system/owner in `pendingDecision` context and retain the selected
scenario. Build the known foundation and independent review work now. Describe
system-specific work as pending, not as a fabricated connector or a knowledge-only
replacement. For a task that needs an unknown system, include the matching
`system.<scenario-id>` decision key in `consumes`; the local readiness check keeps
it waiting until `add-system` confirms that choice. Once resolved, research and
replace/refine the affected placeholders with the real role-split integration
tasks and their artifact dependencies. A resolved system name alone is not a
configured connection.

The CLI rejects starting/completing a task with unresolved inputs. Run
`task-brief` before the corresponding MCP state/completion call as well; do not
bypass the local guard by writing straight to the shared service. A task may be
assigned before its dependencies are ready. Missing people do not block drafting
or unrelated work, but a qualified owner must perform the affected work.

Do not invent execution prerequisites to force visual order: independent firewall
preparation may run in parallel with environment setup. The view puts foundation
work first when ready and preserves topological order across stream boundaries;
a stream can appear in more than one contiguous section.

## Split on role boundaries

A kit skill (e.g. `connect`) is itself a multi-step procedure with its own
checklist. Those individual steps stay **inside the skill** — they do NOT each
become a Task, and you do NOT add both "run connect" and its checklist items.

**Exhaustive — every step the skill performs lands on the plan.** For a system
with a kit skill (connect Workday, setup), the plan must represent **all** of that
skill's work — don't drop or summarise steps. The rules below decide their
*shape*, not whether they appear: same-role sequential steps collapse into **one
outcome task** (its steps live inside the skill, surfaced at brief time), and each
distinct role the flow touches gets its **own** task. Nothing the skill does is
left off the plan.

**But split a Task on every role boundary. Role boundary = Task boundary.** A
Task is atomic: exactly one role can complete it. If the docs put part of the
work on a *different* role, that part is its own Task — never split by step,
always split by role.

**Read the skill's role map before you emit tasks — do NOT assume one skill =
one task.** Before emitting the task(s) for a system, read that system's setup
checklist and its role gating (`src/skills/setup/<system>/tasks.md` and
`src/reference/ess-docs/setup/role-gating.md` — each checklist item carries a
`role:`), and emit **one Task per distinct role** the flow requires.

**Don't hand-decompose a system that ships a setup checklist — run the extractor.**
For any `system` with a `src/skills/setup/<system>/tasks.md` (today: `workday`),
the decomposition is deterministic — do **not** eyeball it. Run:

```
python scripts/planner/cli.py setup-tasks --system workday --commands
```

It reads the checklist, groups **every** step by its role boundary, maps each
grounded role to its **attestable** role, and prints ready-to-run `add-task`
lines — one Task per (group, role), covering all 25 steps across all 6 groups.
Emit those lines **verbatim**; add `--skip-foundation` when a backbone **Set up
the environment** (`/setup`) task already produces `primaryEnvironment`/`essAgent`
(checklist groups 1–2). Omit
`--commands` for the structured JSON. Never invent, drop, merge, or re-role what
it emits.

**The `--role` on a Task must be an _attestable_ role — ground it, then map it.**
A Task is assigned to a role so a real person can be attested onto it (`assign.md` →
*Nudge*); only the **closed attestable set** is assignable, so a Task tagged with a
free-form grounded slug (`app-cloud-app-admin`, `infosec-it`, …) can never surface
in anyone's "what am I assigned?" view. Take the checklist's `role:`, map it to the
attestable role that owns that work (source of truth:
`src/mcp/agentconfig_planner/roles_surface.py` → `ATTESTABLE_ROLES`), and keep the
checklist wording in the description:

| Checklist `role:` (grounded) | `--role` (attestable id) | Attestable display |
|---|---|---|
| Power Platform Administrator | `EntraPowerPlatformAdministrator` | Power Platform Administrator |
| Environment Maker | `PowerPlatformEnvironmentMaker` | Environment Maker |
| App/Cloud App Admin | `EntraCloudApplicationAdministrator` | Cloud Application Administrator |
| Workday Administrator | `WorkdayAdmin` | Workday administrator |
| InfoSec/IT | `EntraNetworkAdministrator` | Network Administrator |

**Never over-privilege or invent a role.** Workday SSO is a
`EntraCloudApplicationAdministrator` task — **not** `Global Administrator` (GA is
only a consent fallback, named in the description, never the Task's role). The
firewall step is `EntraNetworkAdministrator`, the closest attestable proxy for
InfoSec/IT — it comes from the mapping above, not invented per-run.

**Worked example — Workday is seven role-boundary Tasks (grounded from
`setup/workday/tasks.md`), never one.** This is exactly what
`setup-tasks --system workday` emits — run it rather than transcribing the table:

| Task (title) | `--role` (attestable) | Grounded role | Steps | Produces |
|---|---|---|---|---|
| Set up the Power Platform environment | `EntraPowerPlatformAdministrator` | Power Platform Administrator | S1.1–S1.2 | `primaryEnvironment` |
| Install the Employee Self-Service base agent | `PowerPlatformEnvironmentMaker` | Environment Maker | S2.1 | `essAgent` |
| Set up Workday single sign-on (Entra) | `EntraCloudApplicationAdministrator` | App/Cloud App Admin | S3.1–S3.7 | `workdayEntraApp` |
| Configure the Workday tenant | `WorkdayAdmin` | Workday Administrator | S4.1–S4.4 | `workdayTenantConfig` |
| Install the Workday extension pack & connect | `PowerPlatformEnvironmentMaker` | Environment Maker | S5.1–S5.7 | `workdayConnection` |
| Allow Workday through the firewall | `EntraNetworkAdministrator` | InfoSec/IT | S5.8 | `workdayNetworkAllowlist` |
| Author your first custom Workday topic | `PowerPlatformEnvironmentMaker` | Environment Maker (+ Workday SME) | S6.1–S6.3 | `topic:workday` |

Groups 1–2 stand up the shared environment + base agent — pass `--skip-foundation`
to drop them when a backbone **Set up the environment** (`/setup`) task already
covers them. Group 5 is
itself multi-role (Environment Maker for the pack + connect, InfoSec/IT for the
firewall), which is why it yields two Tasks.

## Typical greenfield backbone

The "how" is the **description** (say which command to run in prose); `produces`/
`consumes` drive ordering and capture; the role is grounded from Learn.

| Task (title) | Description (what & how) | Produces | Consumes | Role (attestable) |
|------|--------|----------|----------|-----------------|
| Set up the environment | Run guided foundation setup to provision/select the environment and verify its ID, URL, access, and prerequisites | `primaryEnvironment` | — | `EntraPowerPlatformAdministrator` |
| Install and bind the ESS base agent | Continue setup to install/select ESS and bind the workspace; capture the actual agent identity | `essAgent` | `primaryEnvironment` | `PowerPlatformEnvironmentMaker` |
| Check readiness | Run `/flightcheck` to validate the environment | `readinessReport` | `primaryEnvironment` | `EntraPowerPlatformAdministrator` |
| Discover the tenant inventory | Run `/discover` to crawl the configured environment and record what already exists | `tenantInventory` | `primaryEnvironment` | `EntraPowerPlatformAdministrator` |
| Set up Workday SSO (Entra) | Register/configure the Workday enterprise app for SSO — `setup/workday/tasks.md` §3 | `workdayEntraApp` | `primaryEnvironment` | `EntraCloudApplicationAdministrator` |
| Configure the Workday tenant | Create the API client & tenant config in Workday — §4 | `workdayTenantConfig` | `primaryEnvironment` | `WorkdayAdmin` |
| Install Workday pack & connect | Run `/connect` — install the Workday extension pack and create the connection — §5 | `workdayConnection` | `primaryEnvironment, essAgent, workdayEntraApp, workdayTenantConfig, workdayNetworkAllowlist` | `PowerPlatformEnvironmentMaker` |
| Allow Workday through the firewall | Attest the Workday egress allowlist — §5 (S5.8) | `workdayNetworkAllowlist` | — | `EntraNetworkAdministrator` |
| Connect ServiceNow | Run `/connect`; use `src/skills/connect/servicenow/steps.md` for the procedure and Learn for the responsible roles. This checklist is not role-tagged; do not treat it as Workday's extractor input. | `servicenowConnection` | `primaryEnvironment` | `ServiceNowAdmin` *(+ `PowerPlatformEnvironmentMaker` where the grounded steps require it)* |
| Author scenario topics | Run `/create` to author the scenario topics | `topic:<name>` | env + connections | `PowerPlatformEnvironmentMaker` |
| Generate evals | Automatically continue to the existing evaluation-generation flow for the selected scope; retain review and push approval | `evalSuite` | environment, agent, actual scenario topic outputs | `PowerPlatformEnvironmentMaker` |
| Run evaluations | Execute the generated suite using the supported runtime and record observed results | `evaluationResults` | `evalSuite`, required topic/connection outputs | `PowerPlatformEnvironmentMaker` |
| Publish the agent | Publish after the agreed evaluation bar is met and the maker approves (see the Learn publish doc) | — | built agent, `evaluationResults` | `EntraPowerPlatformAdministrator` |

`produces`/`consumes` keys are the **expected** outputs, and drive ordering
("blocked until produced"). Phase 6 capture is **generic** — the setup task lists
can capture `primaryEnvironment` and `essAgent` for separate milestones, while `capture-setup` diffs the whole
`.local/config.json` and pins **every** id + name (and any other artifact a skill
recorded) — the environment, the cloned agent, and anything else the run wrote
(a connection, an app…) — even outputs the task didn't pre-declare (see
`capture.md`). And `capture-setup --complete` **cascades across tasks**: it closes
every plan task that run fully produced, so one `/setup` run completes both the
environment task and the base-agent task when they're modelled separately — not
just the task that triggered the capture.

**`tenantInventory` is the one backbone output `capture-setup` cannot see.**
`/discover` writes its findings to `.local/inventory.json` and leaves only two
top-level *strings* in `.local/config.json` (`inventoryPath`, `inventoryUpdatedAt`).
The generic sweep pins **id-bearing objects**, so it skips both. So the `/discover`
skill **closes its own task**: when a run finishes it calls `capture-discover`, which
reads `workspace/discover/results.json`, pins a single `Custom` `tenantInventory`
artifact (per-kind resource counts + the write path + a pointer to the mirror), and —
because a task with unresolved `produces` is refused `Completed` — marks the discover
task done so it never stays open forever. You don't pin it by hand; the same command
run from the planner is the fallback if you ever need it:

```
python scripts/planner/cli.py capture-discover --complete
```

(auto-detects the plan's discover task; `--dry-run` previews without saving.)

When the tasks are in, **show the plan (roles unassigned) locally** (download
link + checklist) — **do not store it to the shared space yet; that's an explicit
step the sponsor asks for later** (`src/skills/planner/sync.md` → *Share*). Then go
to Phase 4 — **assigning the roles to people is a follow-up after the plan is
shown**, not a gate (`src/skills/planner/assign.md`).

**Native connector vs. custom flow.** A "run `/connect`" task is only valid for a
system ESS has a **native integration** for (Workday, ServiceNow HRSD/ITSM, SAP
SuccessFactors — confirm from Phase-2 Learn research). For a captured system with
**no** native connector (e.g. ADP, Jira, Dynamics 365, custom HTTP API), describe a
**"run `/create`" (custom Power Automate flow)** task instead — do not fabricate a
`connect` task for it. SharePoint / M365 content is a **knowledge source**, so it's
the topics/knowledge task, not a connect task.

## First step for a first-time / greenfield rollout

The first task is almost always the **Power Platform admin running `/setup`**.
Foundation setup owns provisioning guidance, prerequisites, installation, and
workspace binding; it delegates manual/admin operations when required. Do not
describe `/setup` as only connecting to an already-installed agent.
Keep environment and agent-install milestones separate, with the appropriate
roles, so verified environment metadata can reach the shared plan while an
installation is still pending. An existing combined task should only be split
with approval; partial metadata must not falsely complete it.

## Back-propagation — how the admin's setup details flow to later tasks

When the admin runs `/setup`, it writes the environment and agent details
(`environmentId`, `dataverseEndpoint`, agent slug/schema/folder) into
`.local/config.json`, and the planner pins `primaryEnvironment` onto the plan
(Phase 6). Those details then reach every downstream task **two ways**, so
nobody re-enters what the admin already set up:

- Every kit skill (`/connect`, `/create`, `/evaluate`) reads `.local/config.json`
  directly for the agent folder / slug / schema.
- Tasks that `consume primaryEnvironment` read the pinned value off the plan.

This is the back-propagation: capture the admin's output once, and every task
that needs it — including topic **create** and eval generation — picks it up.

Each downstream persona connects their **own** kit to that environment first: they
run `/setup` and choose the environment the admin pinned (`primaryEnvironment`),
then their kit skill reads `.local/config.json`. The planner nudges this
automatically — `task-brief` prints "run /setup and choose environment `<envId>`"
for any non-setup kit task once the plan has an environment. So the `/setup` nudge
for other personas is **driven by the plan having an env id**, not fired blindly.

## Emit the full task set now (do not stop at setup)

From the systems and scenarios captured in Phase 1 and grounded in Phase 2, create **every** task now —
not just setup. For *"file HR tickets + get HR knowledge, on Workday + ServiceNow"*
that is:

```
# 1. Separate environment and installed-agent milestones by role.
python scripts/planner/cli.py add-task --id T1 --stream "Setup" --title "Set up the environment" --description "Run /setup to provision/select the environment and verify its ID, URL, access, and prerequisites" --role EntraPowerPlatformAdministrator --produces primaryEnvironment
python scripts/planner/cli.py add-task --id T-agent --stream "Setup" --title "Install and bind ESS" --description "Continue guided setup to install/select ESS and bind the workspace" --role PowerPlatformEnvironmentMaker --produces essAgent --consumes primaryEnvironment
# 2. PP admin takes stock of the tenant BEFORE any connect work is planned
python scripts/planner/cli.py add-task --id T2 --stream "Setup" --title "Discover the tenant inventory" --description "Run /discover to crawl the environment configured during /setup and record the tenant's existing agent resources (environments, app registrations, connectors, connections, SharePoint sites, knowledge sources, extension packs, scenario templates)" --role EntraPowerPlatformAdministrator --produces tenantInventory --consumes primaryEnvironment
# 3. Workday is MULTI-ROLE and ships a checklist — DON'T hand-write it. Emit the
#    grounded, attestable rows straight from setup/workday/tasks.md (the backbone
#    already covers environment + agent, so skip the two foundation groups):
python scripts/planner/cli.py setup-tasks --system workday --commands --skip-foundation
#    -> paste the printed add-task lines verbatim. They map correctly:
#       SSO -> EntraCloudApplicationAdministrator (NOT Global Administrator),
#       tenant -> WorkdayAdmin, pack+connect -> PowerPlatformEnvironmentMaker,
#       firewall -> EntraNetworkAdministrator, first topic -> PowerPlatformEnvironmentMaker.
#    Each printed row already carries --stream "Workday" so they group together.
# 4. ServiceNow — unlike Workday, it ships NO grounded checklist (setup-tasks only
#    grounds Workday today, and `system_setup_tasks("servicenow")` raises). So DON'T
#    imply a checklist: decompose ServiceNow from your Phase-2 research, splitting it
#    along the same role boundaries as Workday (config is a ServiceNow Administrator
#    task; the pack install an Environment Maker one).
python scripts/planner/cli.py add-task --id T-sn-config --stream "ServiceNow" --title "Configure ServiceNow HRSD" --description "Configure the ServiceNow HRSD integration per the connect research for ServiceNow — role: ServiceNow Administrator" --role ServiceNowAdmin --produces servicenowConfig --consumes primaryEnvironment
python scripts/planner/cli.py add-task --id T-sn-connect --stream "ServiceNow" --title "Install ServiceNow pack and connect" --description "Run /connect to install the ServiceNow extension pack and create the connection" --role PowerPlatformEnvironmentMaker --produces servicenowConnection --consumes "primaryEnvironment,essAgent,servicenowConfig"
# 5. authoring per scenario area (knowledge before ticketing — register the dependency)
python scripts/planner/cli.py add-task --id T-know --stream "Authoring" --title "Set up HR knowledge" --description "Run /create to author the HR knowledge topics" --role PowerPlatformEnvironmentMaker --produces "topic:hr-knowledge" --consumes "primaryEnvironment,essAgent"
python scripts/planner/cli.py add-task --id T-tick --stream "Authoring" --title "Author HR ticketing topics" --description "Run /create to author the HR ticketing topics" --role PowerPlatformEnvironmentMaker --produces "topic:hr-ticketing" --consumes "primaryEnvironment,essAgent,servicenowConnection"
# 6. evals + publish
python scripts/planner/cli.py add-task --id T-eval --stream "Evaluation" --title "Generate evals" --description "Continue the guided evaluation flow using saved scenario cases and built topics; preserve review and push approval" --role PowerPlatformEnvironmentMaker --produces evalSuite --consumes "primaryEnvironment,essAgent,topic:hr-knowledge,topic:hr-ticketing"
python scripts/planner/cli.py add-task --id T-eval-run --stream "Evaluation" --title "Run evaluations" --description "Run the approved suite and record actual results against the agreed acceptance criteria" --role PowerPlatformEnvironmentMaker --produces evaluationResults --consumes "evalSuite,servicenowConnection"
python scripts/planner/cli.py add-task --id T-pub --stream "Publish" --title "Publish the agent" --description "After the evaluation bar is met and publishing is approved, publish the agent using the grounded Learn steps" --role EntraPowerPlatformAdministrator --consumes "primaryEnvironment,essAgent,evaluationResults"
```

**Give every task a `--stream` (workstream/theme) so the plan reads by workstream.**
The summary groups tasks under a `### <stream>` heading (`plan_model._render_tasks`)
so the sponsor sees the plan as **Workday**, **ServiceNow**, **Setup**,
**Authoring**, **Evaluation**, **Publish** — not one flat wall of rows. Rules:

- **A captured system → its own stream** (the system name: `Workday`,
  `ServiceNow`). Every task from that system's checklist shares that stream —
  the `setup-tasks` extractor already stamps `--stream "<System>"` on each row,
  so pasting its lines verbatim groups them for free.
- **Cross-cutting backbone tasks → a phase stream**: `Setup` (the `/setup` +
  `/flightcheck` backbone), `Authoring` (the `/create` topic tasks), `Evaluation`
  (`/evaluate`), `Publish`.
- Keep stream labels **few and consistent** — a stream is a workstream a sponsor
  staffs, not a per-task tag. The task **State** column still carries the exact
  cross-stream sequencing (a task waiting on an upstream artifact reads
  **🔒 Not started**), so grouping never hides a dependency.

Also register the scenarios and their dependencies (see `interview.md`) so the
plan shows knowledge-before-ticketing. Then show the summary and go to Phase 4.

## Sequence the tasks — show what's parallel, what's blocked, and the critical path

`produces`/`consumes` aren't just per-task gates — together they form the plan's
**dependency graph**. Once the full set is in, *reason across it* and show the
sponsor the shape, so the work can be **staffed in parallel** instead of run one
task at a time. This is derived entirely from the ledger — don't narrate an order
the keys don't encode; if two tasks must be ordered, wire the key.

- **Parallel waves.** A *wave* is every task whose consumed keys are all produced
  by earlier waves — tasks **in the same wave have no dependency between them and
  can run at once**. The summary's **State** column is the per-task view (a task
  still waiting on an upstream artifact reads **🔒 Not started**; a ready task is
  **⬜ Not started**). Present the plan as waves, not a flat list. For the Workday
  backbone: environment provisioning and the firewall allowlist are both ready at
  kickoff (Wave 0); once the environment exists, **SSO (Cloud App Admin) ∥ tenant
  (Workday Admin) ∥ ESS install (Env Maker)** all open together (Wave 1) — three
  roles working at once.
- **Parallel across roles vs. one person.** Two same-wave tasks owned by
  **different** roles are genuinely concurrent. Two owned by the **same** role are
  independent in the graph but will **serialize on one assignee** — call that out
  so the sponsor can staff a second holder when it sits on the long pole.
- **Blocked = waiting on a producer.** A task can't start until **every** key it
  consumes has been produced. The Workday connect task
  is a **cross-role join**: it waits for the verified environment, installed ESS
  agent, SSO, tenant configuration, and firewall output. Name every actual missing
  input, not just the number of dependencies.
- **Critical path = the long pole.** The longest `produces`→`consumes` chain sets
  the minimum end-to-end time; tasks off it have slack. Surface it so the sponsor
  optimizes the right thing. For a knowledge→read→write rollout the **scenario
  governance chain** (knowledge before reads, reads before writes) is usually the
  critical path — *not* the Workday connection, whose identity/tenant/firewall
  setup finishes early (by Wave 2) and then waits. The lever is to parallelize
  **authoring** (a second Env Maker), not to rush the connector.

Say all of this in plain language — the waves, who can go at once, what's blocked
on whom, and the long pole — right after you show the task summary, then go to
Phase 4.
