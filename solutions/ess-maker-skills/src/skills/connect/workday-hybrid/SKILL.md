# Workday Hybrid Flow Authorization

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling
or what files you are reading.

This is a lightweight authorization path for an already-installed,
Cosmos-backed Workday hybrid agent. It does not run the standard Workday setup
or modify its checklist.

---

## 1 — Collect identifiers

Read `dataverseEndpoint` from `.local/config.json`. If it is missing:

**Message:**

I couldn't find a configured Dataverse environment. Run `/setup` first, then
run `/connect workday-hybrid` again.

**End message.**

Stop.

**Message:**

I'll enable Dataverse flow authorization for an existing Workday hybrid agent.
This requires the agent's bot ID and the workflow IDs it needs to call.

**End message.**

Use `vscode_askQuestions`:

```json
[
  {
    "header": "Agent bot ID",
    "question": "Enter the Cosmos-backed agent's CdsBotId GUID.",
    "allowFreeformInput": true
  },
  {
    "header": "Workflow IDs",
    "question": "Enter the workflow GUIDs to authorize, separated by commas.",
    "allowFreeformInput": true
  }
]
```

Trim the answers. Split workflow IDs on commas and discard empty entries. Do
not attempt to repair malformed identifiers.

Run a local validation without making Dataverse calls:

```text
python scripts/enable_workday_hybrid_flow_authorization.py --bot-id <BOT_ID> --workflow-id <FLOW_ID> [--workflow-id <FLOW_ID> ...] --validate-only
```

If it reports an invalid GUID, show that error and return to this section.

---

## 2 — Confirm

**Message:**

This will create or reuse a delegated authorization and access team in
Dataverse, then grant that team access to the requested workflows.

Do you want me to continue?

**End message.**

Use `vscode_askQuestions`:

```json
[
  {
    "header": "Enable authorization",
    "question": "Apply Workday hybrid flow authorization in the configured environment?",
    "options": [
      {
        "label": "Enable authorization",
        "description": "Create or reuse the required records and workflow shares",
        "recommended": true
      },
      {
        "label": "Cancel",
        "description": "Make no Dataverse changes"
      }
    ],
    "allowFreeformInput": false
  }
]
```

If the user cancels:

**Message:**

Cancelled. No Dataverse changes were made.

**End message.**

Stop.

---

## 3 — Run

Run from the `solutions/ess-maker-skills` directory, using one
`--workflow-id` argument per workflow:

```text
python scripts/enable_workday_hybrid_flow_authorization.py --bot-id <BOT_ID> --workflow-id <FLOW_ID> [--workflow-id <FLOW_ID> ...] --yes
```

The script uses the ADK's cached Microsoft sign-in and the
`dataverseEndpoint` from `.local/config.json`. Never ask the user for an access
token.

If the command succeeds:

**Message:**

Workday hybrid flow authorization is enabled. The command output shows which
Dataverse records and workflow shares were created or reused.

**End message.**

If the command fails:

**Message:**

Workday hybrid flow authorization failed.

Command error:

~~~
{paste the command's complete error output verbatim}
~~~

Review the reported Dataverse error, correct the bot ID, workflow IDs,
permissions, or environment as indicated, then run
`/connect workday-hybrid` again.

**End message.**
