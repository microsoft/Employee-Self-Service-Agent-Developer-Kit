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
3. **Record the choice.** For a specific person, `--person` takes their directory
   **object id**, not a name — so once the sponsor names someone, turn that name
   into their `oid` with the shared person-resolution step
   (`src/skills/roles/resolve-person.md`; it handles sign-in, disambiguation, and
   the WorkIQ fallback, then hands back the `oid`). Skip that when leaving the
   task open to the role.

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
same result and the same capture (Phase 6).

When every Task is assigned or pooled, show the summary. (The eval **preview** was
already rendered eagerly during the interview — Phase 5, `src/skills/planner/evaluate.md`;
re-render it here if the scope changed. It is render-only and generates nothing.)

**Then persist the plan — automatically, the instant assignment is done.**
Finishing assignment is the trigger to publish; do not wait for the sponsor to
ask. The plan they just approved lives only in the local cache until you push it,
so **immediately** follow `src/skills/planner/sync.md` → *Push* now (name the
configuring agent → `export-remote-plan` → `create_project_plan` → re-hydrate).
That publishes the plan as **Draft** and shows it back for review; the plan
**activates on the first role/task assignment, not on push** — you call activate
explicitly then, because the backend never auto-activates (see `sync.md` steps
5–6). Never leave a freshly built plan local. If the service is unreachable,
fall back to the local cache and carry on (never mention any of this to the
sponsor), and push on a later turn once it's reachable — a summary that still
shows the plan as `(local, not synced)` has **not** been persisted.

The Plan is ready to run: each assignee runs the Task's skill (or does the
manual/portal step), and you capture what it produced in Phase 6.

## Nudge — put real people on the attestable roles

Some Tasks are pooled to an **attestable role** (e.g. `ServiceNowAdmin`,
`WorkdayAdmin`, `EntraPowerPlatformAdministrator`) rather than a named person. Pooled
role work is **invisible** until a real person is recorded as holding that role
for the plan — so once the plan is published (`src/skills/planner/sync.md`), nudge
the sponsor to assign those roles to real people. That is what makes the work show
up in each person's "what am I assigned?" view. Hand off to the roles attestation
flow to do it — it resolves the person and records the assignment
(`src/skills/roles/nudge.md`, then `src/skills/roles/resolve-person.md` →
`src/skills/roles/attest.md`). This is **assignment only**; it never answers "what
are my tasks?".

## Future — resolve the person from an external roles API

For an **attestable** role (e.g. `ServiceNowAdmin`, `WorkdayAdmin`,
`EntraPowerPlatformAdministrator`) the person side is already wired: the roles skill
resolves a name to a directory object id and records the holder against the plan
(`src/skills/roles/SKILL.md`). The seam below still describes the **general** roles
source for every *other* grounded role, which remains best-effort until built.

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
