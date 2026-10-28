# Resolve a person to a directory object id

Some flows identify a person by their **directory object id** (`oid`), never by
name. This is the shared step that turns the name a maker says into that id. Two
capabilities call it:

- **Role attestation** — `attest_plan_role` takes the id as `subjectId`
  (`src/skills/roles/attest.md`).
- **Task assignment** — the planner assigns a task to a person with
  `assign --person <oid>` (`src/skills/planner/assign.md`).

So whenever a maker names a **person** — "make Priya the ServiceNow admin",
"assign this task to Sam" — resolve that name here first, then the calling flow
takes the `oid` from here and carries on. It's the one hop the plan can't do for
you: a live **directory** lookup, so it may ask the maker to sign in.

## Self-assignment and missing answers

For "I" or "me" in an explicit assignment request, reuse a verified signed-in
identity for the intended tenant when its object id and recognizable name are
already available. Do not ask for the same name or email again. Do not infer an
identity from the plan owner, another task's assignee, an operating-system account,
or a role statement. A role describes responsibility, not who is signed in.

If identity is still unknown, ask once in the main chat for a first or partial
name or optional work email, with **Leave unassigned for now** available. Then
use the lookup and confirmation flow below. Apply
`src/reference/ui-formatting-guidelines.md` -> **Questions that need the maker**.
A result saying "user is not available" is not an answer: keep the role
understood but the person unresolved, and do not write an assignment. Return a
failed delegated question to the main chat; never guess a name, store a deferral
as if the maker chose it, or claim the role was assigned.

This identity step belongs to assigning a person on the plan. It is not a
prerequisite for a separate `/setup` request, whose sign-in and actual access
checks are owned by foundation setup.

## How to resolve — two tiers

Person resolution has **two tiers**. Tier 1 is the directory (Microsoft Graph)
and is where almost every maker resolves. Tier 2 (WorkIQ) exists only for
tenants that won't let a maker open their own directory — try it **only** after
Tier 1 reports it can't sign in.

## Tier 1 — the directory (Microsoft Graph)

Run, from the kit root:

```
python scripts/roles/cli.py resolve-person --name "<what the maker said>"
```

`--name` accepts a display name, an email, or a user principal name. The command
prints a JSON envelope — `{"query", "status", "count", "candidates": [...]}` —
where each candidate has `oid`, `displayName`, `userPrincipalName`, and `mail`.
It asks the directory for **only** a least-privilege, self-grantable
read permission, so in a normal tenant the maker can approve the one-time
sign-in themselves — no directory admin needed.

Say a first name or partial name is fine; do not require a remembered surname or
email address. Before the first lookup consent, explain that directory read access
is used to find the colleague to assign, not to grant them admin permissions.
For candidate selection, use selectable options labeled by **display name +
initials**, with mail/UPN as disambiguating detail when returned. Include
**Leave unassigned for now** and return that decision to the caller. Do not invent
photos, job titles, or role holdings, or broaden Graph permissions for avatars.

Branch on `status`:

- **`ok` with one candidate** — use its `oid`. Confirm the person by name before
  you use the id ("I found Priya Sharma (priya@contoso.com) — is that who you
  mean?").
- **`ok` with several candidates** — **disambiguate.** Show the candidates in
  plain language (name, email — never the raw JSON) and ask which one
  they mean. Use only the `oid` of the person they pick.
- **`no_match`** — nobody matched. Offer a more specific name or optional email,
  and **Leave unassigned for now**. Never guess an id or trap the maker in retries.
- **`auth_required`** — the directory needs sign-in. Ask the maker to sign in
  once ("I need you to sign in so I can look up people in your directory") and
  run the same command again. **If it still returns `auth_required` after a real
  sign-in attempt** — e.g. the maker says the prompt demanded admin approval or
  wouldn't let them consent — their tenant blocks self-service directory access
  (some large orgs, including Microsoft's own, do this). Don't dead-end: move to
  **Tier 2**.

Hand the chosen `oid` back to the flow that called this step — attestation
carries it as `subjectId` (`src/skills/roles/attest.md`); task assignment carries
it as `--person` (`src/skills/planner/assign.md`).

## Tier 2 — WorkIQ (fallback when the directory won't open)

Use this **only** when Tier 1 keeps returning `auth_required` because the tenant
won't let the maker consent. WorkIQ rides on Microsoft 365 Copilot, which those
same locked-down tenants have already enabled org-wide, so it can resolve people
where the raw directory sign-in is refused.

1. **Find the WorkIQ tool in your host.** Look among your available tools for a
   WorkIQ entry — its name ends in `ask` or `fetch` (e.g. `workiq-preview-ask`,
   `workiq-preview-fetch`). If no WorkIQ tool is present, it isn't set up in this
   host; tell the maker resolution needs either a directory sign-in they can
   approve or WorkIQ enabled, and stop — never guess an id.
2. **Ask it for the person's directory object id.** Query by the exact name (or
   email / UPN) the maker gave, e.g. *"What is the Entra (AAD) object id / user
   id for &lt;name&gt;?"* — or fetch the matching person/user entity and read the
   id off it.
3. **Confirm and disambiguate exactly as in Tier 1** — verify the person by name
   with the maker (and job title / email if WorkIQ returns them) before using the
   id. If WorkIQ returns several people, ask which one they mean. Never use an
   unconfirmed match.

Hand the resulting `oid` back the same way — from the plan's point of view the
two tiers are interchangeable, they just differ in how the person's id was looked
up.

> Setting WorkIQ up (one time, only for tenants that need it): it's a Microsoft
> 365 Copilot capability exposed as an MCP server (`npx -y @microsoft/workiq
> mcp`, server name `workiq-preview`). A maker in a tenant with Copilot enabled
> adds it to their MCP host once; after that its `*-ask` / `*-fetch` tools are
> available here as the fallback above.

## Notes

- The lookup reuses the kit's existing directory sign-in; the maker signs in at
  most once per session and the token is reused after that.
- The object id is plumbing — never surface it to the maker as something they
  have to read or handle. Speak in names.
- **The source of truth is the maker's own directory.** Tier 1 resolves names
  against Microsoft Graph `/users` (`$search`) and Tier 2 against WorkIQ; both
  return the same Entra (AAD) object id, because those ids are minted by Entra —
  WeveNova only *consumes* them (it keys role and task assignments on the id it's
  given).
