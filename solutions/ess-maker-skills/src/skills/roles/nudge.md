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

1. See which roles the plan actually pools work to — its tasks assigned to a role
   (`assignedToType: "Role"`) with nobody named on them. Split them against
   `list_attestable_roles`:
   - **Attestable roles** (e.g. `ServiceNowAdmin`, `WorkdayAdmin`) become visible
     through **attestation** — handle them in steps 2–3.
   - **Non-attestable roles** can't be attested, so attestation will never surface
     their tasks. They become visible only when the task is handed to a **named
     person** — handle them in step 4.
2. Check who's already attested with `list_plan_role_assignments` — only nudge for
   attestable roles with **no active** holder.
3. Nudge in plain language, naming the role and the work waiting on it, and offer
   to do it right there:

   > "This plan has ServiceNow admin work that nobody can see yet. Who should be
   > the ServiceNow admin? I can assign them now."

   If the maker names someone, run the assignment flow
   (`src/skills/roles/resolve-person.md` → `src/skills/roles/attest.md`). If they'd
   rather leave it, that's fine — the task stays pooled and they can assign it
   later.
4. **Non-attestable pooled work still needs a face.** For tasks pooled to a role
   that isn't attestable, there is no attestation that can surface them — they
   stall silently until someone is named. Nudge the maker to hand each one to a
   specific person (`src/skills/planner/assign.md`), naming the work that's
   waiting:

   > "Some of this plan's work isn't tied to an attestable role, so no one can see
   > it until it's handed to a person. Want me to assign it to someone now?"

   Same rule as attestation — offer, don't force; if they leave it, say plainly
   that the work stays hidden until it's assigned.

## Boundaries

- Nudge **assignment**, don't force it — a maker may deliberately leave a pool
  open for now.
- This is about *who holds a role*. It is never the "what are my tasks?" view.
- **Attestable** roles are surfaced by attestation (`src/skills/roles/attest.md`);
  **non-attestable** pooled work is surfaced only by assigning it to a named
  person (`src/skills/planner/assign.md`). Either way, no pooled work should be
  left with no route to visibility.
