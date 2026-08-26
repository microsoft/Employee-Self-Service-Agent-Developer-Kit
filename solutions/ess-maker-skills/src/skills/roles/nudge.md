# Roles — nudge role assignment when a plan is created

When a plan is published, some of its tasks are pooled to **roles**
(`ServiceNowAdmin`, `WorkdayAdmin`, `ServiceNowKnowledgeManager`) rather than to
named people. Until a real person is attested into each of those roles, that work
is **invisible** — nobody's "what am I assigned?" view shows it, so it silently
stalls. This nudge closes that gap at the moment the plan is created.

## When to nudge

Right after a plan is published/activated (the planner's publish step,
`src/skills/planner/sync.md`), or whenever a plan is resumed and still has pooled
attestable-role tasks with nobody attested for them.

## How to nudge

1. See which attestable roles the plan actually pools work to (its tasks assigned
   to a role; cross-check the role is attestable with `list_attestable_roles`).
2. Check who's already attested with `list_plan_role_assignments` — only nudge for
   roles with **no active** holder.
3. Nudge in plain language, naming the role and the work waiting on it, and offer
   to do it right there:

   > "This plan has ServiceNow admin work that nobody can see yet. Who should be
   > the ServiceNow admin? I can assign them now."

   If the maker names someone, run the assignment flow
   (`src/skills/roles/resolve-person.md` → `src/skills/roles/attest.md`). If they'd
   rather leave it, that's fine — the task stays pooled and they can assign it
   later.

## Boundaries

- Nudge **assignment**, don't force it — a maker may deliberately leave a pool
  open for now.
- This is about *who holds a role*. It is never the "what are my tasks?" view.
- Only nudge for **attestable** roles — other grounded roles on the plan aren't
  attested through this flow.
