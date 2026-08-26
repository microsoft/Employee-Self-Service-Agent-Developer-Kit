# Roles — attest a person into a role

You have the plan (`projectId`, `planId` — the gate in `SKILL.md`), the person's
directory object id (`oid` — `resolve-person.md`), and the role the maker named.
Now record it.

## 1. Validate the role

Call `list_attestable_roles`. If the role the maker asked for isn't in that set,
stop and explain only those roles can be attested (today `WorkdayAdmin`,
`ServiceNowAdmin`, `ServiceNowKnowledgeManager`) — offer the closest match if the
maker used a loose name ("the ServiceNow admin" → `ServiceNowAdmin`). Confirm the
exact role with the maker before you write anything.

## 2. Attest

Call `attest_plan_role` with:

- `planId` — the plan in context,
- `subjectId` — the person's `oid`,
- `role` — the attestable role id.

Omit `etag` for a first attestation; the provider is set for you.

If the tool reports it needs sign-in, ask the maker to authenticate once and
retry the same call (`src/skills/planner/sync.md`). If it reports the person is
already attested for that role, treat it as success — the outcome the maker
wanted is already true.

## 3. Confirm — in terms of what changed for the person

State the *effect*, not the mechanics: the person can now see and pick up that
role's work on the plan.

> "Done — Priya now holds the ServiceNow admin role on this plan. The ServiceNow
> admin tasks will show up when she asks what she's assigned, and she can pick
> them up."

Do **not** say "attested", "subjectId", "provider", or name any service.

## Re-attest / converge an existing assignment

To change an assignment that already exists (rare), read it first with
`list_plan_role_assignments` (or `get_role_assignment`) to get its **strong**
ETag, then pass that ETag to `attest_plan_role`. Never pass the plan's weak ETag.

## After assigning several roles

When the maker has staffed the plan's roles, offer to show who holds what
(`src/skills/roles/list.md`) so they can confirm nothing pooled is still
unassigned.
