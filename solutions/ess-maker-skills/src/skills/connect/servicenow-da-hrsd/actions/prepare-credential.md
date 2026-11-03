# Prepare the ServiceNow credential

Treat physical connection setup as one complete high-level step with one pause
boundary.

Read `adminSetup.phaseHandoffs.credential` first. If it is already
`completed` or `reused` and stored checkpoint results are empty or all in the
phase's `completionStatuses`, do not ask again; return
`ACTION_RESULT = "applied"` and let connector-scoped Direct A inventory
reverify the exact current connection. A prior result outside
`completionStatuses` requires one new complete physical-connection handoff.

## Goal and owner

- **Goal:** automatically reuse one exact healthy Connected
  `entraIDUserLogin` ServiceNow physical connection.
- **Owner role:** Power Platform Maker/Admin who can create the connection and
  complete Microsoft Entra sign-in with their own Microsoft account.

Run:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} inspect-admin-setup
```

Match candidates against the confirmed Instance Name and verified App A
Application client ID:

- Read `credentialResolution` from `inspect-admin-setup`.
- If exactly one candidate is healthy and exact, run
  `python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} resolve-credential`. It performs a
  new connector-scoped read and records that connection only if the exact
  healthy match is still unique. Do not ask a completion question.
- If multiple exact healthy candidates match, use the bounded selector below.
  This is the only question for that path: do not show the
  **Completed / Not yet** repair/create question first. Do not create another
  connection and do not ask the Maker to copy an ID.
- If an exact candidate exists but is unhealthy, open that existing
  connection and use its `Repair`, `Fix connection`, or sign-in action to
  reauthenticate it. Refetch inventory and require `Connected` plus the exact
  auth mode, Resource URI, and Instance Name before recording it.
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

Show the exact field table from the output:

- **Display name (optional):** `{CONNECTION_DISPLAY_NAME}`; guidance only and
  never a readiness gate.
- **Authentication Type:** Microsoft Entra ID User Login.
- **Resource URI:** the verified App A Application client ID; never
  an observed failed-connection value, `api://<client-id>`, the app object ID,
  or the connector application ID.
- **Instance Name:** normalized from the confirmed
  `https://<instance>.service-now.com` URL; never the full URL.

Use the ring-aware link returned by `inspect-admin-setup` as the primary
destination:

[Open connections for this environment]({POWER_AUTOMATE_CONNECTIONS_URL})

Use `links.powerAutomateConnections.url` from `inspect-admin-setup`.

If that page is unavailable, use the one alternate root:

[Open Power Apps]({POWER_APPS_URL})

Use `links.powerApps.url`; never substitute a production origin for a
non-production ring.

The repository has no verified direct connector-form or connection-detail URL.
The selected-environment Connections list is the safe fallback; the link does
not create, repair, sign in, submit, or prefill values. Then choose
`New connection`. In the connector picker, use the search box in the
upper-right to search for `ServiceNow`, then select the **ServiceNow**
connector published by **Microsoft** by choosing its `+` action. Choose
`Microsoft Entra ID User Login` only after selecting that connector, then enter
the exact Resource URI and Instance Name shown above and complete sign-in.

Guide the Maker/Admin through Copilot Studio connection creation and Entra
sign-in with their own Microsoft account. Never ask for or display a password,
client secret, access or refresh token, PFX, or browser/session artifact.
While the completion question is pending, do not return an action result. If
they are not finished, return `ACTION_RESULT = "waiting"`.

Microsoft Entra ID User Login connections are not shared across makers. The
same maker may reuse one exact healthy connection for the other ESS agent in
the same environment only after the consolidated shared-configuration
confirmation. This step proves the current maker's physical connection; it
does not prove another maker can use it and does not prove Entra/OIDC setup.

If sign-in reports `Invalid_redirect_uri`, treat this as conditional
remediation, not an observed current error. Copy the popup's `redirect_uri`,
URL-decode it, have the ServiceNow Admin update the OIDC Application Registry
Redirect URL to that exact value, and retry sign-in.

Ask one completion question for the entire physical connection step. The Maker
selects only **Completed, the exact ServiceNow connection is Connected** or
**Not yet, the ServiceNow connection is not ready**. Do not
ask the Maker for a connection display name, connection ID, GUID, or other
manual identifier. Do not add separate pauses for create or sign-in.

Use this exact visible handoff payload only when an exact connection needs
repair or no exact connection exists and a new connection is required. It
must never run for the multiple-healthy-candidate path. Render
`{CONNECTION_DISPLAY_NAME}`, `{INSTANCE_NAME}`, `{APP_CLIENT_ID}`,
`{POWER_AUTOMATE_CONNECTIONS_URL}`, `{POWER_APPS_URL}`, and the exact candidate
summary in the ordinary current-task reply. The native question carries only
the required match, current candidate context, and completion decision:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "ServiceNow connection",
    "question": "Required connection match:\n- Authentication Type: Microsoft Entra ID User Login (`entraIDUserLogin`)\n- Resource URI: `{APP_CLIENT_ID}`\n- Instance Name: `{INSTANCE_NAME}`\n\nCurrent exact candidates: {CONNECTION_CANDIDATE_SUMMARY}\n\nDoes the exact ServiceNow connection now show Connected with these required values?\n\nDisplay name `{CONNECTION_DISPLAY_NAME}` is optional guidance and is not a readiness gate. Selecting the completed option triggers one fresh supported connection inventory read; it does not prove agent binding or business success.",
    "options": [
      { "label": "Completed, the exact ServiceNow connection is Connected" },
      { "label": "Not yet, the ServiceNow connection is not ready" }
    ],
    "allowFreeformInput": false
  }
]
```

After **Completed, the exact ServiceNow connection is Connected**, run:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} resolve-credential
```

The command performs a fresh connector-scoped read:

- `selected`: exactly one healthy exact connection was programmatically
  verified and recorded; return `ACTION_RESULT = "applied"`.
- `choice-required`: more than one healthy exact connection exists. Use the
  selector below; do not create a duplicate and do not expose connection IDs.
- `not-ready`: show its explicit remediation, keep the phase incomplete, and
  return `ACTION_RESULT = "waiting"`. Do not record arbitrary fallback state.
- A command/read error is authoritative. Report it and stop; on HTTP 429,
  honor the cooldown/Retry-After and do not immediately retry the workflow.

If the Maker selects **Not yet, the ServiceNow connection is not ready**,
return `ACTION_RESULT = "waiting"` without
running completion or recording evidence.

For multiple healthy exact candidates discovered by the initial
`inspect-admin-setup`, build the supported selector options directly from
`credentialResolution.healthyExactCandidates`. If a post-Completed
`resolve-credential` unexpectedly returns `choice-required` because inventory
changed, use that command's returned candidates. In either case, each option
label is the returned bounded `label`, and the corresponding internal value is
its `selectionKey`. The Maker sees and selects only the non-secret label;
never ask them to copy the key or connection ID.

<!-- visible-handoff-question:v1-select-credential -->
```json
[
  {
    "header": "Choose ServiceNow connection",
    "question": "Fresh read-only inventory found multiple healthy exact ServiceNow connections in this environment. Each already uses Microsoft Entra ID User Login with the required Resource URI and Instance Name.\n\nChoose the connection to bind to this lifecycle. No new connection will be created.",
    "options": [
      { "label": "{CANDIDATE_LABEL_1}" },
      { "label": "{CANDIDATE_LABEL_2}" }
    ],
    "allowFreeformInput": false
  }
]
```

Replace the example options with exactly one option per returned candidate.
Map the selected label to its returned `selectionKey`, then run:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} resolve-credential --selection-key <internal-selection-key>
```

This second command performs another fresh inventory read and records the
selection only if it is still an exact healthy candidate. If it changed,
report the error and re-enter the phase later with fresh discovery.

Physical credential creation and sign-in are maker actions. Do not call a
connection-create API or persist secrets. Return `ACTION_RESULT = "applied"`
only after a currently healthy credential is selected; otherwise return
`ACTION_RESULT = "waiting"`.
