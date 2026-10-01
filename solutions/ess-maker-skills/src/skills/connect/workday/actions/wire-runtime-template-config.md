<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Action: Initialize Workday runtime templates at conversation start

Run this action before wiring the Admin User Context redirect. It initializes
the Workday runtime template configuration on every new conversation, rather
than depending on the separately cached employee user context.

Every **Message** block is the exact text to show the user. Copy it verbatim.

---

## A.1 - Explain the scoped change

**Message:**

I'll connect your agent's conversation start to the Workday runtime
configuration so each new conversation receives the current Workday templates.

**End message.**

---

## A.2 - Resolve the exact topics

Read `workspace/agents/{AGENT_SLUG}/.component-map.json`.

Resolve exactly one `DialogComponent` for each display name:

- `Conversation Start`
- `Workday [System] - 1: Set Runtime Template Configurations`
- `Workday [System] - 1: Set User Context V2`

Save each mapped path, component ID, and schema name. Every mapped file must
exist beneath the selected agent folder. Stop on missing or duplicate matches,
unsafe paths, or incomplete identities. Do not infer filenames.

Save a rollback checkpoint before editing either mapped file:

```text
python scripts/checkpoint.py "pre-workday-runtime-template-wiring"
```

---

## A.3 - Edit without replacing customer content

In `Conversation Start`, preserve every existing action and customization.
Ensure its top-level `OnConversationStart.actions` begins with exactly one:

```yaml
- kind: BeginDialog
  id: workdayRuntimeTemplateConfiguration
  displayName: Initialize Workday runtime template configurations
  dialog: {WORKDAY_RUNTIME_TEMPLATE_DIALOG}
```

Where `{WORKDAY_RUNTIME_TEMPLATE_DIALOG}` is the resolved schema name for
`Workday [System] - 1: Set Runtime Template Configurations`.

- If this exact call is already the first action, treat the edit as complete.
- If the exact target occurs once later in the top-level action list, move only
  that action to the first position.
- If the target occurs more than once, stop instead of guessing which copy to
  retain.
- Do not remove, reorder, or rewrite any other Conversation Start action.

Then inspect `Workday [System] - 1: Set User Context V2`. If it still contains
a `BeginDialog` whose `dialog` is exactly
`{WORKDAY_RUNTIME_TEMPLATE_DIALOG}`, remove only that exact obsolete nested
call. Preserve all other actions and customizations. If no exact nested call
exists, do not change the topic.

This action must never add the runtime-template call to User Context V2.

---

## A.4 - Scan, preview, approve, and push

Run diagnostics on every edited file and resolve errors before continuing.
Build one exact `--only` argument for each changed mapped path. Never use a
wildcard.

Preview from the solution root:

```powershell
python scripts/push.py {RUNTIME_TEMPLATE_TOPIC_ARGS} --dry-run --preferred-username "{POWER_PLATFORM_MAKER}"
```

The preview may contain only Conversation Start and, when the obsolete nested
call was present, User Context V2. Stop if any unrelated file appears.

Use `vscode_askQuestions`:

```json
[
  {
    "header": "Publish Workday initialization",
    "question": "Publish this scoped Workday conversation-start change to the active agent?",
    "options": [
      { "label": "Publish" },
      { "label": "Not now" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave the selection unset. If the maker selects **Not now**, leave Runtime
active and do not push.

If approved, run:

```powershell
python scripts/push.py {RUNTIME_TEMPLATE_TOPIC_ARGS} --yes --preferred-username "{POWER_PLATFORM_MAKER}"
```

If no local edit was needed, skip the push and continue to live verification.

---

## A.5 - Verify the live contract

Run:

```powershell
python scripts/workday_connect.py record-runtime-template-wiring
```

The controller verifies that the live Conversation Start calls the resolved
runtime-template topic exactly once as its first action and that the obsolete
nested call is absent from User Context V2. It records
`runtime-template-configured` only after both live topic bodies match the
reviewed local files.

On any error after mutation, restore and push only the two mapped topic paths:

```text
python scripts/checkpoint.py --revert-reason "pre-workday-runtime-template-wiring" --only "{CONVERSATION_START_TOPIC_PATH}"
python scripts/checkpoint.py --revert-reason "pre-workday-runtime-template-wiring" --only "{WORKDAY_USER_CONTEXT_TOPIC_PATH}"
python scripts/push.py --only "{CONVERSATION_START_TOPIC_PATH}" --dry-run
python scripts/push.py --only "{WORKDAY_USER_CONTEXT_TOPIC_PATH}" --dry-run
python scripts/push.py --only "{CONVERSATION_START_TOPIC_PATH}" --yes
python scripts/push.py --only "{WORKDAY_USER_CONTEXT_TOPIC_PATH}" --yes
```

If any restore or push fails, leave the runtime phase active and report the
exact failed command for targeted remediation. Do not replace either topic
with a stock copy.
