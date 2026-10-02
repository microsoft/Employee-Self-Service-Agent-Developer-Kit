# Action: Wire the User Context redirect to Workday

Called by the lifecycle runner (`src/skills/connect/shared/lifecycle-runner.md`)
for the `agent-wiring` phase of the Workday contract. By the time this file
runs, the role gate has already passed and a rollback checkpoint has already
been saved — this file only performs the edit and pushes it.

Every **Message** block is the exact text to show the user. Copy it verbatim.

---

## A.0 — Role gate (Environment Maker)

The lifecycle runner already applied `permission-gate.md` before reading this
file using the exact programmatic Dataverse security-role query and accepted
role names declared for this phase in `contract.json`. This file starts from a
passed gate; it does not re-check it.

## A.1 — Explain what's about to change

**Message:**

I'll connect your agent's **User Context** setup to Workday so it can identify
the signed-in employee when a Workday request begins.

**End message.**

---

## A.2 — Resolve both topics from the workspace map

Read `workspace/agents/{AGENT_SLUG}/.component-map.json`.

- Find exactly one entry whose `displayName` is
  `[Admin] - User Context - Setup`. Save its map key as
  `{USER_CONTEXT_TOPIC_PATH}`.
- Find exactly one entry whose `displayName` is
  `Workday [System] - 1: Set User Context V2`. Save its `schemaName` as
  `{USER_CONTEXT_DIALOG}`.

Both entries must be `DialogComponent` records and both mapped files must
exist. Stop on missing or duplicate matches. Do not assume either filename:
current native agents commonly use `topics/Setusercontext.mcs.yml`, while
older materialized workspaces may use `topics/user-context-setup.mcs.yml`.

---

## A.3 — Edit the redirect

Read `workspace/agents/{AGENT_SLUG}/{USER_CONTEXT_TOPIC_PATH}`. Continue only
when it is either the empty `OnRedirect` scaffold or already contains the
exact redirect below. Refuse to overwrite any other actions or custom
content.

Set its `OnRedirect` to a `BeginDialog` calling the resolved dialog id:

```yaml
kind: AdaptiveDialog
beginDialog:
  kind: OnRedirect
  id: main
  priority: 0
  actions:
    - kind: BeginDialog
      id: bfT9Kx
      displayName: Redirect to Workday System Get User Context
      dialog: "{USER_CONTEXT_DIALOG}"
```

---

## A.4 — Scan, dry run, push

Check for errors using the diagnostics tool on the edited file. Fix any
before continuing.

Preview and push:

```
python scripts/push.py --only "{USER_CONTEXT_TOPIC_PATH}" --dry-run --preferred-username "{POWER_PLATFORM_MAKER}"
```

Run this command from the solution root containing `.local/config.json`.
Review the preview. It must contain only the setup topic. This action updates
the redirect but deliberately does not activate Workday topics; activation
runs only after flow connection and parameter sharing are complete. If any
other file appears, stop and report it instead of publishing unrelated work.

When the preview contains only the expected setup topic, continue without
asking for a separate publish confirmation. This scoped redirect is part of
the already approved Workday Connect operation. Run:

```
python scripts/push.py --only "{USER_CONTEXT_TOPIC_PATH}" --yes --preferred-username "{POWER_PLATFORM_MAKER}"
```

The scoped push re-reads the current live topic before mutation. If the exact
redirect is already live, treat the action as successful and continue. If the
live topic is still the compatible empty scaffold, apply the redirect. If it
contains any other actions or custom redirect content, stop with the precise
conflict reported by the push. Do not ask the maker to choose an overwrite
strategy, and never replace newer live content with the older workspace copy.

Only when the command exits successfully, set `ACTION_RESULT = "applied"`.
If it fails, stop and report the failure; do not return an applied result.

---

## A.5 — Return

Return `ACTION_RESULT` to the lifecycle runner. With an `"applied"` result,
also return the exact `{USER_CONTEXT_TOPIC_PATH}` as
`ACTION_ROLLBACK_PUSH_GLOB`. Do not return a wildcard or directory. The runner
re-runs `WD-REST-002` for `AGENT_SLUG` only after an `"applied"` result and
decides whether to advance or use the named restore point — this file does not
re-run the checkpoint itself.
