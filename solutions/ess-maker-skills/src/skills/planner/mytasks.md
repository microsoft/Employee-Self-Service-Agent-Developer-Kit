# Planner — Flow 2: "What am I assigned?"

> **Planner session entry:** Follow `src/skills/planner/SKILL.md` -> **Intent gate**,
> then **Gate** for the workspace bootstrap on first Planner use. Reuse its successful result
> in the same chat and workspace before continuing this flow.
> Apply its **Communication rules** to every reply and next-step handoff.

When a person asks what work is waiting on them, show their Tasks **grouped by
each role they hold** — which naturally covers a person with more than one role.

> **This is the local, service-unreachable fallback — not the primary path.**
> When the shared planner is reachable, "what are my tasks?" is answered by a
> single `list_project_plan_tasks_for_caller` call that scopes to the caller by
> their signed-in identity and returns their direct *and* role-assigned tasks
> (`src/skills/planner/sync.md`, Flow 2). On that path you **never** resolve a
> `subjectId`, list role assignments, or ask the person which roles they hold —
> the service already knows who they are and expands their roles for you. Drop to
> the steps below **only** when the service is genuinely unreachable and you must
> read the local cache instead.

## Steps

0. **Reconcile a finished first-run setup — once.** Before listing anyone's
   tasks, fold in a setup that already ran as a first-run experience: if
   `python scripts/planner/cli.py setup-status` reports `setupTaskOpen` **true**
   and `.local/config.json` shows setup complete, confirm the detected
   environment and run `capture-setup --complete` so the admin's setup task (and
   anything else that run produced) shows Complete before you show the list
   (`src/skills/planner/capture.md` → *Reconcile a first-run setup that already
   ran*). If `setupTaskOpen` is **false**, there's nothing to reconcile —
   continue.
1. **Find the person's roles — offline, so best-effort.** You're here only
   because the service (which would scope to the caller and expand their roles
   for you) is unreachable, so the attested role→person mapping can't be read
   right now. In this order:
   - Prefer what's already in hand — if the caller's identity and the roles they
     hold are known from this session or the local plan, use those.
   - Otherwise resolve the caller's identity (e.g. via Work IQ `/me`) and, **only
     as a last resort**, ask them to confirm which of the plan's roles are theirs.
   Never block on it: if roles stay unknown, show the tasks assigned to them
   directly and note that the role-assigned view needs the shared planner.
2. **Show their Tasks, grouped by role:**

   ```
   python scripts/planner/cli.py mine --person <oid> --roles <role,role,...>
   ```

   This lists, under each role:
   - Tasks **assigned to them** directly ("assigned to you"), and
   - Open tasks for a role they hold ("open to your role"), which they can
     pick up.

   Render their tasks as a **Step / Task / State** table (per role/group), using
   the State cell to carry readiness — one icon per state: **✅ Complete**,
   **🔄 In progress**, **🔒 Not started** for a task still waiting on an upstream
   artifact it consumes, and **⬜ Not started** for one that's ready to pick up
   now. The `mine` output (and its `--json` `waitingOn` list per task) is what
   tells you which tasks are still locked: a non-empty `waitingOn` → 🔒. Also say
   it in plain language — e.g. "you can start this now" vs. "this waits on *Build
   topic* to finish first" — so the person knows what to do next rather than
   picking up a task they can't complete. Refer to the upstream work by its
   **title**, never an internal task id.

3. **Claiming a role Task.** If they take a role Task, record them as the
   owner (the role is retained):

   ```
   python scripts/planner/cli.py claim --task <T#> --person <oid>
   ```

4. From there, they do the Task (as its description says) and you capture its
   output (Phase 6, `src/skills/planner/capture.md`).

## Before they start — connect their kit to the plan's environment

A task after setup runs against the environment the Power Platform admin
established (they run `/setup`, **decide or create** the environment, and the
planner pins its id as `primaryEnvironment`). Each *other* persona still has to
connect their own kit to that same environment first. So when someone picks up a
task, run `task-brief` and honour its nudge:

```
python scripts/planner/cli.py task-brief --task <T#>
```

- **The brief has `kitSetup` because this task needs the pinned environment** →
  `task-brief` prints "First connect your
  kit: run /setup and choose environment `<envId>`". Nudge them to `/setup` into
  **that** environment (don't let them pick or create a different one), then they
  do their task. The CLI checks `.local/config.json` on every brief and omits
  this nudge when the workspace is already set up for that environment and
  recorded agent. Do not add `/setup` back merely because the task consumes an
  environment; the admin may have just finished it.
- **This person's own ready task IS the setup task** (it produces the environment
  and none is pinned yet) → `task-brief` prints **"First-run setup…"**. This is
  their first-run experience. Spell out that they can stand up the environment
  **either manually in Copilot Studio or by running `/setup`** — and **recommend
  `/setup`** as the easier, guided path. When they come back having run it,
  capture what it produced (Phase 6);
  and if the ESS agent install was blocked so `/setup` couldn't finish, still
  persist the environment they created (`src/skills/planner/capture.md` → *When
  `/setup` is blocked before it records the environment*), keeping the setup task
  open.
- **This task needs an environment that isn't pinned yet** (and this isn't their
  setup task) → the admin's `/setup` task is the prerequisite. Don't nudge this
  person to setup — name the missing input and who owns it. Tasks that do not
  consume an environment, such as firewall preparation, can proceed when their
  own prerequisites are met; do not invent an environment dependency for them.

Present the result in plain language — role headings with their tasks beneath —
not as raw output.

## Brief the task in detail — enrich from Learn

When an assignee engages a task — "what do I do?", or they claim it — do **not**
just echo the one-line description. Give a **detailed, actionable how-to**, the
same depth `/connect` or `/setup` gives. **Mantra: enrich from Learn.** Start from
the structured brief, then enrich the "how":

```
python scripts/planner/cli.py task-brief --task <T#>
```

`task-brief` gives the role, the values the task **consumes** (resolved off the
plan — e.g. the environment id to use), the outputs to **capture** when done, and
the `/setup`-into-the-pinned-environment nudge. On top of that, render the "how"
by the task's kind:

**Check readiness before handing off.** A non-empty `blockedBy` means assignment
is allowed but execution must wait. Name the missing input or pending decision,
the role/task that supplies it, and any unrelated ready work the caller can do.
If the user says "start setup" in natural language, enter the setup skill now;
do not ask them to type `/setup` again. Keep the original task and return to it
after this person's workspace is bound.

**Recognize foundation work even without a command in the description.**
Environment provisioning/selection and ESS installation belong to `/setup`
(`src/skills/foundation-setup/SKILL.md`). Use the task's purpose and its
`primaryEnvironment`, `provisionedEnvironment`, or `essAgent` outputs to identify
that workflow. Continue `/setup` when foundation work is already under way,
reusing the plan's existing environment rather than provisioning another one.
In a status response, recommend this handoff without entering the skill; run it
only when the person asks to start or continue.

1. **The task is done by running a kit skill** (from its description or the
   foundation outputs above, e.g. `/setup`, `/connect`, `/create`, `/evaluate`):
   **hand off to that skill** — it owns the
   detailed, current, per-tenant steps (that's exactly why `/connect` and `/setup`
   are rich). Read that skill's `SKILL.md` and follow it; don't re-summarise its
   steps from memory. The skill *is* the how-to. (E.g. "create a topic" → `/create`.)
   When the skill finishes, you (the planner) capture its outputs (`capture.md`) —
   and one run can close **more than one** task: a single `/setup` completes both
   the environment task and the base-agent task when the plan splits them.
   If the skill's handoff already captured this run, do not capture it again.
   Follow `status.md` → **Refresh after progress** for the same person's next
   action; never blindly advance to another role's task.

2. **The task is a portal / manual step** with no kit skill (register an Entra app,
   publish the agent): **fetch the how-to from Microsoft Learn at render time**
   and render a **task walkthrough**:
   - **Role** — taken *verbatim* from the step's Learn page (never relabelled or
     invented; if Learn lists alternatives, name them as Learn does).
   - **What it accomplishes** — a line or two of context.
   - **Steps** — numbered; each step ends with an inline `learn.microsoft.com` link
     to the exact page/section it came from.
   - **Help & resources** — a short list of the relevant Learn links.

   Fetch from the task's grounding Learn anchor kept in the research context
   (§7.6, `prerequisites[].sourceUrl`) — **never** rely only on the terse stored
   description, and **never** fabricate a step, role, or link. The description is
   the scannable summary; the Learn fetch (or the kit skill) is the detailed how.

Always enrich **on start**, freshly from Learn, so the steps and links are current
rather than baked into (and drifting from) the stored plan.
