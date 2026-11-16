# Action: Wire the User Context redirect to Workday

**Development only.** Require verified `activeTargetRealm: dev` before
checkpointing, editing or pushing local topics. Test and Production preserve
the redirect carried by promotion; do not run this authoring action there.

Called by the native DA Workday Runtime phase in
`src/skills/connect/workday/configure-power-platform.md` after approved runtime
configuration, flow attachment, topic activation, and runtime-template wiring.
This action performs only the scoped redirect edit and push.

Every **Message** block is the exact text to show the user. Copy it verbatim.

---

## A.0 — Verify the calling phase and save a restore point

Require the current Runtime phase's approved target and recorded maker, plus
the controller-verified `runtime-template-configured` result. Do not run this
action independently or use a CEA permission gate as evidence.

Save a rollback checkpoint before editing the mapped topic:

```text
python scripts/checkpoint.py "pre-workday-user-context-redirect"
```

## A.1 — Explain what's about to change

**Message:**

I'll configure the agent to identify the signed-in employee when a Workday
request starts.

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
If it fails, follow the scoped recovery in A.5 and report the failure; do not
return an applied result.

---

## A.5 — Return

Return `ACTION_RESULT` to the calling Runtime phase. Only an `"applied"`
result permits it to continue to `record-agent-binding`, which performs the
controller's live verification. Do not run a separate readiness checkpoint or
mark the Runtime phase complete here.

If mutation was attempted and the action fails, restore and publish only the
exact mapped setup topic:

```text
python scripts/checkpoint.py --revert-reason "pre-workday-user-context-redirect" --only "{USER_CONTEXT_TOPIC_PATH}"
python scripts/push.py --only "{USER_CONTEXT_TOPIC_PATH}" --dry-run --preferred-username "{POWER_PLATFORM_MAKER}"
python scripts/push.py --only "{USER_CONTEXT_TOPIC_PATH}" --yes --preferred-username "{POWER_PLATFORM_MAKER}"
```

If any restore or push fails, stop and report the failure. Leave Runtime
incomplete; never replace the topic with a stock copy or publish unrelated work.
