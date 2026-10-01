# Connect the credential to the agent

Guide the maker to Copilot Studio **Settings -> Connection settings**, select
**Connect** for ServiceNow, choose the selected credential, and save.

[Open Employee Self-Service (HR) in Copilot Studio]({COPILOT_STUDIO_AGENT_URL})

Use `links.copilotStudioAgent.url` from the provider inspection result.

Open `Settings` → `Connection settings`; do not invent a tab-specific URL.

Ask whether the ServiceNow row currently shows Connected. A prior attestation
is context only and cannot answer the current question. After explicit
confirmation run:

```text
python scripts/connect_servicenow_da.py record-agent-connection --connection-id <id>
```

Do not call the UI `user-connections` endpoint, reuse browser tokens, or use a
MinimalBot connection-reference update as a substitute. Return
`ACTION_RESULT = "applied"` after the attestation is recorded; if the maker is
unavailable or declines, return `ACTION_RESULT = "cancelled"`.
