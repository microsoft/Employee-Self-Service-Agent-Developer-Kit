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
- `[System] - User Context - Validate`

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
Find exactly one top-level `BeginDialog` whose `dialog` is the resolved schema
name for `[System] - User Context - Validate`. Immediately before that action,
ensure there is exactly one:

```yaml
- kind: BeginDialog
  id: workdayRuntimeTemplateConfiguration
  displayName: Initialize Workday runtime template configurations
  dialog: "{WORKDAY_RUNTIME_TEMPLATE_DIALOG}"
```

Where `{WORKDAY_RUNTIME_TEMPLATE_DIALOG}` is the resolved schema name for
`Workday [System] - 1: Set Runtime Template Configurations`.

- If this exact call is already immediately before User Context Validate, treat
  the edit as complete.
- If the exact target occurs once elsewhere in the top-level action list, move
  only that action to immediately before User Context Validate.
- If the target occurs more than once, stop instead of guessing which copy to
  retain.
- If User Context Validate is missing, duplicated, or nested rather than a
  top-level action, stop instead of choosing another insertion point.
- Do not remove, reorder, or rewrite any other Conversation Start action.

Then inspect `Workday [System] - 1: Set User Context V2`. If it still contains
a `BeginDialog` whose `dialog` is exactly
`{WORKDAY_RUNTIME_TEMPLATE_DIALOG}`, remove only that exact obsolete nested
call. Preserve all other actions and customizations. If no exact nested call
exists, do not change the topic.

This action must never add the runtime-template call to User Context V2.

---

## A.4 - Scan, preview, and push

Run diagnostics on every edited file and resolve errors before continuing.
Build one exact `--only` argument for each changed mapped path. Never use a
wildcard.

Preview from the solution root:

```powershell
python scripts/push.py {RUNTIME_TEMPLATE_TOPIC_ARGS} --dry-run --preferred-username "{POWER_PLATFORM_MAKER}"
```

The preview may contain only Conversation Start and, when the obsolete nested
call was present, User Context V2. Stop if any unrelated file appears.

When the preview contains only those expected mapped paths, continue without
asking for a separate publish confirmation. This scoped runtime wiring is part
of the already approved Workday Connect operation. Run:

```powershell
python scripts/push.py {RUNTIME_TEMPLATE_TOPIC_ARGS} --yes --preferred-username "{POWER_PLATFORM_MAKER}"
```

The scoped push re-reads the current live topics before mutation. If the exact
wiring is already live, treat the action as successful and continue. If newer
live content changed unrelated actions, the push preserves those actions and
applies only this reviewed insertion, move, or removal. If newer content
overlaps the exact action being changed, stop with the reported precise
conflict. Do not ask the maker to choose an overwrite strategy, and never
replace the live topic with the older workspace copy.

If no local edit was needed, skip the push and continue to live verification.

---

## A.5 - Verify the live contract

Run:

```powershell
python scripts/workday_connect.py record-runtime-template-wiring
```

The controller verifies that the live Conversation Start calls the resolved
runtime-template topic exactly once immediately before the top-level User
Context Validate action and that the obsolete nested call is absent from User
Context V2. It records
`runtime-template-configured` only after both live topic bodies match the
reviewed local files.

On any error after mutation, restore and push only the two mapped topic paths:

```text
python scripts/checkpoint.py --revert-reason "pre-workday-runtime-template-wiring" --only "{CONVERSATION_START_TOPIC_PATH}"
python scripts/checkpoint.py --revert-reason "pre-workday-runtime-template-wiring" --only "{WORKDAY_USER_CONTEXT_TOPIC_PATH}"
python scripts/push.py --only "{CONVERSATION_START_TOPIC_PATH}" --only "{WORKDAY_USER_CONTEXT_TOPIC_PATH}" --dry-run --preferred-username "{POWER_PLATFORM_MAKER}"
python scripts/push.py --only "{CONVERSATION_START_TOPIC_PATH}" --only "{WORKDAY_USER_CONTEXT_TOPIC_PATH}" --yes --preferred-username "{POWER_PLATFORM_MAKER}"
```

If any restore or push fails, leave the runtime phase active and report the
exact failed command for targeted remediation. Do not replace either topic
with a stock copy.
