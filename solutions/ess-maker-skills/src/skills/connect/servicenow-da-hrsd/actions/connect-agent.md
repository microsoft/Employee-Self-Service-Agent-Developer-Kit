# Connect the credential to the agent

Guide the maker to Copilot Studio **Settings -> Connection settings**, select
**Connect** for ServiceNow, choose the selected credential, and save.

[Open Employee Self-Service (HR) in Copilot Studio]({COPILOT_STUDIO_AGENT_URL})

Use `links.copilotStudioAgent.url` from the provider inspection result.

Open `Settings` → `Connection settings`; do not invent a tab-specific URL.

Ask whether the ServiceNow row currently shows Connected. A prior attestation
is context only and cannot answer the current question. Use this exact visible
handoff payload after rendering `{CURRENT_PROGRESS}`,
`{COPILOT_STUDIO_AGENT_URL}`, and the selected connection display name/ID:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "Connect ServiceNow to agent",
    "question": "{CURRENT_PROGRESS}\n\nPurpose: bind the selected current ServiceNow credential to this exact HR agent.\n\nOwner: ESS Maker / Agent Developer in Copilot Studio.\n\nOpen Employee Self-Service (HR): {COPILOT_STUDIO_AGENT_URL}\n\nIn this exact agent:\n1. Open Settings -> Connection settings.\n2. Find the ServiceNow row.\n3. Select Connect.\n4. Choose the selected credential `{CONNECTION_DISPLAY_NAME}` (`{CONNECTION_ID}`).\n5. Save and confirm the ServiceNow row currently shows Connected.\n\nDo not substitute the UI `user-connections` endpoint, browser tokens, or a MinimalBot reference update.\n\nDoes the ServiceNow row currently show Connected with this selected credential?",
    "options": [
      { "label": "Yes, Connected", "recommended": true },
      { "label": "Not yet" }
    ],
    "allowFreeformInput": false
  }
]
```

After explicit confirmation run:

```text
python scripts/connect_servicenow_da.py record-agent-connection --connection-id <id>
```

Do not call the UI `user-connections` endpoint, reuse browser tokens, or use a
MinimalBot connection-reference update as a substitute. Return
`ACTION_RESULT = "applied"` after the attestation is recorded; if the maker is
unavailable or declines, return `ACTION_RESULT = "cancelled"`.
