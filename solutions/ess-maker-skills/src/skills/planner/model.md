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
| Create/bind env & run setup | `--skill onboarding` | `primaryEnvironment` | — | `power-platform-admin` |
| Check readiness | `--skill flightcheck` | `readinessReport` | `primaryEnvironment` | `power-platform-admin` |
| Connect Workday | `--skill connect` | `workdayConnection,workdayEntraApp` | `primaryEnvironment` | `integration-owner` |
| Connect ServiceNow | `--skill connect` | `servicenowConnection` | `primaryEnvironment` | `integration-owner` |
| Author scenario topics | `--skill topics` | `topic:<name>` | env + connections | `maker` |
| Generate evals | `--skill evaluations` | `evalSuite` | `primaryEnvironment` | `eval-author` |
| Publish the agent | `--action-kind portal --ref <publish doc>` | — | built agent | `power-platform-admin` |

`produces`/`consumes` keys drive ordering ("blocked until produced") and are
what Phase 5 captures. When the tasks are in, show the summary and go to Phase 4.
