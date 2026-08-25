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

> **MCP store:** when running against WeveNova (`--store mcp`), also record the
> named person against the role so Flow 2 (their "my tasks" view) lights up for
> the pooled role tasks. That's the **`/roles` skill** (`src/skills/roles/SKILL.md`):
> it resolves the person (via the WeveNova people directory) and attests them plan-scoped. Hand off to
> `/roles` — the planner itself no longer attests.

## The soft assumption

For the MVP, the sponsor often also holds Power Platform admin access, so they
may take the setup Task themselves. That's a convenience, not a rule — assign to
whoever actually holds the role; a different admin running the Task produces the
same result and the same capture (Phase 6).

When every Task is assigned or pooled, show the summary. (The eval **preview** was
already rendered eagerly during the interview — Phase 5, `src/skills/planner/evaluate.md`;
re-render it here if the scope changed. It is render-only and generates nothing.)
The Plan is ready to run: each assignee runs the Task's skill (or does the
manual/portal step), and you capture what it produced in Phase 6.

## Future — resolve the person from an external roles API

Today a Task carries a Learn-grounded **role** (pooled), and the sponsor picks the
person by hand. The next step wires a real **roles source** behind the same seam
(`scripts/planner/roles.py` → `RoleSource`), so the planner can:

1. **List holders of a role** from an external API — `list_holders(role)` returns
   the people who hold `{role}`, and the sponsor picks from that list instead of
   typing a name (Flow 1).
2. **Assign a user together with the role** — the choice is stored as
   `assign --task <T#> --role <role> --person <oid>` (person owns it, role
   retained), so the Task still groups under the role in Flow 2.
3. **Resolve "what am I assigned?"** — `roles_of(person)` maps the caller to their
   role(s) so Flow 2 needs no manual role entry.

The Plan schema and skills already support user+role assignment; only the backing
`RoleSource` is unbuilt. The role stays **Learn-grounded** regardless of who fills
it — the external API resolves *people*, never the *role* a Task needs.
