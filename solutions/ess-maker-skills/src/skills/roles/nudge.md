# Roles — nudge role assignment on an active plan

When a plan is Active, some of its tasks are assigned to **roles**
(e.g. `ServiceNowAdmin`, `WorkdayAdmin`, `EntraPowerPlatformAdministrator`) rather
than to named people. Until a real person is attested into each of those roles,
that work
is **invisible** — nobody's "what am I assigned?" view shows it, so it silently
stalls. This nudge makes the maker's ownership action clear without starting an
assignment interview on their behalf. Follow
`src/reference/ui-formatting-guidelines.md` for the handoff.

## When to nudge

After confirmed activation (`src/skills/planner/sync.md`), or when an Active plan
is resumed with relevant unfinished work and a vacant role. A local or shared
draft follows the requester-specific lifecycle guidance in `planner/status.md`;
do not skip review, sharing, or explicit activation to ask for owners.

## How to nudge

1. See which roles the plan actually assigns unfinished work to — its tasks assigned to a role
   (`assignedToType: "Role"`) with nobody named on them. Split them against
   `list_attestable_roles`:
   - **Attestable roles** (e.g. `ServiceNowAdmin`, `WorkdayAdmin`) become visible
     through **attestation** — handle them in steps 2–3.
   - **Non-attestable roles** can't be attested, so attestation will never surface
     their tasks. They become visible only when the task is handed to a **named
     person** — handle them in step 4.
2. Check who's already attested with `list_plan_role_assignments` — only nudge for
   attestable roles with **no active** holder.
    If `owner.<role-id>` is already recorded as a pending decision, include it in
    the status summary but do not repeat the assignment question. Nudge again only
    when the maker asks or that vacancy now blocks the work they want to start.
3. Name the role and work waiting on it with a prominent action, not a blocking question:

   > ## Your next step
   >
   > **Choose an owner for ServiceNow administration.**
   >
   > The ServiceNow setup work is waiting for an owner.
   >
   > **Say:** "Assign the ServiceNow admin role."

   If the maker asks to assign or names someone, run the assignment flow
   (`src/skills/roles/resolve-person.md` → `src/skills/roles/attest.md`). If they'd
   rather leave it, that's fine — the task stays open to the role and they can assign it
   later. Persist that choice as `pendingDecision` per `planner/assign.md`, with
   the affected work and how to resolve it. Other roles' ready work can continue.
4. **Non-attestable role work still needs a face.** For tasks assigned to a role
   that isn't attestable, there is no attestation that can surface them — they
   stall silently until someone is named. Nudge the maker to hand each one to a
   specific person (`src/skills/planner/assign.md`), naming the work that's
   waiting:

   Use the same handoff layout with the actual task title and a prompt to assign
   its owner. Do not turn the suggestion into a question or start assignment
   without the maker's request.

   Same rule as attestation — offer, don't force; if they leave it, say plainly
   that the work stays hidden until it's assigned.

## Boundaries

- Nudge **assignment**, don't force it — a maker may deliberately leave a role
  open for now.
- This is about *who holds a role*. It is never the "what are my tasks?" view.
- **Attestable** roles are surfaced by attestation (`src/skills/roles/attest.md`);
  **non-attestable** role work is surfaced only by assigning it to a named
  person (`src/skills/planner/assign.md`). Either way, no role work should be
  left with no route to visibility.
