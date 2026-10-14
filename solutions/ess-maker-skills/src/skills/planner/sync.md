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
- **Importing: hand each tool result to the CLI as its own file — never splice
  them yourself.** Re-hydrating always means
  `import-remote-plan --plan-file <get_project_plan result> --tasks-file <list_project_plan_tasks result>`,
  pointing each flag at the file holding that tool's result (the temp file the
  runtime saves a large result to, or a file you write the result to). **Do not**
  build a combined `{plan, tasks}` object or pipe the results through PowerShell
  `ConvertFrom-Json`/`ConvertTo-Json`: a large tool result is stored as the
  payload followed by a trailing `{"result": …}` envelope, so a single-document
  JSON parser fails with *"Additional text encountered after finished reading
  JSON content"*. The CLI extracts the payload past that envelope for you.

**Sign-in is the tool's job — never ask the sponsor whether to sign in.** Each
planner tool authenticates itself, and on an expired/rejected token (a 401) it
renews in place: silently when the refresh token is still good (no window), and
otherwise by **opening a browser sign-in itself** and replaying the call once the
sponsor finishes. That browser prompt is the *only* interaction sign-in ever needs —
so you never diagnose it, never narrate the mechanism, never read any MCP/auth
source to explain it, and above all **never present an `ask_user` / "how would you
like to proceed?" choice about signing in.** Treat each call by walking this
ladder **in order** — never cycle back up it:

- **It succeeds** — possibly after a sign-in window appeared mid-call and the
  sponsor completed it. Expected; just carry on. Say nothing about sign-in.
- **It still returns an explicit "sign in again" (HTTP 401)** after the tool's own
  browser sign-in — the server can be wedged on a dead in-memory session that only a
  fresh process clears. Take **one** mechanical recovery, then retry the same call
  **once**: restart the `ess-planner` MCP server — run the editor's *MCP: Restart
  Server* command yourself if that's available to you, otherwise tell the sponsor in
  one plain line to run it (Command Palette → *MCP: Restart Server* → `ess-planner`).
  The restart rebuilds the client and re-triggers a clean sign-in.
- **It 401s again even after that restart + retry** — stop. Say one plain line —
  *"I'll keep the plan local for now; it'll save to the shared space on the next
  successful sync"* — and continue locally. A 401 that survives a fresh sign-in and a
  restart means the account can't reach the shared plan; nothing more you do helps.
- **Any non-401 failure** (network error, 5xx) — fall back to the local cache the
  same way, silently.

That single restart is the **only** mechanical recovery you ever take. Do **not**
clear or inspect token caches, read any MCP/auth source, check the token source, or
reason about the client's internals — that is the spiral to avoid, not a path to a
fix. The whole budget is: one 401 → at most one restart + one retry → then local.
Never open a diagnostic thread, and the sponsor is only ever prompted by the tool's
own sign-in window or that one restart line — never by a "how would you like to
proceed?" question. Planning is never blocked by the service.

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
   3. Hydrate the cache by handing each result to the CLI as its own file (see
      the import rule above — do **not** hand-stitch a `{plan, tasks}` object or
      run the results through PowerShell JSON cmdlets):
      `python scripts/planner/cli.py import-remote-plan --plan-file <get_project_plan result> --tasks-file <list_project_plan_tasks result>`
   4. Resume from the refreshed cache (`summary`, Flow 2, next actions) exactly as
      the **First** section of `SKILL.md` describes.
3. **If the service has no plan but a local `plan.json` exists**, it's an
   un-shared draft — resume it locally and, **when the sponsor asks to share it**,
   store it (the *Share* step below).
4. **If neither exists**, start fresh: interview → build the plan through the
   phases → show it locally → share it when the sponsor asks.

`import-remote-plan` writes through without a local validation gate (the service
is authoritative). It prints any validation notes as warnings — treat them as
diagnostics, never as a reason to refuse the plan.

**A pull never reverts an unpushed local completion.** If a task was completed
locally but its push to the service hasn't landed yet (flagged `pendingSync` —
see `src/skills/planner/capture.md`), `import-remote-plan` **preserves** it
instead of overwriting it with the service's stale `NotStarted`, and prints
`Preserved unpushed local completion(s): …`. So on entry, after the hydrate, run
`python scripts/planner/cli.py pending-sync`; if it lists any task, **sync each
now** via `complete_project_plan_task` (the capture file's *Sync each local
complete* flow) before moving on — then re-hydrate so the server's confirmation
clears the flag. This is what makes a completion that failed to push last time
reach the shared plan on the next successful entry.

## Share — store a newly authored plan to the shared planner (explicit)

**The first store is an explicit step the sponsor asks for — never automatic.** A
freshly modelled plan is built and shown **locally** (saved in the maker's
workspace); it is **not** sent to the shared space on creation. Store it only when
the sponsor asks to **share** it ("share it", "save it to the shared space", "store
it"). Do **not** push it the moment it's modelled, and do **not** wait on naming
people (naming is the Phase 4 follow-up, after the plan is shared and activated). A
plan that still shows `(local, not synced)` / has no plan id lives only in the local
cache — that is a valid resting state until the sponsor asks to share it, not a risk
to chase. **This explicit gate is only for the *first* store**; once the plan has
been shared, later changes sync automatically (see *Ongoing edits* below).

When the sponsor asks to share the plan you built locally (research → interview →
model), store it in **one** create call rather than task-by-task:

1. **Confirm whether this plan targets HR or IT — the only agent axis left.**
   The create body's `configuringAgentName` is required. The ESS agent ships as
   a **declarative agent (DA)** — that's what merges to `main` — so there is **no
   DA-vs-custom-engine choice to make**; every plan targets the DA. The only axis
   the sponsor still picks is **HR vs IT**:
   - `EmployeeSelfServiceHRDA` — HR
   - `EmployeeSelfServiceITDA` — IT
   HR-vs-IT is usually clear from the interview; confirm it in plain language
   ("Is this for HR or IT?") rather than guessing. Only once confirmed, set it:
   `python scripts/planner/cli.py set-agent-name --name <AgentName>`
2. **Build the create body:**
   `python scripts/planner/cli.py export-remote-plan` — this prints the JSON body
   (configuring agent, acceptance criteria, context, and every task inline).
3. **Store it (the plan is created in Draft):** call **`create_project_plan`**
   with the `projectId`, that body, and an **`idempotencyKey`**. Generate the key
   once when the share starts (a fresh UUID) and treat it as belonging to this
   draft — reuse the *exact same* key on every retry of this same store. Keying
   the create is what makes a retry safe: the service collapses a replay onto the
   same plan instead of creating a duplicate. (An **unkeyed** create is
   deliberately *not* auto-retried, because a blind replay could duplicate the
   plan — so if a keyless push fails ambiguously, never just fire it again; add a
   key and retry with that.) The plan and all its tasks are created
   atomically, in **Draft**. Keep the returned `planId` and `etag`. A Draft plan
   already holds all its tasks with their assignees baked in at creation, but
   those tasks can't be *mutated* (reassigned, state-changed, edited, completed)
   until the plan is **Active** — and **the backend never auto-activates a plan**.
   Activation is therefore an explicit step you take yourself, once the sponsor
   confirms the plan is ready to run (step 6). Do **not** activate here.
4. **Re-hydrate so the cache carries the server ids** (planId, task ids, etag):
   `get_project_plan` + `list_project_plan_tasks`, then hand each result to
   `import-remote-plan --plan-file <get_project_plan result> --tasks-file <list_project_plan_tasks result>`
   (one file per flag — never hand-stitch a combined object or run the results
   through PowerShell JSON cmdlets; the CLI strips the trailing `{"result": …}`
   envelope itself). The plan is now cached as **Draft** with real ids.
5. **Confirm it's saved to the shared space, then offer to activate.** The plan the
   sponsor already reviewed locally is now stored as a **Draft** with its assignees
   baked in — tell them it's saved to the shared space (plain language, never name
   the backend) and re-surface the downloadable *ESS scenario plan* link if helpful
   (the `summary` command prints the exact `📄 [ESS-scenario-plan.md](…)` line). A
   Draft's tasks are **read-only** until it's Active, so name the next step:
   - **Activate now** — the plan is ready to run; go to step 6. Activation makes
     the assigned work real and visible. From then on, put people on the
     roles (`src/skills/roles/nudge.md` → `src/skills/roles/attest.md`), hand
     tasks to named owners (`src/skills/planner/assign.md`), and capture outputs —
     all through the task tools against the **Active** plan.
   - **Not yet** — leave it in Draft. Refinement is best done **before** you share:
     once stored, local edits **can't be pushed onto a Draft** — the service has no
     "update a Draft" path (re-running `create_project_plan` makes a *new* plan, and
     a Draft's tasks are read-only), so revisions reach the server only **after
     activation** (step 6). So steer the sponsor to **finish editing locally before
     sharing**; if they still need changes once it's a Draft, activate first, then
     edit.
6. **Activate when the sponsor is ready — explicitly; the backend won't.** When
   the sponsor confirms the plan is ready to run (step 5), activate it: call
   **`update_project_plan`** with `{"status": "Active"}` and the plan's Draft
   `etag`. Activation returns a **new `etag`**, but that etag belongs to the
   **plan** — so re-hydrate first (`get_project_plan` + `list_project_plan_tasks`
   → `import-remote-plan`) so the cache reflects the **Active** status and the
   fresh per-task etags. Any later assignment change must then use the etag that
   matches the call you make:
   - **Reassigning a task** (`update_project_plan_task`) needs **that task's**
     etag — from the re-hydrated cache or a fresh `get_project_plan` — never the
     plan's activation etag, which would 412.
   - **A role attestation** (`create_role_assigned_project_plan_task`) is a
     create and takes **no** etag at all.
   Once the plan is Active, later edits and assignments need no re-activation.

   **Then make role assignment the explicit next step.** The instant the plan is
   Active, the headline next action is **assigning the roles to people** so each
   owner can see their tasks — say so plainly and offer to do it right now
   (`src/skills/roles/nudge.md` → `src/skills/roles/attest.md`). Editing still
   works after activation, but those edits now reach **both** the local plan **and**
   the shared service — route them through the task tools (*Ongoing edits* below),
   not the local cache alone.

If `export-remote-plan` errors that the configuring agent name is required, you
skipped step 1 — set it, then re-export.

## Ongoing edits — keep local and the shared plan in step

Once a plan is on the service, an edit isn't finished until it has landed on
**both** sides: the local cache (so the maker's `ESS-scenario-plan.md` reflects what
they asked for) **and** the shared planner (so every other owner — and a later pull
— sees it). Dropping either half is the bug this guards against — a local-only edit
never reaches other accounts, and a tool-only edit leaves the local `.json`/`.md`
stale — so run all three steps for every follow-up change on a live plan:

1. **Apply it locally** through the CLI — the maker-facing round-trip in
   `src/skills/planner/edit.md` writes `plan.json` and regenerates the Markdown in
   one step (and runs the coherence loop for a scope change). A capture `--complete`
   (`src/skills/planner/capture.md`) is this step for a completion.
2. **Push the same change to the service** through its matching tool — never the
   local cache alone:
   - **Change a task's state:** `set_project_plan_task_state`.
   - **Record what a task produced:** `complete_project_plan_task` (Phase 6
     capture). This is **coupled to the local complete, not a deferred step**: the
     moment a `capture-setup` / `capture-discover` / `pin-output --complete` (or an
     `edit.md` checkbox tick applied via `set-state`) flags a task `pendingSync`,
     push it in the same turn — `pending-sync` prints the exact `projectId` /
     `planId` / `taskId` / `outputs` / `etag`; call the tool, then re-hydrate to
     clear the flag. If the push can't reach the service, the completion stays
     `pendingSync` locally and syncs on the next entry (the Pull step above
     preserves and re-attempts it). Full flow: `src/skills/planner/capture.md` →
     *Sync each local complete to the shared plan*.
   - **Edit task content** (title/description/produces/consumes): `update_project_plan_task`.
   - **Add a task later:** `create_project_plan_task` (or
     `create_role_assigned_project_plan_task` for a role-owned task).
   - **Remove a task:** its delete tool.

   Guard each per-task call with **that task's own etag** (from the hydrated cache
   or a fresh `get_project_plan`), never the plan's activation etag — that mismatch
   is a 412. On any failure, walk the sign-in ladder at the top of this file; a
   change that can't be pushed stays in the local cache and re-syncs on the next
   successful entry.
3. **Re-hydrate before you show the plan back or end the turn** — `get_project_plan`
   + `list_project_plan_tasks` → `import-remote-plan` — so the local view and the
   Markdown summary match the server's authoritative response (ids, etags, any
   server-side effect). A batch of edits may share **one** re-hydrate at the end,
   but never re-render the plan for the maker, or leave the turn, with the local
   cache and the service out of step — that stale `.md`/`.json` is exactly the
   symptom this prevents.

## Flow 2 — "what am I assigned?" is answered by the service

The service stores the role→person mapping and scopes tasks to the caller
itself. So for "what are my tasks?", make **one** call —
**`list_project_plan_tasks_for_caller`** with just `projectId` and `planId` — and
present exactly what it returns. The caller's identity comes from the signed-in
token, so:

- **Pass no identity, and don't go looking for one.** Never pass, resolve, or
  guess the caller's object id (`subjectId`); never call
  `list_plan_role_assignments` to find yourself; never list the plan's
  assignments to hunt for your own id; never read the project's owner id as if it
  were the caller. The tool already knows who you are.
- **Don't re-derive role gating locally.** What comes back already includes both
  the tasks assigned directly to the caller *and* the tasks assigned to every role
  they hold — the service expands the caller's roles server-side (attesting a
  person into a role is what makes that role's tasks appear). The roles the
  caller holds are evident from the tasks it returns, so state them in
  plain language ("you hold the Power Platform admin role") — **never ask "which
  role(s) do you hold?"**.
- **Call out a first-run setup plainly.** If what comes back includes the caller's
  **setup task** (the one that stands up the environment) still open and no
  environment is on the plan yet, that is their first step — they can stand up the
  environment **either manually in Copilot Studio or by running `/setup`**, and
  **`/setup` is the recommended, guided path**, so point them there **now** (their
  first-run experience).
  `task-brief --task <setupTaskId>` flags this as the first-run setup. When they
  return having run it, capture what
  it produced (`src/skills/planner/capture.md`); and if the ESS agent install was
  blocked so `/setup` couldn't finish, still persist the environment they created
  (same file → *When `/setup` is blocked before it records the environment*) so
  the plan carries it for everyone, while the setup task stays open.
- **On failure, walk the sign-in ladder at the top of this file** and nothing
  else: a 401 → one MCP restart + one retry → then local; any other failure, or
  an unreachable service → local. A rejected call is **never** a cue to start
  asking the person for their roles, guessing ids, or listing assignments. Fall
  back to the local `mine` command (`src/skills/planner/mytasks.md`) only, and
  only when the service is genuinely unreachable.
