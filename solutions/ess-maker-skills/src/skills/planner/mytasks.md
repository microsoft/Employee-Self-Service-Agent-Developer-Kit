# Planner — Flow 2: "What am I assigned?"

When a person asks what work is waiting on them, show their Tasks **grouped by
each role they hold** — which naturally covers a person with more than one role.

## Steps

1. **Find the person's roles.** The roles source is a separate, unbuilt system,
   so this is best-effort:
   - If a roles source is wired, look up the roles this person holds.
   - If not, resolve the caller's identity (e.g. via Work IQ `/me`) and/or ask
     them to confirm which of the plan's roles are theirs.
2. **Show their Tasks, grouped by role:**

   ```
   python scripts/planner/cli.py mine --person <oid> --roles <role,role,...>
   ```

   This lists, under each role:
   - Tasks **assigned to them** directly ("assigned to you"), and
   - Open **pools** for a role they hold ("open to your role"), which they can
     pick up.

   Each task line also carries a **dependency marker** when it isn't ready yet:
   `[blocked by <T#, ...>]` names the upstream task(s) that must still produce an
   artifact this task consumes (or `[blocked by needs <key>]` for an input
   nothing in the plan produces). No marker == ready to start on the
   produces/consumes model. Surface it in plain language — e.g. "you can start
   this now" vs. "this waits on T2 (Build topic) to finish first" — so the person
   knows what to do next rather than picking up a task they can't complete. The
   `--json` form exposes the same signal as a `waitingOn` list per task.

3. **Claiming a pooled Task.** If they take a pooled Task, record them as the
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
