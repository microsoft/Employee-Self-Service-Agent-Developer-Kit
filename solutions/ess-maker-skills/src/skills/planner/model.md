# Planner — Phase 3: Model the Tasks

Turn the grounded prerequisite graph (Phase 1) into **atomic Tasks**. A Task is
the smallest unit one owner can complete end-to-end, and it maps to a single
**action** — *usually* a kit skill, but sometimes a manual/portal/admin step
with no kit skill.

Add each Task with:

```
python scripts/planner/cli.py add-task --id <T#> --title "<title>" \
  [--skill <kitSkill> | --action-kind <portal|manual|external> --ref <docUrl>] \
  --role <grounded-role> \
  [--produces <key,key>] [--consumes <key,key>]
```

The `--role` and `--produces` keys come from the **Learn docs** (Phase 1) — not
hardcoded and not from the sponsor. Set `--role` to pool the Task to that role
for now; Phase 4 assigns a person.

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

| Task | Action | Produces | Consumes | Role (grounded) |
|------|--------|----------|----------|-----------------|
| Run `/setup` — onboard the ADK to the deployed agent (records the environment & agent details) | `--skill onboarding` | `primaryEnvironment` | — | `power-platform-admin` |
| Check readiness | `--skill flightcheck` | `readinessReport` | `primaryEnvironment` | `power-platform-admin` |
| Connect Workday | `--skill connect` | `workdayConnection,workdayEntraApp` | `primaryEnvironment` | `integration-owner` |
| Connect ServiceNow | `--skill connect` | `servicenowConnection` | `primaryEnvironment` | `integration-owner` |
| Author scenario topics | `--skill topics` | `topic:<name>` | env + connections | `maker` |
| Generate evals | `--skill evaluations` | `evalSuite` | `primaryEnvironment` | `eval-author` |
| Publish the agent | `--action-kind portal --ref <publish doc>` | — | built agent | `power-platform-admin` |

`produces`/`consumes` keys drive ordering ("blocked until produced") and are
what Phase 5 captures. When the tasks are in, show the summary and go to Phase 4.

**Native connector vs. custom flow.** A `--skill connect` task is only valid for a
system ESS has a **native integration** for (Workday, ServiceNow HRSD/ITSM, SAP
SuccessFactors — confirm from Phase‑1 Learn research). For a captured system with
**no** native connector (e.g. ADP, Jira, Dynamics 365, custom HTTP API), emit a
**`--skill create`** (custom Power Automate flow) task instead — do not fabricate a
`connect` task for it. SharePoint / M365 content is a **knowledge source**, so it's
the topics/knowledge task, not a connect task.

## First step for a first-time / greenfield rollout

The first task is almost always the **Power Platform admin running `/setup`**.
Be accurate about what `/setup` (onboarding) does: it **connects the kit to an
ESS agent that is already deployed in a Power Platform environment and records
its details** — it does *not* create the environment or install ESS. For a
brand-new tenant, provisioning the environment and installing the ESS agent are
**portal/admin prerequisites**; add a `--action-kind portal` task before
`/setup` if they don't exist yet.

## Back-propagation — how the admin's setup details flow to later tasks

When the admin runs `/setup`, it writes the environment and agent details
(`environmentId`, `dataverseEndpoint`, agent slug/schema/folder) into
`.local/config.json`, and the planner pins `primaryEnvironment` onto the plan
(Phase 5). Those details then reach every downstream task **two ways**, so
nobody re-enters what the admin already set up:

- Every kit skill (`/connect`, `/create`, `/evaluate`) reads `.local/config.json`
  directly for the agent folder / slug / schema.
- Tasks that `consume primaryEnvironment` read the pinned value off the plan.

This is the back-propagation: capture the admin's output once, and every task
that needs it — including topic **create** and eval generation — picks it up.

## Emit the full task set now (do not stop at setup)

From the systems and scenarios captured in Phase 2, create **every** task now —
not just setup. For *"file HR tickets + get HR knowledge, on Workday + ServiceNow"*
that is:

```
# 1. PP admin onboards the ADK (records the environment details)
python scripts/planner/cli.py add-task --id T1 --title "Run /setup - onboard the ADK to the deployed agent" --skill onboarding --role power-platform-admin --produces primaryEnvironment
# 2. one connect task PER system (grounded role from the connect skill + Learn)
python scripts/planner/cli.py add-task --id T2 --title "Connect Workday" --skill connect --role integration-owner --produces "workdayConnection,workdayEntraApp" --consumes primaryEnvironment
python scripts/planner/cli.py add-task --id T3 --title "Connect ServiceNow" --skill connect --role integration-owner --produces servicenowConnection --consumes primaryEnvironment
# 3. authoring per scenario area (knowledge before ticketing — register the dependency)
python scripts/planner/cli.py add-task --id T4 --title "Set up HR knowledge" --skill topics --role maker --produces "topic:hr-knowledge" --consumes primaryEnvironment
python scripts/planner/cli.py add-task --id T5 --title "Author HR ticketing topics" --skill topics --role maker --produces "topic:hr-ticketing" --consumes "primaryEnvironment,servicenowConnection"
# 4. evals + publish
python scripts/planner/cli.py add-task --id T6 --title "Generate evals" --skill evaluations --role eval-author --produces evalSuite --consumes primaryEnvironment
python scripts/planner/cli.py add-task --id T7 --title "Publish the agent" --action-kind portal --ref "<Learn publish doc>" --role power-platform-admin --consumes primaryEnvironment
```

Also register the scenarios and their dependencies (see `interview.md`) so the
plan shows knowledge-before-ticketing. Then show the summary and go to Phase 4.
