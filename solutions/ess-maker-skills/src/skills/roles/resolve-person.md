# Roles — resolve a person to a directory object id

`attest_plan_role` identifies the person by their **directory object id**
(`subjectId`), never by name. So the first step of any "assign `<role>` to
`<person>`" request is to turn the name the maker said into that id. This is the
one hop the plan can't do for you — it's a live **directory** lookup, so it may
ask the maker to sign in.

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
where each candidate has `oid`, `displayName`, `userPrincipalName`, `mail`, and
`jobTitle`. It asks the directory for **only** a least-privilege, self-grantable
read permission, so in a normal tenant the maker can approve the one-time
sign-in themselves — no directory admin needed.

Branch on `status`:

- **`ok` with one candidate** — use its `oid`. Confirm the person by name before
  attesting ("I found Priya Sharma (priya@contoso.com) — assigning the ServiceNow
  admin role to her").
- **`ok` with several candidates** — **disambiguate.** Show the candidates in
  plain language (name, email, job title — never the raw JSON) and ask which one
  they mean. Use only the `oid` of the person they pick.
- **`no_match`** — nobody matched. Ask for a more specific name, or their email /
  user principal name, and resolve again. Never guess an id.
- **`auth_required`** — the directory needs sign-in. Ask the maker to sign in
  once ("I need you to sign in so I can look up people in your directory") and
  run the same command again. **If it still returns `auth_required` after a real
  sign-in attempt** — e.g. the maker says the prompt demanded admin approval or
  wouldn't let them consent — their tenant blocks self-service directory access
  (some large orgs, including Microsoft's own, do this). Don't dead-end: move to
  **Tier 2**.

Carry the chosen `oid` into the attestation (`src/skills/roles/attest.md`).

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
   id. If WorkIQ returns several people, ask which one they mean. Never attest on
   an unconfirmed match.

Carry the resulting `oid` into the attestation the same way — from the plan's
point of view the two tiers are interchangeable, they just differ in how the
person's id was looked up.

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
  WeveNova only *consumes* them (it keys role assignments on the id it's given).
