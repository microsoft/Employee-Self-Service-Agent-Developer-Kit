# Action: Activate all Workday topics

Run this action only after the reviewed Workday flows are connected to the
agent and **Allow permission to share parameters** is enabled.

Every **Message** block is the exact text to show the user. Copy it verbatim.

---

## B.1 — Resolve the complete Workday topic set

Read `workspace/agents/{AGENT_SLUG}/.component-map.json`. This map is the
materialized workspace projection of the source `agent.yml`.

Select every entry that satisfies all of these conditions:

- `componentKind` is `DialogComponent`;
- `schemaName` starts with `{AGENT_SCHEMA}.topic.Workday`;
- `displayName` starts with `Workday`;
- the mapped path starts with `topics/` and ends with `.mcs.yml`;
- the mapped file exists beneath the selected agent directory.

Reject unsafe paths, duplicate component IDs, missing schema names, or an empty
result. Do not use a handwritten filename list. For the current reviewed ESS
HR template this resolves all 21 Workday dialog topics from `agent.yml`,
including business topics and supporting system topics.

Sort the mapped paths and build `{WORKDAY_TOPIC_ARGS}` as one exact
`--only "{path}"` argument per selected topic.

---

## B.2 — Preview activation

Run from the solution root containing `.local/config.json`:

```powershell
python scripts/push.py {WORKDAY_TOPIC_ARGS} --activate --dry-run --preferred-username "{POWER_PLATFORM_MAKER}"
```

The preview count must equal the selected component-map count. Every previewed
component must be one of the resolved Workday dialog topics. Stop if the count
differs or any non-Workday topic appears.

**Message:**

The Workday connections and shared parameters are ready. I found
**{WORKDAY_TOPIC_COUNT}** Workday topics from the installed agent definition.
I can now enable that exact set without changing their dialog content.

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Enable Workday topics",
    "question": "Enable all Workday topics in the active ESS HR agent?",
    "options": [
      { "label": "Enable", "recommended": true },
      { "label": "Not now" }
    ],
    "allowFreeformInput": false
  }
]
```

If the user selects **Not now**, set `ACTION_RESULT = "cancelled"` and leave
the runtime phase active.

---

## B.3 — Activate and verify

If the user selects **Enable**, run:

```powershell
python scripts/push.py {WORKDAY_TOPIC_ARGS} --activate --yes --preferred-username "{POWER_PLATFORM_MAKER}"
```

`push.py` sends a full `BotComponentUpdate` for each selected topic through the
native MinimalBot components endpoint, preserves the dialog body, sets both
`state` and `status` to `Active`, and rereads every component. Continue only
when the command reports that all `{WORKDAY_TOPIC_COUNT}` topics were verified.

Set `ACTION_RESULT = "applied"` and
`WORKDAY_TOPICS_ACTIVATED = true`. On any error or count mismatch, stop and
leave the runtime phase active.
