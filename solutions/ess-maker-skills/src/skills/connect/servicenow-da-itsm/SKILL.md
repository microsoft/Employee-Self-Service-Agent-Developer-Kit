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
the retired ServiceNow setup capture guide with the explicit
condition `scope.hrsd == true`; the older reference update `f3bdf293` records
that `com.sn_hr_core` supplies `sn_hr_core_case` and other HRSD tables.
Together these support omitting that HRSD data prerequisite from this
IT-only lifecycle. They do not prove that every current ITSM/OIDC instance
needs no ServiceNow plugin or capability; the OIDC phase still stops when the
tenant lacks the required OIDC capability.

The current authenticated review-site revision was not freshly fetched; do
not invent additional requirements from the review URL. For Entra access tokens, do not assume UPN or email. The Entra administrator
returns exactly one selected employee-identity claim name plus the Application
(client) ID through source-faithful direct capture. `aud` may be
configured for audience validation but is never accepted as that selected
user-matching claim. The ServiceNow direct handoff uses the same bound values
and leaves only the actual matching `sys_user` field for the ServiceNow
administrator to confirm. Connect never guesses, defaults, or manually
recopies the claim.
The approved manual runbook also
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
**Progress snapshot, then conversation text.** After every `resume-handoff` or `record-checkpoint-results`, your very next assistant messages — before any other tool call — are: first `renderBlock.progressSnapshot` verbatim as its own short chat message when it is non-empty (ordinary Markdown progress list like `/setup`'s: ✅ done, 🔄 current, ⛔ needs attention, ⬜ not started; nothing is pinned, so re-post the fresh snapshot at the start, after each phase change, on resume, when waiting or blocked, and at completion), then `renderBlock.text` verbatim when it is non-empty (the conversation text for the current step). `SHOW_PHASE_CHECKLIST = False` in `scripts/connect_servicenow_da.py` hides the snapshot, so both may be empty; then send nothing for them. Never render anything under `internal`, never edit or rebuild the snapshot, never write your own checklist or phase list, never add a Check/Status table, and never use a card or input for it. At the start of a fresh run `renderBlock.text` begins with the connection opening ("We'll connect ... so employees can ..."); emit it verbatim as part of the same message, and never write your own opening or repeat it later. The Test-pane ready message in the current-task lead-in is controller-built: show it verbatim and never reword it, and when `record-test --result untested` or `--result empty` returns `message`, show that `message` verbatim (for `empty`, nothing is recorded and the Test step stays open; ask the result question again) and never claim the integration works.

**Ask in plain chat text.** Every question is ordinary chat text: never call `ask_user` or show an input, selection or confirm card. Send the controller's `plainText`, wait for the typed reply, map it with `match-reply`, and run the same command as before (see `shared/lifecycle-runner.md`). Accept free-form replies such as "yes", "1" or a pasted value. Never ask for a secret.

**Hard rules.** Read `src/skills/connect/shared/lifecycle-runner.md` before the first action. When `resume-handoff` returns a non-empty `renderBlock`, emit `renderBlock.progressSnapshot` (when non-empty) as its own short chat message, then `renderBlock.text` verbatim as an assistant message; terminal output does not count. Never edit `lifecycle.json` by hand; record results with `record-checkpoint-results`. Run every command with the launcher resolved by `/setup` (`py -3`, `python3`, then `python`), never assuming bare `python`.

Keep the ServiceNow `resume-handoff.progress` items and current-step state
as agent-facing data for resume and routing; the only maker-visible progress
list is the controller's `renderBlock.progressSnapshot`, never one you write.

On every first run and resume, track the controller's IT collaboration groups
and nested internal-step statuses internally. Preflight and
instance input run without an availability question. When the controller
enters Entra identity, ServiceNow SSO/user mapping, or Maker configuration,
ask only that group's returned Yes/No question as plain chat text. A No answer loops in that role
and repeats the same question without advancing state. A Yes acknowledgement
applies only to that group. Availability never proves authentication,
authorization, permission, admin evidence, binding, mutation consent, or Test
completion.

The runner loads
`src/skills/connect/servicenow-da-itsm/contract.json`, persists state at
`.local/connect/servicenow-da-itsm/agents/{AGENT_SLUG}/lifecycle.json`, and
live-reverifies every phase. The connection and the agent's saved binding are
verified together by ADK; Test pane results remain maker-confirmed evidence; topic mutation requires explicit confirmation.
Publishing is outside ServiceNow Connect. Parameter-sharing is not a
standalone lifecycle phase; legacy
evidence is retained only as historical state and never treated as proof that
the direct connector-action path was independently verified.

**Create and connect ServiceNow:** The Maker creates the ServiceNow connection from
the agent's Copilot Studio Connection Settings, which also selects it for the
agent, then confirms it shows Connected. FlightCheck verifies one exact healthy
connection and that the agent's saved draft uses it in a single check. Connect
does not enable ServiceNow topics before this check passes.

**Topics and Portal:** After the connection check passes, Connect reads the topic
states for Maker review and saves only approved changes. It also saves the
administrator-provided portal URL after Maker confirmation. The confirmation
question comes from `portal-url-confirmation`: send its `plainText` (the
question and its Yes/No reply guidance) verbatim as chat text, and save nothing
before the Maker replies Yes. FlightCheck
verifies the resulting topic states and portal value.

**Dev Test:** After topic and portal configuration is complete, the Maker runs
the HRSD or ITSM scenario in the agent’s Test pane using authorized real data.
FlightCheck reviews the Maker’s reported result as Manual evidence for the
final configuration. In the final report word it as "Maker-reported Test pane
result"; administrator-supplied items as "Confirmed by the administrator" and
Maker-supplied items as "Confirmed by the Maker". Manual means human-verified,
never Passed, and never proof of business success; Passed means verified by
Connect checks.

**Later realms:** A promoted agent in a later realm is checked on its own by
`src/skills/connect/servicenow/realms.md`; it does not depend on this
lifecycle.

Only report the integration connected after the runner completes all eight
ITSM phases. The IT lifecycle intentionally omits the HR-only ServiceNow
plugin phase. Do not add a second completion message.
