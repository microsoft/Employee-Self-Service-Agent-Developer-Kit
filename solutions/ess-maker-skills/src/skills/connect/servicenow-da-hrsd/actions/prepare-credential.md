# Create and connect ServiceNow

Treat connection creation and agent binding as one maker-visible step with one
pause boundary. The maker creates the connection from the agent's own
Copilot Studio Connection Settings, which also selects it for the agent. ADK
then verifies both facts in the background.

Read `adminSetup.phaseHandoffs.credential` first. If it is already
`completed` or `reused` and stored checkpoint results are empty or all in the
phase's `completionStatuses`, do not ask again; return
`ACTION_RESULT = "applied"` and let the merged connection and agent-binding
check reverify the exact current connection and the agent's saved binding. A
prior result outside `completionStatuses` requires one new complete handoff.

## Goal and owner

- **Goal:** one exact healthy Connected `entraIDUserLogin` ServiceNow
  connection that this agent's saved settings use.
- **Owner role:** ESS Maker / Agent Developer who can create the connection
  and complete Microsoft Entra sign-in with their own Microsoft account.

Run:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} inspect-admin-setup
```

Match candidates against the confirmed Instance Name and verified App A
Application client ID:

- Read `credentialResolution` from `inspect-admin-setup`.
- If exactly one candidate is healthy and exact, run
  `python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} resolve-credential`. It performs a
  new connector-scoped read, then reads the agent's saved draft connection
  reference. It records the step only if the healthy match is still unique
  and the saved draft uses that connection. Do not ask a completion question
  unless it returns a blocking issue.
- If multiple exact healthy candidates match, use the bounded selector below.
  This is the only question for that path. Do not create another connection
  and do not ask the Maker to copy an ID.
- If an exact candidate exists but is unhealthy, open that existing
  connection and use its `Repair`, `Fix connection`, or sign-in action to
  reauthenticate it. Then continue with the same completion question.
- If the current maker cannot repair an unhealthy candidate because another
  maker owns it, say so plainly. Do not impersonate the owner or request their
  credentials; create a separate exact connection only when the current maker
  is authorized to do so.
- Only when no exact candidate exists, continue to the new-connection handoff
  below.

A Connected row with the wrong auth mode, Resource URI, or Instance Name is
not reusable. Its existence also does not prove any Entra, plugin, OIDC, or
user-mapping phase complete.

When no exact candidate exists, run:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} create
```

Show the exact field values from the output in the ordinary current-task
reply (the controller builds the text; show it verbatim):

- **Authentication type:** Microsoft Entra ID User Login.
- **Resource URI:** the verified App A Application client ID; never
  an observed failed-connection value, `api://<client-id>`, the app object ID,
  or the connector application ID.
- **Instance name:** normalized from the confirmed
  `https://<instance>.service-now.com` URL; never the full URL.

The maker works in Copilot Studio: open the agent, go to **Settings >
Connection Settings > ServiceNow > Connect > Create new connection**, enter the
values above, and complete Microsoft Entra sign-in with their own account.
Creating the connection here also selects it for this agent. If Copilot Studio
is unavailable, the selected-environment Connections list in Power Apps is the
fallback for creating the connection; the maker must then select it in the
agent's Connection Settings and save.

Never ask for or display a password, client secret, access or refresh token,
PFX, or browser/session artifact. While the completion question is pending,
do not return an action result. If they are not finished, return
`ACTION_RESULT = "waiting"`.

Microsoft Entra ID User Login connections are not shared across makers. The
same maker may reuse one exact healthy connection for the other ESS agent in
the same environment only after the consolidated shared-configuration
confirmation. This step proves the current maker's connection and this agent's
binding; it does not prove another maker can use it and does not prove
Entra/OIDC setup.

If sign-in reports `Invalid_redirect_uri`, treat this as conditional
remediation, not an observed current error. Copy the popup's `redirect_uri`,
URL-decode it, have the ServiceNow Admin update the OIDC Application Registry
Redirect URL to that exact value, and retry sign-in.

Ask one completion question for the entire step. The Maker confirms that the
connection is created and shows Connected, and may name the connection (for
example, "I created Contoso ServiceNow. Copilot Studio shows Connected.").
Do not ask a second question about the agent's ServiceNow row, and do not ask
for a connection ID or GUID.

Use this exact visible handoff payload only when an exact connection needs
repair or no exact connection exists and a new connection is required. It
must never run for the multiple-healthy-candidate path. Render
`{CONNECTION_DISPLAY_NAME}`, `{INSTANCE_NAME}`, `{APP_CLIENT_ID}`, and the
exact candidate summary in the ordinary current-task reply. The reply starts
with a controller-built lead-in (it names the saved User Claim and User Field
only when both are recorded) and ends with a controller-built closing line;
show both verbatim. The closing line already asks the Maker to reply with the
connection they used, so send no separate question and no input or selection
component. The connection check below is plain chat text only; never a card or input
component. Its text is the controller's closing line (shown verbatim), which
already asks the Maker to reply with the connection they used. Send no separate
question and end your turn after it. For your own mapping, a reply that the
connection is created and shows Connected means completed; a reply that it is
not ready means not yet. The name is optional guidance and is not a readiness
gate.

After a reply that says the connection is created and shows Connected, run:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} resolve-credential
```

The command performs a fresh connector-scoped read and reads the agent's saved
draft connection reference:

- `selected`: exactly one healthy exact connection was verified, the saved
  draft uses it, and the step is recorded; return `ACTION_RESULT = "applied"`.
- `choice-required`: more than one healthy exact connection exists. Use the
  selector below; do not create a duplicate and do not expose connection IDs.
- `not-ready`: show its explicit remediation, keep the step incomplete, and
  return `ACTION_RESULT = "waiting"`. Do not record arbitrary fallback state.
- A blocking issue (error with `details.blockingIssue`) means the connection
  is fine but the agent does not use it yet. Show the error text verbatim,
  keep the step incomplete, and return `ACTION_RESULT = "waiting"`:
  - `agent-reference-missing`: the agent has no saved ServiceNow connection
    reference; ask the maker to open Connection Settings > ServiceNow, create
    or select the connection, and save.
  - `agent-not-bound`: select the connection in Connection Settings >
    ServiceNow and save the agent settings, then tell ADK again. The maker
    does not need to create the connection again.
  - `agent-bound-elsewhere`: the agent uses a different connection; select the
    verified one and save.
  - `agent-binding-mismatch`: the saved reference differs in authentication
    type, instance name, or Resource URI; re-select the verified connection and
    save.
- A command/read error is authoritative. Report it and stop; on HTTP 429,
  honor the cooldown/Retry-After and do not immediately retry the workflow.

If the Maker replies that the connection is not ready yet, return
`ACTION_RESULT = "waiting"` without running completion or recording evidence.

For multiple healthy exact candidates discovered by the initial
`inspect-admin-setup`, build the supported choices directly from
`credentialResolution.healthyExactCandidates`. If a post-Completed
`resolve-credential` unexpectedly returns `choice-required` because inventory
changed, use that command's returned candidates. In either case, each choice
label is the returned bounded `label`, and the corresponding internal value is
its `selectionKey`. The Maker sees and replies with only the non-secret label
or its number; never ask them to copy the key or connection ID. Pass the
question below to `adapt-question` on stdin, send the returned `plainText` as
ordinary chat text (never `ask_user`), and map the typed reply with
`match-reply`.

<!-- plain-chat-question:v1-select-credential -->
**Message:**

Fresh read-only inventory found multiple healthy exact ServiceNow connections in this environment. Each already uses Microsoft Entra ID User Login with the required Resource URI and Instance Name.

Choose the connection to use for this agent. No new connection will be created. Make sure this agent's Connection Settings use the same connection.

1. {CANDIDATE_LABEL_1}
2. {CANDIDATE_LABEL_2}

Reply with the number or the name of the connection.

**End message.**

Replace the example choices with exactly one numbered line per returned
candidate, then end your turn.
Map the selected label to its returned `selectionKey`, then run:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} resolve-credential --selection-key <internal-selection-key>
```

This second command performs another fresh inventory read and saved-draft
check, and records the selection only if it is still an exact healthy
candidate that the agent uses. If it changed, report the error and re-enter
the phase later with fresh discovery.

Do not call the UI `user-connections` endpoint, reuse browser tokens, or use a
MinimalBot connection-reference update as a substitute. Connection creation and
sign-in are maker actions. Do not call a connection-create API or persist
secrets. Return `ACTION_RESULT = "applied"` only after a currently healthy
connection is verified and the agent's saved settings use it; otherwise return
`ACTION_RESULT = "waiting"`.

The recorded binding identity covers the exact provider, profile, agent,
environment, selected connection, and ServiceNow connection-reference
metadata. Later approved topic-state or same-instance portal changes do not
require re-binding. A changed agent, environment, connection, auth/resource/
instance metadata, or connection reference does.
