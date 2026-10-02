# Action: Activate all Workday topics

Run this action only after the reviewed Workday flows are connected to the
agent and **Allow permission to share parameters** is enabled.

Every **Message** block is the exact text to show the user. Copy it verbatim.

---

## B.1 — Resolve the complete Workday topic set

Read `workspace/agents/{AGENT_SLUG}/.component-map.json`. This map is the
materialized workspace projection of the source `agent.yml`.

Resolve the repository-reviewed ESS HR Workday inventory. The resolver must
match all 23 exact schema names in the checked-in contract, including the two
topics whose schema names do not begin with `Workday`:

- `{AGENT_SCHEMA}.topic.EmployeeUpdatePhoneNumber`
- `{AGENT_SCHEMA}.topic.GetReferenceData`

For every reviewed entry:

- `componentKind` must be `DialogComponent`;
- the exact schema name must be in the reviewed 23-topic HR inventory;
- `displayName` must start with `Workday`;
- the mapped path starts with `topics/` and ends with `.mcs.yml`;
- the mapped file exists beneath the selected agent directory.

Reject unsafe paths, duplicate component IDs, missing schema names, any missing
reviewed schema, or an empty result. `push.py --activate` independently
enforces the same exact mapped set and rejects omitted Workday topics or any
selected non-Workday dialog; these instructions are not the only safety
boundary. Do not derive the set from a broad display-name search. The two
disabled employee/manager handoff topics are not in the reviewed inventory and
must remain excluded. For the current ESS HR template this resolves all 23
active-contract Workday dialog topics, including business and supporting
system topics.

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
differs, any non-Workday topic appears, or the command reports pending local
content changes. Content changes require their own scoped review and push;
activation approval never approves topic-content edits.

**Message:**

The Workday connections and shared parameters are ready. I found
**{WORKDAY_TOPIC_COUNT}** Workday topics included with this agent. I can now
enable all of them without changing their configured behavior.

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Enable Workday topics",
    "question": "Enable all Workday topics in the active ESS HR agent?",
    "options": [
      { "label": "Enable" },
      { "label": "Not now" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave the selection unset. Enabling topics is an explicit mutation approval,
not a recommended answer.

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
`state` and `status` to `Active`, and rereads every component. Continue when the
command reports that all `{WORKDAY_TOPIC_COUNT}` topics were verified Active.
The command may also report dependency diagnostics such as
`CloudFlow NotFound`; preserve those diagnostics for support correlation, but
do not treat them as an activation failure or proof of a broken package.

Record the live activation evidence:

```powershell
python scripts/workday_connect.py record-topic-activation
```

This controller command resolves the same complete mapped Workday topic set,
authenticates as the recorded maker, and rereads `state` and `status` for every
topic. It accepts no manual boolean evidence. The command records activation as
complete when all mapped topics are Active; topic metadata diagnostics do not
create a runtime blocker by themselves.

Set `ACTION_RESULT = "applied"` and
`WORKDAY_TOPICS_ACTIVATED = true`. On any error or count mismatch, stop and
leave the runtime phase active.
