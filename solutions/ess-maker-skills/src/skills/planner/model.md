# Planner — Phase 3: Model the Tasks

Turn the grounded prerequisite graph (Phase 1) into **atomic Tasks**. A Task is
the smallest unit one owner can complete end-to-end. Each Task is described by a
**title** and a **description** — nothing else is needed to understand it.

Add each Task with:

```
python scripts/planner/cli.py add-task --id <T#> \
  --title "<short imperative title>" \
  --description "<self-explanatory: what to do and how — including which command to run, e.g. 'Run /connect to connect Workday to the ESS agent and follow its steps'>" \
  --role <grounded-role> \
  [--produces <key,key>] [--consumes <key,key>]
```

**Title + description must be self-explanatory.** A reader (or the assignee)
should know exactly what to do from those two alone — including which kit command
to run (say it in the description, e.g. "run `/connect`", "in the Power Platform
admin center, register an Entra app…"). **Do not** encode the "how" in structured
fields like an action/kit-skill type — those are not task data; the description
carries it. (The setup task is identified by what it **produces**, below — not by
any skill field.)

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
(Phase 1; the `research --extract` step surfaces the role candidates). Keep the
Learn page URL in your research notes (it lives in the research context, §7.6 —
not as a task field). `--role` pools the Task to that role for now (any holder can
pick it up, Flow 2); Phase 4 assigns the actual person.

**Emit the role as its _exact WeveNova id_ — verbatim, never slugified.** WeveNova
validates a task's role **ordinally and case-sensitively** with no normalization,
so a slug like `power-platform-administrator`, a lowercase `workday administrator`,
or a spaceless `PowerPlatformAdministrator` is **rejected** — the wire id is
`Power Platform Administrator` / `WorkdayAdmin`. Run `python
scripts/planner/roles_cli.py roles` to list the valid ids (the `--role` argument
also accepts a display name and normalises it to the id, e.g. `Workday
Administrator` → `WorkdayAdmin`). The valid universe (id → provider):

- Internal authority (PascalCase): `AgentOwner`, `AgentEditor`, `AgentAnnotator`,
  `AgentViewer`.
- External attestable (compact id, **not** the display name): `WorkdayAdmin`,
  `ServiceNowAdmin`, `ServiceNowKnowledgeManager`.
- Entra attestable (id == display, spaced Title Case): `Global Administrator`,
  `Network Administrator`, `User Administrator`, `Power Platform Administrator`.
- PowerPlatform attestable: `Environment Maker`.

Ground each task's role to the **nearest valid id** for the authority the Learn
step actually requires (e.g. registering the Workday enterprise app → the Entra
`Global Administrator`; standing up the connection in the environment →
`Environment Maker`). Do not invent a role that isn't in this list.

> **Person comes later.** Today the role is pooled and the sponsor picks a person
> (Phase 4, Flow 1). Naming the person who holds a role — and persisting it as a
> plan **attestation** — belongs to the separate **`/roles` skill**
> (`src/skills/roles/SKILL.md`): it resolves the person (via the WeveNova people
> directory) and records
> them so they later see the role's pooled tasks. The planner only *grounds* the
> role onto the task; it does not name people. Keep the role Learn-grounded.

## A Task is not a skill's steps — but split on every role boundary

A kit skill (e.g. `connect`) is itself a multi-step procedure with its own
checklist. Those individual steps stay **inside the skill** — they do NOT each
become a Task, and you do NOT add both "run connect" and its checklist items.

**But split a Task on every role boundary. Role boundary = Task boundary.** A
Task is atomic: exactly one role can complete it. If the docs put part of the
work on a *different* role, that part is its own Task — never split by step,
always split by role.

**Read the skill's role map before you emit tasks — do NOT assume one skill =
one task.** Before emitting the task(s) for a system, read that system's setup
checklist and its role gating (`src/skills/setup/<system>/tasks.md` and
`src/reference/ess-docs/setup/role-gating.md` — each checklist item carries a
`role:`), and emit **one Task per distinct role** the flow requires.

**Worked example — "Connect Workday" is multi-role, never one Task.** Standing up
Workday spans several roles (grounded from `setup/workday/tasks.md`), so it
decomposes into role-based Tasks. Each role is the **exact valid WeveNova id** for
the authority the step needs:

| Task (title) | Role id (verbatim) | Provider | Grounded in | Produces |
|---|---|---|---|---|
| Set up Workday single sign-on (Entra) | `Global Administrator` | Entra | S3.1–S3.7 | `workdayEntraApp` |
| Configure the Workday tenant | `WorkdayAdmin` | External | S4.1–S4.4 | `workdayTenantConfig` |
| Install the Workday extension pack & connect | `Environment Maker` | PowerPlatform | S5.1–S5.7 | `workdayConnection` |
| Allow Workday egress through the firewall | `Network Administrator` | Entra | S5.8 | `workdayNetworkAllowlist` |

Use the role id **verbatim** as `--role` (no slugifying, no lowercasing, no
hyphenation) — WeveNova stores and validates it character-for-character. `WorkdayAdmin`
is the compact External id (the display name is *Workday Administrator*); the Entra
and PowerPlatform ids are already the spaced Title-Case display strings. Map each
checklist `role:` to the nearest valid id from the roles listing
(`python scripts/planner/roles_cli.py roles`); the id set is the
same for every plan and matches the WeveNova registry, while the Learn page stays
the grounding anchor. Confirm the exact split from that skill's checklist; never
assume it.

**The converse — a _single-role_ skill is exactly one Task.** When every step a
kit skill runs is gated to the **same** role, do **not** decompose it: emit a
single "run `/<skill>`" Task for that role. Its **description** carries what the
skill accomplishes (grounded from Learn) and the command to run — *just run
`/setup`* — plus a pointer to the skill, so anyone who asks *what* it does gets the
Learn-sourced answer while the skill itself owns the step-by-step. Splitting a
single-role skill into several **same-role** Tasks — e.g. a separate "provision the
environment" **and** "run setup" when `/setup` already provisions the environment as
its own first step (`setup/workday/provision-power-platform-environment.md`) — is
splitting by *step*, not by *role*, and is exactly what this rule forbids.
**Classify each kit skill in the research phase (§1) by reading its role map: one
role → one Task; many roles → one Task per role.**

## Typical greenfield backbone

The "how" is the **description** (say which command to run in prose); `produces`/
`consumes` drive ordering and capture; the role is grounded from Learn.

| Task (title) | Description (what & how) | Produces | Consumes | Role (verbatim id) |
|------|--------|----------|----------|-----------------|
| Run setup | Run `/setup` to onboard the ADK to the deployed agent — records the environment **and clones the agent** into the workspace | `primaryEnvironment, essAgent` | — | `Power Platform Administrator` |
| Check readiness | Run `/flightcheck` to validate the environment | `readinessReport` | `primaryEnvironment` | `Power Platform Administrator` |
| Set up Workday SSO (Entra) | Register/configure the Workday enterprise app for SSO — `setup/workday/tasks.md` §3 | `workdayEntraApp` | `primaryEnvironment` | `Global Administrator` |
| Configure the Workday tenant | Create the API client & tenant config in Workday — §4 | `workdayTenantConfig` | `primaryEnvironment` | `WorkdayAdmin` |
| Install Workday pack & connect | Run `/connect` — install the Workday extension pack and create the connection — §5 | `workdayConnection` | `workdayEntraApp, workdayTenantConfig` | `Environment Maker` |
| Allow Workday through the firewall | Attest the Workday egress allowlist — §5 (S5.8) | `workdayNetworkAllowlist` | — | `Network Administrator` |
| Connect ServiceNow | Run `/connect` — decompose per its own checklist `role:` items (read `setup/servicenow/tasks.md`) | `servicenowConnection` | `primaryEnvironment` | `ServiceNowAdmin` *(+ `Environment Maker` per its checklist)* |
| Author scenario topics | Run `/create` to author the scenario topics | `topic:<name>` | env + connections | `Environment Maker` |
| Generate evals | Run `/evaluate` to generate the eval suite | `evalSuite` | `primaryEnvironment` | `Environment Maker` |
| Publish the agent | In the Power Platform admin center, publish the agent (see the Learn publish doc) | — | built agent | `Power Platform Administrator` |

`produces`/`consumes` keys are the **expected** outputs, and drive ordering
("blocked until produced"). Phase 6 capture is **generic** — the setup task lists
`--produces primaryEnvironment,essAgent`, but `capture-setup` diffs the whole
`.local/config.json` and pins **every** id + name (and any other artifact a skill
recorded) — the environment, the cloned agent, and anything else the run wrote
(a connection, an app…) — even outputs the task didn't pre-declare (see
`capture.md`).
When the tasks are in, show the summary and go to Phase 4.

**Native connector vs. custom flow.** A "run `/connect`" task is only valid for a
system ESS has a **native integration** for (Workday, ServiceNow HRSD/ITSM, SAP
SuccessFactors — confirm from Phase‑1 Learn research). For a captured system with
**no** native connector (e.g. ADP, Jira, Dynamics 365, custom HTTP API), describe a
**"run `/create`" (custom Power Automate flow)** task instead — do not fabricate a
`connect` task for it. SharePoint / M365 content is a **knowledge source**, so it's
the topics/knowledge task, not a connect task.

## First step for a first-time / greenfield rollout

The first task is almost always the **Power Platform admin running `/setup`**.
`/setup` is a **single Power Platform Administrator Task** even though it does a
lot: its first steps **verify or create** the Power Platform environment +
Dataverse and confirm Copilot Studio capacity
(`setup/workday/provision-power-platform-environment.md`), then record the
environment and clone the agent into the workspace
(`--produces primaryEnvironment,essAgent`). Because provisioning is `/setup`'s own
first step, **do not emit a separate "provision the environment" Task ahead of it
for the Power Platform Administrator** — the one "run `/setup`" Task covers it
(single-role rule above). Only carve a step out into its own Task when a
**different** role owns it — e.g. the base ESS agent install (`Environment Maker`,
`install-ess.md`) or the multi-role Workday split (SSO, tenant, connect, firewall).

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

From the systems and scenarios captured in Phase 2, create **every** task now —
not just setup. For *"file HR tickets + get HR knowledge, on Workday + ServiceNow"*
that is:

```
# 1. PP admin onboards the ADK (records the environment AND clones the agent)
python scripts/planner/cli.py add-task --id T1 --title "Run setup" --description "Run /setup to onboard the ADK to the deployed agent (records the environment and clones the agent)" --role "Power Platform Administrator" --produces "primaryEnvironment,essAgent"
# 2. Workday is MULTI-ROLE — read setup/workday/tasks.md and emit one task per role (use the exact WeveNova role id)
python scripts/planner/cli.py add-task --id T2 --title "Set up Workday SSO (Entra)" --description "Register/configure the Workday enterprise app for SSO — Entra app registration (setup/workday/tasks.md S3.1-S3.7)" --role "Global Administrator" --produces workdayEntraApp --consumes primaryEnvironment
python scripts/planner/cli.py add-task --id T3 --title "Configure the Workday tenant" --description "Create the API client and tenant config in Workday (S4.1-S4.4)" --role WorkdayAdmin --produces workdayTenantConfig --consumes primaryEnvironment
python scripts/planner/cli.py add-task --id T4 --title "Install Workday pack & connect" --description "Run /connect to install the Workday extension pack and create the connection (S5.1-S5.7)" --role "Environment Maker" --produces workdayConnection --consumes "workdayEntraApp,workdayTenantConfig"
python scripts/planner/cli.py add-task --id T5 --title "Allow Workday through the firewall" --description "Attest the Workday egress allowlist (S5.8)" --role "Network Administrator" --produces workdayNetworkAllowlist
# 3. ServiceNow — decompose per its OWN checklist role: items (read setup/servicenow/tasks.md); shown here collapsed
python scripts/planner/cli.py add-task --id T6 --title "Connect ServiceNow" --description "Run /connect to connect ServiceNow (split per its checklist role: items)" --role ServiceNowAdmin --produces servicenowConnection --consumes primaryEnvironment
# 4. authoring per scenario area (knowledge before ticketing — register the dependency)
python scripts/planner/cli.py add-task --id T7 --title "Set up HR knowledge" --description "Run /create to author the HR knowledge topics" --role "Environment Maker" --produces "topic:hr-knowledge" --consumes primaryEnvironment
python scripts/planner/cli.py add-task --id T8 --title "Author HR ticketing topics" --description "Run /create to author the HR ticketing topics" --role "Environment Maker" --produces "topic:hr-ticketing" --consumes "primaryEnvironment,servicenowConnection"
# 5. evals + publish
python scripts/planner/cli.py add-task --id T9 --title "Generate evals" --description "Run /evaluate to generate the eval suite" --role "Environment Maker" --produces evalSuite --consumes primaryEnvironment
python scripts/planner/cli.py add-task --id T10 --title "Publish the agent" --description "In the Power Platform admin center, publish the agent (see the Learn publish doc)" --role "Power Platform Administrator" --consumes primaryEnvironment
```

Also register the scenarios and their dependencies (see `interview.md`) so the
plan shows knowledge-before-ticketing. Then show the summary and go to Phase 4.

## Naming people & "what am I assigned?" — the `/roles` skill

The planner stops at *grounding* the role onto the task. Binding a named **person**
to a role (**attestation**), listing/revoking those records, and answering "what
am I assigned?" (Flow 2) live in the separate **`/roles` skill**
(`src/skills/roles/SKILL.md`), backed by `python scripts/planner/roles_cli.py`.
That skill resolves the person by name (via the WeveNova people directory), attests them plan-scoped,
and — once attested — a person's `caller-tasks` shows their direct tasks plus the
pooled tasks for every role they hold. Hand off to `/roles` for anything about
*who* holds a role; keep the planner focused on the tasks and their grounded roles.
