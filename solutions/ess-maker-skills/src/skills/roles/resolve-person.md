# Roles — resolve a person to a directory object id

`attest_plan_role` identifies the person by their **directory object id**
(`subjectId`), never by name. So the first step of any "assign `<role>` to
`<person>`" request is to turn the name the maker said into that id. This is the
one hop the plan can't do for you — it's a live **directory** lookup, so it may
ask the maker to sign in.

## Resolve

Run, from the kit root:

```
python scripts/roles/cli.py resolve-person --name "<what the maker said>"
```

`--name` accepts a display name, an email, or a user principal name. The command
prints a JSON envelope — `{"query", "status", "count", "candidates": [...]}` —
where each candidate has `oid`, `displayName`, `userPrincipalName`, `mail`, and
`jobTitle`.

Branch on `status`:

- **`auth_required`** — the directory needs sign-in. Ask the maker to sign in once
  ("I need you to sign in so I can look up people in your directory"), then run
  the same command again. Don't proceed without an `oid`.
- **`no_match`** — nobody matched. Ask for a more specific name, or their email /
  user principal name, and resolve again. Never guess an id.
- **`ok` with one candidate** — use its `oid`. Confirm the person by name before
  attesting ("I found Priya Sharma (priya@contoso.com) — assigning the ServiceNow
  admin role to her").
- **`ok` with several candidates** — **disambiguate.** Show the candidates in
  plain language (name, email, job title — never the raw JSON) and ask which one
  they mean. Use only the `oid` of the person they pick.

Carry the chosen `oid` into the attestation (`src/skills/roles/attest.md`).

## Notes

- The lookup reuses the kit's existing directory sign-in; the maker signs in at
  most once per session and the token is reused after that.
- The object id is plumbing — never surface it to the maker as something they
  have to read or handle. Speak in names.
