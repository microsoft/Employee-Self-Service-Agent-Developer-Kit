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
for a user decision. The explicit DA-GA scope exclusions above remain approved.
For Entra access tokens, do not assume UPN or email. The Entra administrator
returns exactly one selected employee-identity claim name plus the Application
(client) ID through the protected one-row XLSX or equivalent CSV. `aud` may be
configured for audience validation but is never accepted as that selected
user-matching claim. The ServiceNow XLSX/CSV is generated from the same bound
values and leaves only the actual matching `sys_user` field for the
ServiceNow administrator to confirm. XLSX uses protected visible inputs plus
hidden locked metadata; CSV carries the same values and binding columns.
Neither format guesses, defaults, or manually recopies the claim.
The approved
manual runbook also covers Broadly scoped ServiceNow scope
restriction, non-email custom user identifiers, and safe coexistence with a
separate Graph Connector app-only configuration.

Secondary help references (PR #217 remains authoritative):

- [Microsoft Learn: ServiceNow for Employee Self-Service](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow)
- [ServiceNow connector actions](https://learn.microsoft.com/en-us/connectors/service-now/#actions)
- [ServiceNow connector known issues](https://learn.microsoft.com/en-us/connectors/service-now/#known-issues-and-limitations)

Use the invocation-local `SELECTED_AGENT_SLUG` and `SELECTED_AGENT_ID`
supplied by the ServiceNow DA chooser. Then read
`src/skills/connect/shared/lifecycle-runner.md` and follow it with:

```text
PROVIDER = "servicenow-da-hrsd"
AGENT_SLUG = SELECTED_AGENT_SLUG
```

The shared runner's `connect_lifecycle.py next-step` command is mandatory.
Never jump directly from a result to another checkpoint or infer that
`actionApplied` skips an incomplete provider action.
Render the ServiceNow `resume-handoff.progress` checklist and current-step
updates exactly as the shared runner specifies; do not suppress them under
the ordinary Message-block silence rule.

The runner loads
`src/skills/connect/servicenow-da-hrsd/contract.json`, persists state at
`.local/connect/servicenow-da-hrsd/agents/{AGENT_SLUG}/lifecycle.json`, and
live-reverifies every phase. Agent binding and Test pane results remain
maker-confirmed evidence; topic mutation requires explicit confirmation.
Publishing is outside ServiceNow Connect. Parameter-sharing is not a
standalone lifecycle phase; legacy
evidence is retained only as historical state and never treated as proof that
the direct connector-action path was independently verified.

Only report the integration connected after the runner completes all nine
phases, including explicit remote reuse approval and the four admin
prerequisite phases before the physical connection and topics. Do not add a
second completion message.

After that exact Dev lifecycle is complete with current passing Test evidence,
run `validation-realm-handoff`. Only then may the user choose Dev, Test, or
Prod validation. Test/Prod uses `validate-realm --realm <test|prod>` with the
administrator-confirmed target instance and client ID and is read-only: it
must prove the exact target environment and agent, report every
automated result honestly, and finish by directing the customer to that exact
agent's Test pane. It never promotes, imports, configures, sends a real-data
query, changes `activeAgent`, or publishes.
