# Connect ServiceNow HRSD to the DA HR agent

This provider uses the shared connect lifecycle. It supports only the exact
editable Employee Self-Service HR agent and does not use the retained Preview
ServiceNow state or steps.

Resolve `AGENT_SLUG` from `.local/config.json` (`activeAgent`, falling back to
`agent.slug`). Then read `src/skills/connect/shared/lifecycle-runner.md` and
follow it with:

```text
PROVIDER = "servicenow-da-hrsd"
AGENT_SLUG = the exact active agent slug
```

The runner loads
`src/skills/connect/servicenow-da-hrsd/contract.json`, persists state at
`.local/connect/servicenow-da-hrsd/agents/{AGENT_SLUG}/lifecycle.json`, and
live-reverifies every phase. Agent binding, parameter sharing, and Test pane
results remain maker-confirmed evidence; topic mutation and publish require
explicit confirmation.

Only report the integration connected after the runner completes all six
phases. Do not add a second completion message.
