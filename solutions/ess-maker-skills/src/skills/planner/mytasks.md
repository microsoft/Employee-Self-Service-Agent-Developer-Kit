# Planner — Flow 2: "What am I assigned?"

When a person asks what work is waiting on them, show the Tasks assigned to them —
their direct assignments **plus** the pooled Tasks for the roles they hold. Against
WeveNova you never resolve those roles yourself: pass the person's own id and the
server expands their attested roles. Grouping the result by role is a *display*
choice, not a reason to query role-by-role.

**The answer is *exactly* what the caller-scoped WeveNova call returns — nothing
more.** "What am I assigned?" is a **filtered, self-scoped** query, not a plan tour:

- The task list you show is **only** the output of `caller-tasks` (step 1). Never
  substitute, pad, or supplement it with the wider plan.
- **Never enumerate the whole plan's tasks**, and never show a task that is waiting
  on a role the caller does **not** hold. "Here's everything in the plan and who
  it's waiting on" is the **wrong** answer to "what am I assigned?".
- **Never filter the plan client-side** to decide what's theirs — WeveNova scopes
  it server-side from the caller's id. Pulling the plan and picking out rows
  yourself is exactly the bug this flow exists to prevent.
- If nothing is scoped to them, say so plainly and **stop there** (then offer the
  next actions in step 1) — do **not** fall back to dumping the plan.

## Steps

**0. Confirm a plan exists on WeveNova — for context only, not to list tasks.**
Pull the live plan first so you can tell "no plan authored yet" apart from "a plan
exists but nothing is scoped to you" — **even if you routed straight here** and
think no backend is configured:

```
python scripts/planner/cli.py --store mcp pull
```

- Returns a plan → a plan exists; go to step 1 for the **scoped** answer. The
  pulled plan is **background context only** — it is **not** the task list, and its
  tasks must **never** be read out as "your tasks" (that dump is the exact mistake
  this flow exists to prevent).
- Returns an **empty plan / "no plans yet"** → there genuinely are no assignments
  because no plan has been authored yet; say so and offer to **build** one (hand
  back to the planner's plan-creation flow). Do **not** claim "no plan exists"
  without having pulled.
- Errors that WeveNova is unreachable/unconfigured → fall back to the **offline**
  path in step 1 (`mine --person … --roles …`, where you supply the roles
  manually because there's no server to resolve them).

**Never answer "nothing is assigned / no plan exists" until this pull has run** —
and never answer with the *whole* plan once it has.

1. **Show the tasks waiting on them — let WeveNova resolve the roles.** Against
   WeveNova (`--store mcp`, the default backend) this is owned by the **`/roles`
   skill**; hand off to its `caller-tasks`:

   ```
   python scripts/planner/roles_cli.py caller-tasks
   ```

   `caller-tasks` resolves the caller **automatically** from the kit's `.env`
   (`userName` + `aadId`) — so **don't ask the person for their AAD id** (or
   look up a name). `--caller` / `PLANNER_MCP_CALLER_ID` are optional overrides.
   **Don't look up or infer their roles either** — there is no client-side role
   API, and you never enumerate roles to build the query. Passing the caller id
   *is* the whole mechanism: WeveNova reads it as a self-scope marker, expands the
   roles that caller is attested to **server-side**, and returns their directly-
   assigned tasks **plus** the pooled tasks for those roles. (Self-only: it is
   always *your own* authenticated identity — a different, hand-supplied OID is
   read as a literal filter and returns none of that person's role-pooled work.
   See `src/skills/roles/SKILL.md`.)

   **`caller-tasks` output *is* the answer — present it and stop:**
   - **It returned tasks** → show **those**, grouped by role for readability. Don't
     add sibling tasks from the plan "for context."
   - **It returned "No tasks are waiting on you right now"** (the plan exists — step
     0 pulled it — but nothing is scoped to this caller) → say exactly that: nothing
     is assigned to them yet. **Do not** then list the plan's other tasks or who
     they're waiting on. Instead offer the useful next moves: **assign them to a
     role** so the matching tasks become theirs (hand to `/roles` attest), or
     **walk them through a specific task** if they name one. Let *them* ask to see
     the wider plan — never volunteer it as their task list.

   > **Offline fallback only** — when step 0 reported WeveNova
   > unreachable/unconfigured (no live plan), the local equivalent is:
   > ```
   > python scripts/planner/cli.py mine --person <oid> --roles <role,…>
   > ```
   > Here — and *only* here — you supply the roles manually, because there's no
   > server to resolve them: ask the person which of the plan's roles are theirs.
   > Never do this against a live WeveNova plan — let the server expand roles.

2. **Claiming a pooled Task.** If they take a pooled Task, record them as the
   owner (the role is retained):

   ```
   python scripts/planner/cli.py claim --task <T#> --person <oid>
   ```

3. From there, they do the Task (as its description says) and you capture its
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

- **Plan has an environment pinned** → `task-brief` prints "First connect your
  kit: run /setup and choose environment `<envId>`". Nudge them to `/setup` into
  **that** environment (don't let them pick or create a different one), then they
  do their task.
- **No environment pinned yet** → the admin's `/setup` task is the prerequisite;
  the environment hasn't been decided. Don't nudge this person to setup — tell
  them their task is blocked until setup runs, and who owns it.

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

1. **The task is done by running a kit skill** (its description says run `/setup`,
   `/connect`, `/create`, `/evaluate`): **hand off to that skill** — it owns the
   detailed, current, per-tenant steps (that's exactly why `/connect` and `/setup`
   are rich). Read that skill's `SKILL.md` and follow it; don't re-summarise its
   steps from memory. The skill *is* the how-to. (E.g. "create a topic" → `/create`.)

2. **The task is a portal / manual step** with no kit skill (register an Entra app,
   provision the Power Platform environment, publish the agent): **fetch the how-to
   from Microsoft Learn at render time** and render a **task walkthrough**:
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
