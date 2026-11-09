# Connect the credential to the agent

Guide the maker to Copilot Studio **Settings -> Connection settings**, select
**Connect** for ServiceNow, choose the selected credential, and save.

[Open Employee Self-Service (HR) in Copilot Studio]({COPILOT_STUDIO_AGENT_URL})

Use `links.copilotStudioAgent.url` from the provider inspection result.

Open `Settings` → `Connection settings`; do not invent a tab-specific URL.

Ask whether the ServiceNow row currently shows Connected. A prior attestation
is context only and cannot answer the current question. Render the target URL
and binding steps above in the ordinary current-task reply, then use this
compact payload with the exact selected agent and connection:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "Connect ServiceNow to agent",
    "question": "Selected agent: Employee Self-Service (HR) (`{SELECTED_AGENT_SLUG}` / `{SELECTED_AGENT_ID}`)\nSelected credential: `{CONNECTION_DISPLAY_NAME}` (`{CONNECTION_ID}`)\n\nDoes the ServiceNow row currently show Connected with this selected credential?\n\nThis records only current Manual agent-binding evidence; it does not prove business success.",
    "options": [
      { "label": "Yes, the selected credential is shown as Connected" },
      { "label": "Not yet, the agent binding is incomplete" }
    ],
    "allowFreeformInput": false
  }
]
```

After explicit confirmation run:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-agent-connection --connection-id <id>
```

Do not call the UI `user-connections` endpoint, reuse browser tokens, or use a
MinimalBot connection-reference update as a substitute. Return
`ACTION_RESULT = "applied"` after the attestation is recorded; if the maker is
unavailable or declines, return `ACTION_RESULT = "cancelled"`.

The recorded binding identity covers the exact provider, profile, agent,
environment, selected physical connection, and ServiceNow connection-reference
metadata. Later approved topic-state or same-instance portal changes do not
require re-binding. A changed agent, environment, connection, auth/resource/
instance metadata, or connection reference does.
