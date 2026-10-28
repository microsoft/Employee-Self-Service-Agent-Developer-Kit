# Roles — who holds what (and revoking)

Apply `roles/SKILL.md` for the shared-plan gate and the main-chat communication
rules, including the prominent next-step handoff.

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
   role's tasks stop showing up for that person.
3. Confirm the effect in plain language: that person no longer sees that role's
   work on the plan.

Only confirm revocation after a successful shared result. Then follow
`src/skills/planner/status.md` -> **Refresh after progress** for the requesting
person's next action. If unfinished work has lost its owner, identify that
vacancy without assigning a replacement or starting another person's work.
