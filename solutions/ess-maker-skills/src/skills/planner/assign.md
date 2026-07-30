# Planner — Phase 4: Assign each Task (Flow 1)

The role for each Task is already grounded from the Learn docs (Phase 3). The
sponsor's only job here is to pick **who** does it. For each Task:

1. **State the role** (don't ask for it): "This task is a `{role}` task."
2. **List the people who hold that role.** The roles source is a separate,
   currently-unbuilt system, so this is best-effort:
   - If a roles source is wired, show its holders of `{role}` and let the
     sponsor pick one.
   - If not, ask the sponsor for the person's name/identifier, or offer to
     **leave it open to the role** (a pool any holder can later claim).
3. **Record the choice:**

   ```
   # assign a specific person, keeping the grounded role
   python scripts/planner/cli.py assign --task <T#> --role <role> --person <oid>

   # or leave it open to the role (pooled)
   python scripts/planner/cli.py assign --task <T#> --role <role>
   ```

The person is stored *acting as* the role — both facts are kept, so the Task
still shows up under that role in Flow 2, and provenance survives.

## The soft assumption

For the MVP, the sponsor often also holds Power Platform admin access, so they
may take the setup Task themselves. That's a convenience, not a rule — assign to
whoever actually holds the role; a different admin running the Task produces the
same result and the same capture (Phase 5).

When every Task is assigned or pooled, show the summary. The Plan is ready to
run: each assignee runs the Task's skill (or does the manual/portal step), and
you capture what it produced in Phase 5.
