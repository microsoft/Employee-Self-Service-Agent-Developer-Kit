# Planner Skill — sync the Plan with the shared planner

The local Plan (`workspace/plan/plan.json`) is a **cache**. The source of truth
is the **shared planner** — a service every maker on the agent shares, reached
through the planner tools available to you. This file is the concrete flow for
keeping the two in step: pull an existing plan on entry, and push a newly
authored plan as one object.

## Entry preflight

Apply `src/skills/planner/SKILL.md` -> **Intent gate** first. "Hi" or passive
`plan.json` context alone is not permission; stop without bootstrap or shared tools.
Complete the **workspace bootstrap before any shared tool call**. Follow
`src/skills/planner/SKILL.md` -> **Gate** on first Planner use, including a direct
pull/share/activate/sync request in a fresh chat. Reuse successful results in the
same chat and workspace for later turns or phases, following the gate's
recheck/failure rules. A saved plan, absent setup config, or already-visible
Planner tools do not replace this chat's bootstrap.
Apply the same skill's **Communication rules** to every reply and next-step
handoff, including saves, activation, partial progress, and recovery.

If configuration creation/validation fails, keep the local draft unchanged,
report that error, and stop shared calls. Configuration, host discovery/trust,
and a service response are separate evidence: never infer the workspace file
exists just because a tool is exposed, or label an unavailable tool as a service
failure. Bootstrap does not grant shared access or authorize plan mutations.

**Rules that never bend:**

- **Make persistence truthful.** Say **Saved in this workspace**, **Shared draft**,
  **Active**, **Saved locally - awaiting shared confirmation**, or **Confirmed on
  the shared plan**, as appropriate. Avoid unnecessary backend names, but explain
  `ess-planner` when the host requests approval. Never hide a failure or equate a
  local file write with a successful shared update.
- **Plan mutations stay local in the CLI; shared writes use tools.** The CLI
  (`scripts/planner/cli.py`) reads/writes the local plan. Its `research`
  command can fetch public Learn documentation, not the shared planner.
  The planner tools talk to the service and never touch local files.
  You are the bridge: you carry JSON between
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

**Sign-in is the tool's job — never ask the sponsor whether to sign in.** A new
Planner client acquires its configured credentials, opening browser sign-in when
needed. The transport does not automatically refresh and replay a rejected HTTP
401. Do not claim a new sign-in or token renewal happened unless it was observed.
Never inspect MCP/auth source or credential stores during the maker flow, and
never add a "how would you like to sign in?" interview. Walk this ladder **in
order** — never cycle back up it:

- **It succeeds** — possibly after a sign-in window appeared when connecting and the
  sponsor completed it. Expected; just carry on. Say nothing about sign-in.
- **PlanPayloadTooLarge / OpenTypeTooLarge, or a confirmed storage-size diagnosis**
  — stop shared writes, even if the outer error says `InternalServerError`.
  This is not transient. Do not retry unchanged, rotate idempotency keys, restart
  MCP, or run `/setup` to work around it. Follow **Shared-record size budget**
  below, keeping the complete local draft intact.
- **It returns HTTP 401** — take **one** mechanical recovery, then retry the same call
  **once**: restart the `ess-planner` MCP server — run the editor's *MCP: Restart
  Server* command yourself if that's available to you, otherwise give the sponsor
  the prominent next-step handoff for Command Palette → *MCP: Restart Server* →
  `ess-planner`. The restart reruns credential acquisition; it may reuse cached
  credentials and is not proof of a fresh browser sign-in.
- **It 401s again even after that restart + retry** — stop. Explain briefly —
  *"Your saved local copy is available; shared updates are unavailable right now.
  Pending completions will be retried when access returns."* Continue local drafting.
  Shared access is still unconfirmed; do not loop, change accounts automatically,
  or infer the missing permission from the status code alone.
- **Network error or 5xx** — use the local cache and explicitly say shared status
  could not be refreshed. Preserve pending completions; do not imply other edits
  are queued when no durable queue exists.
- **403/access denied** — explain the missing access and stop shared operations.
  Do not show restricted shared data via a local-cache fallback.
- **400/409/412** — surface the specific validation/lifecycle/conflict problem.
  Re-read and reconcile a conflict with the maker; never auto-activate or replace
  a stored ETag and replay an offline write over someone else's edit.

That single restart is the **only** sign-in recovery you ever take. Missing
configuration or unavailable MCP tools use the separate **Gate** recovery, not
this HTTP-error ladder. Do **not**
clear or inspect token caches, read any MCP/auth source, check the token source, or
reason about the client's internals — that is the spiral to avoid, not a path to a
fix. The whole budget is: one 401 → at most one restart + one retry → then local.
Never open a diagnostic thread, and the sponsor is only ever prompted by the tool's
own sign-in window or that one restart line — never by a "how would you like to
proceed?" question. Planning is never blocked by the service.

## Identify the project (always first)

These shared operations apply only after entry preflight and when the maker has
accepted shared access.
For an explicitly local-only draft or declined trust prompt, keep working locally
and skip this flow until they ask for shared access.

Use the authenticated tenant reported by MCP diagnostics when tracing a failure,
not an assumed tenant from an earlier conversation. If it differs from the maker's
intended tenant, stop writes and confirm the intended tenant/account through the
normal sign-in flow before continuing. Do not change tenant IDs in configuration
to match telemetry or inspect/edit token caches. Correlate the actual tenant,
project, request IDs, and failure time; never include access tokens.

Every plan lives under the ESS project. For an admitted request needing shared
access, get-or-create it. Idempotence makes replay safe; it is not authorization
to start this flow, and the call can create a project when none exists:

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
diagnostics. A corrupt local cache or a pending write belonging to another plan
must stop replacement rather than silently discard local work.
An unshared draft with pending completions or outputs is **not** associated with
an existing shared plan merely because task titles or local IDs match. Import
stops and leaves its JSON and Markdown intact. Reconcile the separate plans
before resuming; never add a first-share association just to bypass this guard.
Malformed/error tool results or missing plan/task identities are rejected before
replacing the cache; they are not an empty shared plan.

**A pull never reverts an unpushed local completion.** If a task was completed
locally but its push to the service hasn't landed yet (flagged `pendingSync` —
see `src/skills/planner/capture.md`), `import-remote-plan` **preserves** it
instead of overwriting it with the service's stale `NotStarted`, and prints
`Preserved unpushed local completion(s): …`. So on entry, after the hydrate, run
`python scripts/planner/cli.py pending-sync`; if it lists any task, **sync each
now** using the operation in that payload (the capture file's *Sync each local
complete* flow) before moving on — then re-hydrate so the server's confirmation
clears the flag only when the expected outputs also match. Partial outputs are
listed separately as `pendingOutputs`, not sent to a completion endpoint.
This is what makes a completion that failed to push last time
reach the shared plan on the next successful entry.

## Shared-record size budget

ESS limits one stored plan record to **25,600 bytes**, including server-added
metadata. Per-field lengths, context count, and the size of the entire HTTP body
are not sufficient checks. Context and acceptance criteria share the plan record;
inline tasks are separate records. Shrinking task descriptions alone does not
fix oversized plan context.

Before a create or metadata update, use a fresh
`python scripts/planner/cli.py export-remote-plan` result. The export and MCP share
an aggregate UTF-8 preflight with conservative metadata headroom. Export can pack
generated workstream labels losslessly into bounded scalar maps; do not hand-edit
those carriers. Existing workstream entries remain readable.

If export fails, there is no sendable body. Preserve the full local draft and
review a concise shared version: state common assumptions once, remove repeated
boilerplate, and shorten redundant descriptions. Preserve scenario scope,
dependencies, ownership, authorization/confirmation rules, and evaluation
expectations. Do not truncate fields, silently discard requirements, or claim a
local attachment is accessible to colleagues. Confirm semantic changes before
sharing. Re-export and proceed only when the check passes.

The preflight is a conservative client budget, not the exact service serializer.
If the backend still reports `OpenTypeTooLarge`, retain the diagnostic and stop
unchanged retries; server-side aggregate validation and a clear error remain
necessary. A generic 500 without size evidence must not be labelled a size error.

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

When the sponsor asks to share the plan you built locally (interview → research →
model), store it in **one** create call rather than task-by-task:

1. **Reuse the scenario-inferred target confirmed with the draft**, or the
   maker's explicit/saved target. Do not reopen an HR/IT selector at sharing.
   `configuringAgentName` is required for this shared create, **not** for local
   drafting. If it is missing, infer it from the already-captured scenarios using
   `interview.md` and confirm it with the draft's scope, without restarting the
   interview. Unknown systems do not prevent that inference. Mixed or unclear
   experience stays pending until resolved; keep the local draft rather than
   inventing a target to satisfy the API. Persist the resolved target if needed:
   `python scripts/planner/cli.py set-agent-name --name <AgentName>`
2. **Build the create body:**
   `python scripts/planner/cli.py export-remote-plan` — this prints the JSON body
   (configuring agent, acceptance criteria, context, and every task inline).
   Require a successful export before calling MCP. It checks the final aggregate
   budget, including generated metadata, and packs workstream labels losslessly
   when needed. Use this freshly exported body verbatim, never an older oversized
   body or raw `plan.json`.
3. **Store it (the plan is created in Draft):** call **`create_project_plan`**
   with the `projectId`, that body, and an **`idempotencyKey`**. Generate the key
   once when the share starts (a fresh UUID) and treat it as belonging to this
   exact request body — reuse the *exact same* key on a safe retry of the unchanged
   store. A changed body requires readback/reconciliation of the failed attempt
   before a new keyed create; never rotate keys merely to bypass an error. Keying
   the create is what makes a retry safe: the service collapses a replay onto the
   same plan instead of creating a duplicate. (An **unkeyed** create is
   deliberately *not* auto-retried, because a blind replay could duplicate the
   plan — if a keyless push fails ambiguously, re-read the project's plans and
   reconcile the result before another create. Adding a key retroactively does
   not deduplicate the original request.) The plan and all its tasks are created
   atomically, in **Draft**. Keep the returned `planId`, `etag`, and the raw
   successful create response for the association in step 4. A Draft plan
   already holds all its tasks with their assignees baked in at creation, but
   those tasks can't be *mutated* (reassigned, state-changed, edited, completed)
   until the plan is **Active** — and **the backend never auto-activates a plan**.
   Activation is therefore an explicit step you take yourself, once the sponsor
   confirms the plan is ready to run (step 6). Do **not** activate here.
4. **Re-hydrate so the cache carries the server ids** (planId, task ids, etag):
   `get_project_plan` + `list_project_plan_tasks`, then hand each result to
   `import-remote-plan --plan-file <get_project_plan result> --tasks-file <list_project_plan_tasks result> --created-plan-file <successful create_project_plan result>`
   (one file per flag — never hand-stitch a combined object or run the results
   through PowerShell JSON cmdlets; the CLI strips the trailing `{"result": …}`
   envelope itself). Use `--created-plan-file` **only** for the successful create
   of this local draft, never for a normal pull/resume or another plan's result.
   Its plan ID and any returned project ID must match the readback. Only this
   explicit association permits unique title matching to carry offline progress
   onto newly assigned task IDs; missing/ambiguous matches stop for reconciliation
   without replacing the draft. Do not fabricate a receipt or use `stamp-remote`
   to bypass that check. The plan is now cached as **Draft** with real ids.
5. **Confirm it's saved to the shared space, then offer to activate.** The plan the
   sponsor already reviewed locally is now stored as a **Draft** with its assignees
   baked in — tell them it's saved to the shared space (plain language, never name
   the backend) and re-surface the downloadable *ESS scenario plan* link if helpful
   (the `summary` command prints the exact `📄 [ESS-scenario-plan.md](…)` line). A
   Draft's tasks are **read-only** until it's Active, so name the next step:
   render the chosen action with the shared next-step heading, bold action, and
   separate prompt, not as an inline sentence. The branches below guide the
   response; they are not a blocking menu.
   - **Activate the plan** — make this the active rollout plan so owners can start
     ready tasks and record progress. This does not run tasks or deploy ESS
     automatically. **Prompt:** "Activate this plan." Go to step 6 only when the
     sponsor asks to activate, not merely because this option was displayed.
     From then on, put people on the
     roles (`src/skills/roles/nudge.md` → `src/skills/roles/attest.md`), hand
     tasks to named owners (`src/skills/planner/assign.md`), and capture outputs —
     all through the task tools against the **Active** plan.
   - **Not yet** — leave it in Draft. Refinement is best done **before** you share:
     once stored, local edits **can't be pushed onto a Draft** — the service has no
     "update a Draft" path (re-running `create_project_plan` makes a *new* plan, and
     a Draft's tasks are read-only), so revisions reach the server only **after
     activation** (step 6). Explain this limitation before sharing. If they need
     changes afterward, preserve the proposed edits as a review copy and explain
     which changes cannot yet reach the shared Draft. Never activate just to
     bypass the restriction or claim a local edit updated the shared Draft.
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
   Pending system/owner decisions do not globally block activation: identify
   the tasks that must wait, while unrelated ready work can proceed.

   **Then refresh the maker's next step.** Use `status.md` → **Refresh after progress**.
   Use its prominent activation handoff with the actual saved state.
   If required roles for unfinished work are still vacant, recommend assigning
   them (`src/skills/roles/nudge.md` → `src/skills/roles/attest.md`). Do not
   recommend activation again or ask them to repeat assignments already recorded.
   Otherwise choose the relevant coordination action or their own eligible task.
   Editing still
   works after activation, but those edits now reach **both** the local plan **and**
   the shared service — route them through the task tools (*Ongoing edits* below),
   not the local cache alone.

If `export-remote-plan` reports a missing configuring agent name, return to the
scenario-inference and draft-review step above, not an up-front experience
question. Keep planning locally if the target is still unresolved.

## Ongoing edits — keep the service authoritative

Once a plan is on the service, route mutations through the tools (not just the
local cache), then re-hydrate so the cache reflects the server's response:

- **Change a task's state:** `set_project_plan_task_state`. Before starting or
  completing work, run `task-brief` and enforce its `blockedBy`/`blockingReason`.
  Assignment can happen in advance; execution cannot skip missing prerequisites.
- **Record what a task produced:** `complete_project_plan_task` (Phase 6 capture).
  This is **coupled to the local complete, not a deferred step**: the moment a
  `capture-setup` / `capture-discover` / `pin-output --complete` / `set-state
  --state Completed` flags a task
  `pendingSync`, push it in the same turn — `pending-sync` prints the exact
  `projectId` / `planId` / `taskId` / `outputs` / `etag`; call the tool, then
  re-hydrate to clear the flag. If the push can't reach the service, the
  completion stays `pendingSync` locally and syncs on the next entry (the Pull
  step above preserves and re-attempts it). Full flow:
  `src/skills/planner/capture.md` → *Sync each local complete to the shared plan*.
- **Edit task content** (title/description/produces/consumes): `update_project_plan_task`.
- **Add a task later:** `create_project_plan_task` (or
  `create_role_assigned_project_plan_task` for a role-owned task).
- **Delete a task:** `delete_project_plan_task`, after confirming affected work.
- **Plan context / acceptance criteria:** `update_project_plan`, using the
  plan's ETag. Preserve other entries and verify the returned plan after the write.

For non-completion edits, compute and confirm the change, call the appropriate
tool with the entity's ETag, then hydrate the local view. A failed ordinary edit
is not automatically queued by the completion queue: retain the proposal and
say it has **not** reached the shared plan. Never overwrite edited review files
before reading and reconciling them.

After a batch of edits, re-pull (`get_project_plan` + `list_project_plan_tasks` →
`import-remote-plan`) so the local view and the Markdown summary match the service.

## Flow 2 — "what am I assigned?" is answered by the service

The service stores the role→person mapping and scopes tasks to the caller
itself. Use this same caller-scoped view for a personal execution next step in a
status or resume response; the project-wide task list is only team context.
Apply the requester and lifecycle policy in `status.md` first: a shared Draft
remains read-only, and returned tasks still need a readiness check with
`task-brief`. Do not call this flow without a shared plan ID. An empty result
means no open tasks were returned, not that the caller has no deployment role.

For "what are my tasks?", make **one** call —
**`list_project_plan_tasks_for_caller`** with just `projectId` and `planId` — and
keep that assignment scope. Refresh it after progress, not from an earlier result.
If the local ledger preserves a completed task as `pendingSync`, label it as
awaiting shared confirmation rather than recommending it again, even if the
service list is stale. The caller's identity comes from the signed-in
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
  **setup task** (the one that stands up the environment) ready to execute and no
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
