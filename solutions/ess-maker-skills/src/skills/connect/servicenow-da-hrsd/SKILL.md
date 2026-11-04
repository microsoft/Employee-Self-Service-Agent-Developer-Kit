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
(client) ID through source-faithful direct capture. `aud` may be
configured for audience validation but is never accepted as that selected
user-matching claim. The ServiceNow direct handoff uses the same bound values
and leaves only the actual matching `sys_user` field for the ServiceNow
administrator to confirm. Connect never guesses, defaults, or manually
recopies the claim.
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
**STOP — render before acting.** After every `resume-handoff` or `record-checkpoint-results`, your very next assistant message — before any other tool call — must contain `renderBlock.text` verbatim (the grouped phases view; it already ends with the current step line). `renderBlock.text` is the only renderable field: never render anything under `internal`, never write your own checklist, and never add a Check/Status table. Never summarize it or write "render the plan" instead.

**Hard rules.** Read `src/skills/connect/shared/lifecycle-runner.md` before the first action. When `resume-handoff` returns `renderBlock`, emit `renderBlock.text` verbatim as an assistant message; terminal output does not count. Never edit `lifecycle.json` by hand; record results with `record-checkpoint-results`. Run every command with the `/setup` launcher (`py -3`), never bare `python`.

Render the ServiceNow `resume-handoff.progress` checklist and current-step
updates exactly as the shared runner specifies; do not suppress them under
the ordinary Message-block silence rule.

On every first run and resume, show the controller's HR collaboration groups
and nested internal-step statuses as an ordinary response. Preflight and
instance input run without an availability question. When the controller
enters HR prerequisite, Entra identity, ServiceNow SSO/user mapping, or Maker
configuration, ask only that group's returned Yes/No question. A No answer
loops in that role and repeats the same question without advancing state. A
Yes acknowledgement applies only to that group. Availability never proves
authentication, authorization, permission, admin evidence, binding, mutation
consent, or Test completion.

The runner loads
`src/skills/connect/servicenow-da-hrsd/contract.json`, persists state at
`.local/connect/servicenow-da-hrsd/agents/{AGENT_SLUG}/lifecycle.json`, and
live-reverifies every phase. Agent binding and Test pane results remain
maker-confirmed evidence; topic mutation requires explicit confirmation.
Publishing is outside ServiceNow Connect. Parameter-sharing is not a
standalone lifecycle phase; legacy
evidence is retained only as historical state and never treated as proof that
the direct connector-action path was independently verified.

**Agent Binding:** The Maker binds the verified ServiceNow connection to the
selected ESS agent in Copilot Studio. FlightCheck checks the Maker’s
confirmation as Manual evidence. Connect does not enable ServiceNow topics
before binding is confirmed.

**Topics and Portal:** After binding is confirmed, Connect reads the topic
states for Maker review and saves only approved changes. It also saves the
administrator-provided portal URL after Maker confirmation. FlightCheck
verifies the resulting topic states and portal value.

**Dev Test:** After topic and portal configuration is complete, the Maker runs
the HRSD or ITSM scenario in the agent’s Test pane using authorized real data.
FlightCheck reviews the Maker’s reported result as Manual evidence for the
final configuration. In the final report word it as "Maker-reported Test pane
result"; administrator-supplied items as "Confirmed by the administrator" and
Maker-supplied items as "Confirmed by the Maker". Manual means human-verified,
never Passed, and never proof of business success; Passed means verified by
Connect checks.

Only report the integration connected after the runner completes all nine
phases, including explicit remote reuse approval and the four admin
prerequisite phases before the physical connection and topics. Do not add a
second completion message.
