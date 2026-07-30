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

4. From there, they run the Task's action and you capture its output (Phase 5,
   `src/skills/planner/capture.md`).

Present the result in plain language — role headings with their tasks beneath —
not as raw output.
