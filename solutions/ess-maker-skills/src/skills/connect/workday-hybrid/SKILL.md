# Workday Hybrid Flow Authorization

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling
or what files you are reading.

This is a lightweight authorization path for an already-installed,
Cosmos-backed Workday hybrid agent. It does not run the standard Workday setup
or modify its checklist.

---

## 1 — Select environment

Read `dataverseEndpoint` from `.local/config.json` if the file exists. Save the
value without a trailing slash as CONFIGURED_ENV_URL.

Use `vscode_askQuestions`. Include the first option only when
CONFIGURED_ENV_URL is available:

```json
[
  {
    "header": "Environment",
    "question": "Which Power Platform environment should receive the Workday hybrid authorization?",
    "options": [
      {
        "label": "Use configured environment — {CONFIGURED_ENV_URL}",
        "description": "Use the environment currently configured in this workspace",
        "recommended": true
      },
      {
        "label": "Choose from my environments",
        "description": "Sign in and select a Dataverse environment from your tenant"
      },
      {
        "label": "Enter an environment URL",
        "description": "Provide a specific Dataverse environment URL"
      }
    ],
    "allowFreeformInput": false
  }
]
```

- **Use configured environment**: set ENV_URL to CONFIGURED_ENV_URL.
- **Choose from my environments**: show the following message, then run the
  discovery command.

  **Message (do NOT wait for a response — continue immediately):**

  A browser window may open for Microsoft sign-in while I retrieve the
  Dataverse environments available to your account.

  **End message.**

  ```text
  python scripts/discover.py --list-environments
  ```

  Parse `ENVIRONMENT_LIST_JSON:` from stdout. Build a `vscode_askQuestions`
  option for each environment using `{displayName} — {instanceUrl}` as the
  label and `{type}` as the description. Do not preselect an environment.
  Set ENV_URL to the selected `instanceUrl`.
- **Enter an environment URL**: ask:

  ```json
  [
    {
      "header": "Environment URL",
      "question": "Enter the Dataverse environment URL. Example: https://yourorg.crm.dynamics.com",
      "allowFreeformInput": true
    }
  ]
  ```

  Trim the answer, remove the trailing slash, and run:

  ```text
  python scripts/discover.py --resolve-environment-url "<ENV_URL>"
  ```

  Continue only when `SELECTED_ENV_JSON:` confirms the URL belongs to a
  Dataverse environment available to the signed-in account.

If environment discovery or URL resolution fails, show the exact command
error and stop. Never fall back silently to CONFIGURED_ENV_URL.

---

## 2 — Collect identifiers

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
python scripts/enable_workday_hybrid_flow_authorization.py --url "<ENV_URL>" --bot-id <BOT_ID> --workflow-id <FLOW_ID> [--workflow-id <FLOW_ID> ...] --validate-only
```

If it reports an invalid GUID, show that error and return to this section.

---

## 3 — Confirm

**Message:**

This will create or reuse Dataverse authorization records with the following
target:

Environment: `{ENV_URL}`
Agent bot ID: `{BOT_ID}`
Workflow IDs:
{one `- {FLOW_ID}` line per workflow}

After you confirm, a browser window will open and Microsoft will ask you to
choose the account used for this environment.

Do you want me to continue?

**End message.**

Use `vscode_askQuestions`:

```json
[
  {
    "header": "Enable authorization",
    "question": "Sign in and apply Workday hybrid flow authorization to {ENV_URL}?",
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

## 4 — Run

Run from the `solutions/ess-maker-skills` directory, using one
`--workflow-id` argument per workflow:

```text
python scripts/enable_workday_hybrid_flow_authorization.py --url "<ENV_URL>" --bot-id <BOT_ID> --workflow-id <FLOW_ID> [--workflow-id <FLOW_ID> ...] --interactive-auth --yes
```

The `--interactive-auth` flag must always be present for this skill. It skips
silent token acquisition and opens Microsoft's account picker even when the
ADK has a cached session. It does not delete the shared token cache. Never ask
the user for an access token.

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
