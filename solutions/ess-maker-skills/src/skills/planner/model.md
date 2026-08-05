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

> **Person comes later.** Today the role is pooled and the sponsor picks a person
> (Phase 4, Flow 1). A future step resolves *who holds the role* from an external
> roles API (the `roles.py` `RoleSource` seam — `list_holders(role)`), and a Task
> can then be assigned a **user together with the role** (`assign --role R
> --person <oid>`). Do not hardcode people; keep the role Learn-grounded.

## A Task is not a skill's steps

A kit skill (e.g. `connect`) is itself a multi-step procedure with its own
checklist and steps. Those steps stay **inside the skill** — they do NOT become
separate Tasks, and you do NOT add both "run connect" and its checklist items.
"Connect Workday" is **one** Task. Reasons: one assignee does all its steps in
one sitting; the steps are runtime-variable (e.g. simplified vs legacy Workday);
and the skill owns its own procedure.

**Split a Task only on a role boundary.** If the docs put part of the work on a
*different* role (e.g. an Entra admin registers the app while an integration
owner creates the connection), make that part its own Task. If one admin holds
all of it, keep it as one Task. Role boundary = Task boundary; never split by
step.

## Typical greenfield backbone

The "how" is the **description** (say which command to run in prose); `produces`/
`consumes` drive ordering and capture; the role is grounded from Learn.

| Task (title) | Description (what & how) | Produces | Consumes | Role (grounded) |
|------|--------|----------|----------|-----------------|
| Run setup | Run `/setup` to onboard the ADK to the deployed agent (records the environment & agent details) | `primaryEnvironment` | — | `power-platform-admin` |
| Check readiness | Run `/flightcheck` to validate the environment | `readinessReport` | `primaryEnvironment` | `power-platform-admin` |
| Connect Workday | Run `/connect` to connect Workday to the agent | `workdayConnection,workdayEntraApp` | `primaryEnvironment` | `integration-owner` |
| Connect ServiceNow | Run `/connect` to connect ServiceNow | `servicenowConnection` | `primaryEnvironment` | `integration-owner` |
| Author scenario topics | Run `/create` to author the scenario topics | `topic:<name>` | env + connections | `maker` |
| Generate evals | Run `/evaluate` to generate the eval suite | `evalSuite` | `primaryEnvironment` | `eval-author` |
| Publish the agent | In the Power Platform admin center, publish the agent (see the Learn publish doc) | — | built agent | `power-platform-admin` |

`produces`/`consumes` keys drive ordering ("blocked until produced") and are
what Phase 6 captures. The setup task is the one that **`--produces primaryEnvironment`**.
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
Be accurate about what `/setup` (onboarding) does: it **connects the kit to an
ESS agent that is already deployed in a Power Platform environment and records
its details** — it does *not* create the environment or install ESS. For a
brand-new tenant, provisioning the environment and installing the ESS agent are
**portal/admin prerequisites**; add a task described as a portal/admin step before
`/setup` if they don't exist yet.

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
# 1. PP admin onboards the ADK (records the environment details)
python scripts/planner/cli.py add-task --id T1 --title "Run setup" --description "Run /setup to onboard the ADK to the deployed agent (records the environment)" --role power-platform-admin --produces primaryEnvironment
# 2. one connect task PER system (role grounded from the connect page + Learn)
python scripts/planner/cli.py add-task --id T2 --title "Connect Workday" --description "Run /connect to connect Workday to the ESS agent and follow its steps" --role integration-owner --produces "workdayConnection,workdayEntraApp" --consumes primaryEnvironment
python scripts/planner/cli.py add-task --id T3 --title "Connect ServiceNow" --description "Run /connect to connect ServiceNow to the ESS agent" --role integration-owner --produces servicenowConnection --consumes primaryEnvironment
# 3. authoring per scenario area (knowledge before ticketing — register the dependency)
python scripts/planner/cli.py add-task --id T4 --title "Set up HR knowledge" --description "Run /create to author the HR knowledge topics" --role maker --produces "topic:hr-knowledge" --consumes primaryEnvironment
python scripts/planner/cli.py add-task --id T5 --title "Author HR ticketing topics" --description "Run /create to author the HR ticketing topics" --role maker --produces "topic:hr-ticketing" --consumes "primaryEnvironment,servicenowConnection"
# 4. evals + publish
python scripts/planner/cli.py add-task --id T6 --title "Generate evals" --description "Run /evaluate to generate the eval suite" --role eval-author --produces evalSuite --consumes primaryEnvironment
python scripts/planner/cli.py add-task --id T7 --title "Publish the agent" --description "In the Power Platform admin center, publish the agent (see the Learn publish doc)" --role power-platform-admin --consumes primaryEnvironment
```

Also register the scenarios and their dependencies (see `interview.md`) so the
plan shows knowledge-before-ticketing. Then show the summary and go to Phase 4.
