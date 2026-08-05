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
