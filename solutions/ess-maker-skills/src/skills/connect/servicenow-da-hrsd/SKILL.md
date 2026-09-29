# Connect ServiceNow HRSD to the DA HR agent

This provider uses the shared connect lifecycle. It supports only the exact
editable Employee Self-Service HR agent and does not use the retained Preview
ServiceNow state or steps.

The lifecycle is Actions-only and supports only Microsoft Entra ID User Login
(`entraIDUserLogin`). Knowledge/Graph Connector retrieval, certificate/App B,
PFX, Basic/OAuth2, Dataverse connections/references, cloud flows, and portal
URL setup are out of scope. Admin prerequisites are always guided: the skill
may discover and verify with read-only APIs, but never creates or patches an
Entra application or ServiceNow OIDC/security object.

Use Draft PR #217 (`users/mukesh4139/servicenow-connect-adk`) as the
source-of-truth for the end-to-end admin runbook structure, delegated handoff,
resume, and evidence patterns. Use current Microsoft Learn ServiceNow
connector documentation to validate external field semantics, IDs,
permissions, and auth values. If those sources conflict in a way that changes
user steps, required artifacts, admin roles, auth requirements, or acceptance
criteria, stop and ask the user rather than silently diverging or mechanically
copying Preview-era behavior. The explicit DA-GA scope exclusions above are
already approved deviations.

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

Only report the integration connected after the runner completes all ten
phases, including explicit remote reuse approval and the four admin
prerequisite phases before the physical connection and topics. Do not add a
second completion message.
