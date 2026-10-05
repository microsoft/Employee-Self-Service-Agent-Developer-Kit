# Connect ServiceNow HRSD to the DA HR agent

This provider uses the shared connect lifecycle. It supports only the exact
editable Employee Self-Service HR agent and does not use the retained Preview
ServiceNow state or steps. One lifecycle instance serves the current active
HR agent/profile only; it does not combine HRSD and ITSM into one state file.
ITSM remains a separate provider/PR layer.

The lifecycle is Actions-only and supports only Microsoft Entra ID User Login
(`entraIDUserLogin`). Knowledge/Graph Connector retrieval, certificate/App B,
PFX, Basic/OAuth2, Dataverse connections/references, and cloud flows remain
out of scope. The HR Setup
Configurations topic's Portal Base URI is now in scope: the skill may update
that exact authored node through the native component API only with an
administrator-supplied full portal URL and guarded rollback, or guide the same
manual edit when the API path is unavailable. Admin prerequisites are always guided: the skill
may discover and verify with read-only APIs, but never creates or patches an
Entra application or ServiceNow OIDC/security object.

Strictly follow Draft PR #217
(`users/mukesh4139/servicenow-connect-adk`) as the source-of-truth for admin
steps, requirements, runbook structure, delegated handoff, resume, and
evidence patterns unless the user approves a deviation. Microsoft Learn is a
secondary reference that can explain fields or flag a possible external
change; it never overrides PR #217 by itself. If Learn or current runtime
evidence suggests PR #217 is stale in a way that changes user steps, required
artifacts, admin roles, auth requirements, or acceptance criteria, stop and
report the old PR behavior, current evidence, proposed deviation, and impact
for a user decision. The explicit DA-GA scope exclusions above remain approved. For Entra access
tokens, `email` and `upn` are configurable optional claims; `aud` is a built-in
access-token audience claim that must be validated, not added as an optional
claim. The approved manual runbook also covers Broadly scoped ServiceNow scope
restriction, non-email custom user identifiers, and safe coexistence with a
separate Graph Connector app-only configuration.

Secondary help references (PR #217 remains authoritative):

- [Microsoft Learn: ServiceNow for Employee Self-Service](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow)
- [ServiceNow connector actions](https://learn.microsoft.com/en-us/connectors/service-now/#actions)
- [ServiceNow connector known issues](https://learn.microsoft.com/en-us/connectors/service-now/#known-issues-and-limitations)

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
live-reverifies every phase. Agent binding and Test pane results remain
maker-confirmed evidence; topic mutation and publish require explicit
confirmation. Parameter-sharing is not a standalone lifecycle phase; legacy
evidence is retained only as historical state and never treated as proof that
the direct connector-action path was independently verified.

Only report the integration connected after the runner completes all ten
phases, including explicit remote reuse approval and the four admin
prerequisite phases before the physical connection and topics. Do not add a
second completion message.
