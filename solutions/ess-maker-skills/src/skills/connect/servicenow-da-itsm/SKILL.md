# Connect ServiceNow ITSM to the DA IT agent

This provider uses the shared connect lifecycle. It supports only the exact
chooser-selected editable Employee Self-Service (IT) agent and does not use
the retained Preview ServiceNow state or steps. One lifecycle instance serves
one IT agent/profile only. It may read the exact HRSD lifecycle solely for
maker-confirmed compatible shared-configuration discovery; it never migrates,
merges, or copies the HRSD lifecycle or its agent-scoped evidence.

The lifecycle is Actions-only and supports only Microsoft Entra ID User Login
(`entraIDUserLogin`). Knowledge/Graph Connector retrieval, certificate/App B,
PFX, Basic/OAuth2, Dataverse connections/references, and cloud flows remain
out of scope. The IT Setup Configurations topic's Portal Base URI is in scope:
the skill may update
that exact authored node through the native component API only with an
administrator-supplied full portal URL and guarded rollback, or guide the same
manual edit when the API path is unavailable. Admin prerequisites are always guided: the skill
may discover and verify with read-only APIs, but never creates or patches an
Entra application or ServiceNow OIDC/security object.

The checked-in HRSD rev6 runbook is the shared implementation baseline. The
user-provided DA ServiceNow review source confirms that the ITSM topics are
already included in the IT agent and that customer-facing Employee
Self-Service uses delegated Microsoft Entra ID User Login. The HR-only Core
gate has separate historical design evidence: Draft PR #217 commit
`e9550ddd` adds the gate in
`src/skills/setup/servicenow/capture-servicenow-config.md` with the explicit
condition `scope.hrsd == true`; the older reference update `f3bdf293` records
that `com.sn_hr_core` supplies `sn_hr_core_case` and other HRSD tables.
Together these support omitting that HRSD data prerequisite from this
IT-only lifecycle. They do not prove that every current ITSM/OIDC instance
needs no ServiceNow plugin or capability; the OIDC phase still stops when the
tenant lacks the required OIDC capability.

The current authenticated review-site revision was not freshly fetched; do
not invent additional requirements from the review URL. For Entra access
tokens, do not assume UPN or email. The Entra administrator returns one or
more confirmed employee-identity token claim candidates through the protected
XLSX workbook. The ServiceNow administrator then chooses exactly one candidate
and fills its matching `sys_user` field in a second protected XLSX workbook.
Both files open on a ServiceNow-specific `Steps` sheet, use a two-column
`Worksheet`, and retain hidden locked `_metadata` for import integrity. The
current administrator's editable cells are yellow and all locked cells are
gray. The ServiceNow workbook is generated from the confirmed Entra return and
preserves the exact claim row order; claims are not manually recopied or
guessed.
`aud` is a built-in audience claim. Validate it instead of adding it as an
optional claim. The approved manual runbook also
covers Broadly scoped ServiceNow scope
restriction, non-email custom user identifiers, and safe coexistence with a
separate Graph Connector app-only configuration.

Discover the current package inventory from the exact selected Agent's
authoritative component fetch. Treat a component as an ITSM topic only when it
is a `DialogComponent` with a dialog payload and its schema is under
`{exact IT agent schema}.topic.ServiceNowITSM...`. The discovered positive
inventory is the package inventory for this invocation; do not require a
fixed topic count or a checked-in list of expected topic names. New package
revisions and subsets are valid. Never include generic Agent topics, the HRSD
namespace, or non-topic components merely because a name contains
`ServiceNowITSM`.

The named `ServiceNowITSMSetupConfigurations` topic remains the exact portal
configuration target when that later operation runs. Its specific lookup does
not make it a blanket package-completeness requirement.

Secondary help references:

- [Draft PR #217](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/pull/217)
- [Microsoft Learn: ServiceNow for Employee Self-Service](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow)
- [ServiceNow connector actions](https://learn.microsoft.com/en-us/connectors/service-now/#actions)
- [ServiceNow connector known issues](https://learn.microsoft.com/en-us/connectors/service-now/#known-issues-and-limitations)

Use the invocation-local `SELECTED_AGENT_SLUG` and `SELECTED_AGENT_ID` supplied
by the ServiceNow DA chooser. Then read
`src/skills/connect/shared/lifecycle-runner.md` and follow it with:

```text
PROVIDER = "servicenow-da-itsm"
AGENT_SLUG = SELECTED_AGENT_SLUG
```

The shared runner's `connect_lifecycle.py next-step` command is mandatory.
Never jump directly from a result to another checkpoint or infer that
`actionApplied` skips an incomplete provider action.
Render the ServiceNow `resume-handoff.progress` checklist and current-step
updates exactly as the shared runner specifies; do not suppress them under
the ordinary Message-block silence rule.

The runner loads
`src/skills/connect/servicenow-da-itsm/contract.json`, persists state at
`.local/connect/servicenow-da-itsm/agents/{AGENT_SLUG}/lifecycle.json`, and
live-reverifies every phase. Agent binding and Test pane results remain
maker-confirmed evidence; topic mutation requires explicit confirmation.
Publishing is outside ServiceNow Connect. Parameter-sharing is not a
standalone lifecycle phase; legacy
evidence is retained only as historical state and never treated as proof that
the direct connector-action path was independently verified.

Only report the integration connected after the runner completes all eight
ITSM phases. The IT lifecycle intentionally omits the HR-only ServiceNow
plugin phase. Do not add a second completion message.

After that exact Dev lifecycle is complete with current passing Test evidence,
run `validation-realm-handoff`. Only then may the user choose Dev, Test, or
Prod validation. Test/Prod uses `validate-realm --realm <test|prod>` with the
administrator-confirmed target instance and client ID and is read-only: it
must prove the exact target environment and agent, report every
automated result honestly, and finish by directing the customer to that exact
agent's Test pane. It never promotes, imports, configures, sends a real-data
query, changes `activeAgent`, or publishes.
