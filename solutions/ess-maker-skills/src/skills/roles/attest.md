# Roles — attest a person into a role

You have the plan (`projectId`, `planId` — the gate in `SKILL.md`), the person's
directory object id (`oid` — `resolve-person.md`), and the role the maker named.
Now record it.

## 1. Validate the role

Call `list_attestable_roles` — that live list is the source of truth for what the
plan accepts, and it spans three provider families: the external systems
(`WorkdayAdmin`, `ServiceNowAdmin`, `ServiceNowKnowledgeManager`), Microsoft Entra
directory roles (including `EntraPowerPlatformAdministrator`,
`EntraGlobalAdministrator`, `EntraApplicationAdministrator`), and Power Platform
roles (`PowerPlatformEnvironmentMaker`, `PowerPlatformEnvironmentAdministrator`,
`PowerPlatformSystemAdministrator`). Map a loose name the maker uses to the
matching id ("the ServiceNow admin" → `ServiceNowAdmin`, "Power Platform admin" →
`EntraPowerPlatformAdministrator`). Only if the role genuinely isn't in that list
do you stop and explain it can't be attested. Reuse an explicit or already-confirmed
role choice; ask only when the mapping is ambiguous. Confirm the person/role
pairing once before writing, using the original explicit request or the person's
selection from the directory results rather than another confirmation turn.

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

Only confirm an assignment after a successful shared result. A recognized role,
a resolved name, or an unanswered confirmation is not a saved assignment.
If the person or their approval is still missing, keep the assignment unresolved
and return the required question to the main chat via `resolve-person.md`.

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

## Several assignments in one go

A maker often names more than one pairing in a single breath — "assign Erica as
Power Platform admin **and** James as Workday admin", or "make Priya and Sam the
ServiceNow admins". **Handle every pair — don't drop any, and don't make the maker
repeat themselves one at a time.**

1. **Parse the utterance into `(person, role)` pairs.** Split on "and" / commas and
   map each person to the role named for them. If one pairing is genuinely ambiguous
   (a name with no role, or a role with no person), ask about **that pair only** —
   don't stall the others.
2. **Resolve and attest each pair in turn** — for each pair, run person resolution
   (`src/skills/roles/resolve-person.md`) then `attest_plan_role` (steps 1–2 above).
   The writes are independent, so one pair failing (needs sign-in, no directory
   match) never blocks the rest — carry on and track that pair separately.
3. **Confirm them together.** After the loop, give **one combined** read-back of who
   now holds what, and call out any pair you couldn't finish and why, so the maker
   can fix just that one.

> "Done — Erica now holds the Power Platform admin role and James the Workday admin
> role on this plan. I couldn't find a 'Sam Lee' in your directory, so the ServiceNow
> admin role is still open — want to try a different name or their email?"

## After assigning several roles

After a single assignment or a batch, follow `src/skills/planner/status.md` ->
**Refresh after progress** for the requesting person's next action. Use the
shared prominent handoff, not a buried one-line offer or the newly assigned
colleague's task. List only remaining relevant vacancies; when none remain,
select the caller's next coordination action or eligible work instead of
repeating the assignment prompt.
