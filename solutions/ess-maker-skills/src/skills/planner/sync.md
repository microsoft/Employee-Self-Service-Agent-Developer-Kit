# Planner Skill — sync the Plan with the shared planner

The local Plan (`workspace/plan/plan.json`) is a **cache**. The source of truth
is the **shared planner** — a service every maker on the agent shares, reached
through the planner tools available to you. This file is the concrete flow for
keeping the two in step: pull an existing plan on entry, and push a newly
authored plan as one object.

**Two rules that never bend:**

- **Never name or hint at the backend.** To the sponsor there is just *"the
  plan"*. Never say where it lives, that it "synced", or that a service/tool was
  involved. The pull/push is invisible — you just show the plan.
- **The CLI never talks to the network; the tools never touch local files.** The
  CLI (`scripts/planner/cli.py`) only reads/writes the local cache. The planner
  tools only talk to the service. You are the bridge: you carry JSON between
  `export-remote-plan`/`import-remote-plan` and the tools.

If a planner tool reports it needs sign-in, ask the sponsor to authenticate once,
then retry the same call. If the tools stay unreachable, fall back to the local
cache and carry on — planning is never blocked by the service being offline.

## Identify the project (always first)

Every plan lives under the ESS project. Get-or-create it — the call is
idempotent, so it's safe to run on every entry:

- Call **`create_agent_configuration_project`** with `{"name": "Employee Self-Service"}`.
- Keep the returned **`projectId`** (and its `etag`); you need `projectId` for
  every plan/task call below. The project entity also names its one plan in
  **`activePlanId`** — keep that too; the Pull step below resolves the plan from
  it. Do **not** list-and-match on the display name — the
  tenant may render it differently. The name must be one of the supported
  configuration experiences — **`Employee Self-Service`** or **`Workforce
  Insights`**; any other value is rejected with a 400 (`name must be one of the
  supported configuration experiences`). Matching is case- and
  whitespace-insensitive, so casing/spacing is forgiven, but the words must match
  a supported experience exactly.

## Pull — resume from the service on entry

Run this the moment `/planner` starts, before deciding whether to interview:

1. **Resolve the one plan from the project.** A project has **at most one active
   plan** — activating a plan archives whatever was active before — and the
   project entity names it in **`activePlanId`** (from the get-or-create you just
   ran). There is never a genuine "which plan?" choice, so never present one and
   never fall back to "the most recently updated":
   - **`activePlanId` is set** → that is the plan. Use it directly; skip the
     listing.
   - **`activePlanId` is null** → there may still be an un-activated **Draft** (a
     plan that was pushed but not yet activated — activation is what stamps
     `activePlanId`). Call **`list_project_plans`** (it returns only non-archived
     plans) and take the single plan it returns, if any; that is the Draft to
     resume.
2. **If a plan was resolved** (an `activePlanId` plan or a lone Draft), hydrate
   it:
   1. **`get_project_plan`** (`projectId`, `planId`) — the plan entity.
   2. **`list_project_plan_tasks`** (`projectId`, `planId`) — its tasks.
   3. Write the two results into a temp file as one object:
      `{"plan": <get_project_plan result>, "tasks": <list_project_plan_tasks result>}`
      at `workspace/plan/.remote.json`.
   4. Hydrate the cache:
      `python scripts/planner/cli.py import-remote-plan --input workspace/plan/.remote.json`
      then delete the temp file.
   5. Resume from the refreshed cache (`summary`, Flow 2, next actions) exactly as
      the **First** section of `SKILL.md` describes.
3. **If the service has no plan but a local `plan.json` exists**, it's an
   un-pushed draft — resume it locally and, once the sponsor is happy, **push** it
   (below).
4. **If neither exists**, start fresh: interview → build the plan through the
   phases → push.

`import-remote-plan` writes through without a local validation gate (the service
is authoritative). It prints any validation notes as warnings — treat them as
diagnostics, never as a reason to refuse the plan.

## Push — publish a newly authored plan as one object

**Publishing is automatic and mandatory, not optional.** The moment the plan is
modelled and assigned (end of Phase 4), push it — without waiting for the sponsor
to ask. A plan that still shows `(local, not synced)` / has no plan id lives only
in the local cache and has **not** been persisted; the sponsor's work is at risk
until it is pushed. Re-run this push after any later change the tools didn't
already mirror.

After you've built the plan locally through the phases (research → interview →
model → assign), publish it in **one** create call rather than task-by-task:

1. **Name the configuring agent.** Pick the enum that matches the agent the
   sponsor is configuring and set it:
   `python scripts/planner/cli.py set-agent-name --name <AgentName>`
   where `<AgentName>` is one of:
   - `EmployeeSelfServiceHRCEA` — HR, custom engine agent
   - `EmployeeSelfServiceHRDA` — HR, declarative agent
   - `EmployeeSelfServiceITCEA` — IT, custom engine agent
   - `EmployeeSelfServiceITDA` — IT, declarative agent
   If it isn't obvious from the interview (HR vs IT, custom-engine vs
   declarative), ask the sponsor in plain language ("Is this for HR or IT?").
2. **Build the create body:**
   `python scripts/planner/cli.py export-remote-plan` — this prints the JSON body
   (configuring agent, acceptance criteria, context, and every task inline).
3. **Push it (the plan is created in Draft):** call **`create_project_plan`**
   with the `projectId`, that body, and an **`idempotencyKey`**. Generate the key
   once when the publish starts (a fresh UUID) and treat it as belonging to this
   draft — reuse the *exact same* key on every retry of this same publish. Keying
   the create is what makes a retry safe: the service collapses a replay onto the
   same plan instead of creating a duplicate. (An **unkeyed** create is
   deliberately *not* auto-retried, because a blind replay could duplicate the
   plan — so if a keyless push fails ambiguously, never just fire it again; add a
   key and retry with that.) The plan and all its tasks are created
   atomically, in **Draft**. Keep the returned `planId` and `etag`. A Draft plan
   holds all its tasks, but they can't be *mutated* (assigned, reassigned,
   state-changed) until the plan is **Active** — and **the backend never
   auto-activates a plan**. Activation is therefore an explicit step you take
   yourself, at the moment the first assignment happens (step 6). Do **not**
   activate here.
4. **Re-hydrate so the cache carries the server ids** (planId, task ids, etag):
   `get_project_plan` + `list_project_plan_tasks` → write
   `{"plan": <get_project_plan result>, "tasks": <list_project_plan_tasks result>}`
   to `workspace/plan/.remote.json` → `import-remote-plan --input ...` → delete
   the temp file. The plan is now cached as **Draft** with real ids.
5. **Show the plan and let the sponsor choose what's next — don't activate yet.**
   Present the plan and offer the Markdown for them to **download and review**
   (the render is in `src/skills/planner/SKILL.md`). Then offer a plain-language
   choice of where to go next:
   - **Put people on the roles** — record real people against the plan's
     attestable roles so pooled role work becomes visible
     (`src/skills/roles/nudge.md` → `src/skills/roles/attest.md`).
   - **Assign tasks to people** — hand specific tasks to named owners
     (`src/skills/planner/assign.md`).
   - **Keep iterating on the plan** — refine the objective or tasks before anyone
     is put on it; this stays in **Draft**, so just re-push the edits.
   Iterating leaves the plan in Draft. Choosing either kind of assignment is what
   puts the plan into motion — so it **activates** the plan (step 6).
6. **Activate on the first assignment — explicitly; the backend won't.** The
   first time the sponsor assigns a role or a task, activate *before* recording
   it: call **`update_project_plan`** with `{"status": "Active"}` and the plan's
   Draft `etag`. Activation returns a **new `etag`**, but that etag belongs to the
   **plan** — so re-hydrate first (`get_project_plan` + `list_project_plan_tasks`
   → `import-remote-plan`) so the cache reflects the **Active** status and the
   fresh per-task etags, **then** record the assignment with the etag that matches
   the call you make:
   - **Reassigning a task** (`update_project_plan_task`) needs **that task's**
     etag — from the re-hydrated cache or a fresh `get_project_plan` — never the
     plan's activation etag, which would 412.
   - **A first role attestation** (`create_role_assigned_project_plan_task`) is a
     create and takes **no** etag at all.
   Once the plan is Active, later assignments need no re-activation.

If `export-remote-plan` errors that the configuring agent name is required, you
skipped step 1 — set it, then re-export.

## Ongoing edits — keep the service authoritative

Once a plan is on the service, route mutations through the tools (not just the
local cache), then re-hydrate so the cache reflects the server's response:

- **Change a task's state:** `set_project_plan_task_state`.
- **Record what a task produced:** `complete_project_plan_task` (Phase 6 capture).
- **Edit task content** (title/description/produces/consumes): `update_project_plan_task`.
- **Add a task later:** `create_project_plan_task` (or
  `create_role_assigned_project_plan_task` for a role-owned task).

After a batch of edits, re-pull (`get_project_plan` + `list_project_plan_tasks` →
`import-remote-plan`) so the local view and the Markdown summary match the service.

## Flow 2 — "what am I assigned?" is answered by the service

The service stores the role→person mapping and filters tasks by the caller's
roles. So for "what are my tasks?", call **`list_project_plan_tasks_for_caller`**
(`projectId`, `planId`) and present exactly what it returns — do not re-derive
role gating locally. Only fall back to the local `mine` command
(`src/skills/planner/mytasks.md`) when the service is unreachable.
