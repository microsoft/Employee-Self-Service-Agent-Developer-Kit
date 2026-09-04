# Roles — who holds what (and revoking)

## List assignments on the plan

To answer "who holds the ServiceNow admin role?", "who's assigned on this plan?",
or to check before/after attesting, call `list_plan_role_assignments` with the
`planId`. Filter when it helps:

- by person: `subjectId`,
- by role: `role`,
- by state: `status` = `Active` or `Revoked` (default view is the active ones).

Present it grouped by role in plain language — "ServiceNow admin: Priya Sharma;
Workday admin: nobody yet". Resolve object ids back to names only when you already
have them from this session; don't imply you keep a record of people.

## The attestable roles

`list_attestable_roles` returns the exact set the plan accepts. Use it to answer
"what roles can I assign?" and to validate a maker's request before attesting.

## Revoke a role

To take a person off a role ("Priya isn't the ServiceNow admin anymore"):

1. Find the assignment with `list_plan_role_assignments` (filter by `subjectId`
   and/or `role`) — keep its assignment id and ETag.
2. Call `revoke_role_assignment` with that assignment id (pass the ETag to
   converge). This soft-revokes it — the assignment flips to `Revoked`, and the
   role's pooled tasks stop showing up for that person.
3. Confirm the effect in plain language: that person no longer sees that role's
   work on the plan.
