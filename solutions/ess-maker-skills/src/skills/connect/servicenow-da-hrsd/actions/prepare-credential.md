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
  complete Microsoft Entra sign-in.

Run:

```text
python scripts/connect_servicenow_da.py inspect-admin-setup
```

Match candidates against the confirmed Instance Name and verified App A
Application client ID:

- Read `credentialResolution` from `inspect-admin-setup`.
- If exactly one candidate is healthy and exact, run
  `python scripts/connect_servicenow_da.py resolve-credential`. It performs a
  new connector-scoped read and records that connection only if the exact
  healthy match is still unique. Do not ask a completion question.
- If multiple exact healthy candidates match, use the bounded selector below.
  This is the only question for that path: do not show the
  **Completed / Not yet** repair/create question first. Do not create another
  connection and do not ask the Maker to copy an ID.
- If an exact candidate exists but is unhealthy, open that existing
  connection and use its `Repair`, `Fix connection`, or sign-in action to
  reauthenticate it. Refetch inventory and require `Connected` plus the exact
  auth mode, Instance Name, and Resource URI before recording it.
- Only when no exact candidate exists, continue to the new-connection handoff
  below.

A Connected row with the wrong Instance Name, Resource URI, or auth mode is
not reusable. Its existence also does not prove any Entra, plugin, OIDC, or
user-mapping phase complete.

When no exact candidate exists, run:

```text
python scripts/connect_servicenow_da.py create
```

Show the exact field table from the output:

- **Authentication Type:** Microsoft Entra ID User Login.
- **Instance Name:** normalized from the confirmed
  `https://<instance>.service-now.com` URL; never the full URL.
- **Resource URI:** the verified App A Application client ID; never
  `api://<client-id>`, the app object ID, or the connector application ID.

Use the ring-aware link returned by `inspect-admin-setup` as the primary
destination:

[Open connections for this environment]({POWER_AUTOMATE_CONNECTIONS_URL})

Use `links.powerAutomateConnections.url` from `inspect-admin-setup`.

If that page is unavailable, use the one alternate root:

[Open Power Apps]({POWER_APPS_URL})

Use `links.powerApps.url`; never substitute a production origin for a
non-production ring.

Then select the exact environment, open `Connections`, and choose
`New connection`.

Guide the Maker/Admin through Copilot Studio connection creation and Entra
sign-in. While the completion question is pending, do not return an action
result. If they are not finished, return `ACTION_RESULT = "waiting"`.

Microsoft Entra ID User Login connections are not shareable. This step proves
only the current Maker's physical connection; do not describe it as a
tenant-wide or shared credential.

If sign-in fails with `Invalid redirect_uri`, do not add another normal-flow
pause. As conditional remediation, copy the popup's `redirect_uri`, URL-decode
it, have the ServiceNow Admin update the OIDC Application Registry Redirect
URL to that exact value, and retry sign-in.

Ask one completion question for the entire physical connection step. The Maker
selects only **Completed** or **Not yet** after the row is Connected. Do not
ask the Maker for a connection display name, connection ID, GUID, or other
manual identifier. Do not add separate pauses for create or sign-in.

Use this exact visible handoff payload only when an exact connection needs
repair or no exact connection exists and a new connection is required. It
must never run for the multiple-healthy-candidate path. Render
`{CURRENT_PROGRESS}`, `{INSTANCE_NAME}`, `{APP_CLIENT_ID}`,
`{POWER_AUTOMATE_CONNECTIONS_URL}`, `{POWER_APPS_URL}`, and the exact candidate
summary. The question body must include both repair/new behavior and the
required field values:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "ServiceNow connection",
    "question": "{CURRENT_PROGRESS}\n\nPurpose: repair or create one exact healthy Connected Microsoft Entra ID User Login ServiceNow connection when automatic reuse is not currently possible.\n\nOwner: Power Platform Maker/Admin who can repair/create the connection and complete Entra sign-in.\n\nExpected values:\n- Authentication Type: Microsoft Entra ID User Login (`entraIDUserLogin`)\n- Instance Name: `{INSTANCE_NAME}` (name only, not the full URL)\n- Resource URI: `{APP_CLIENT_ID}` (the Application client ID, never `api://`, object ID, or connector app ID)\n\nCurrent exact candidates: {CONNECTION_CANDIDATE_SUMMARY}\n\nWhat to do:\n1. If an exact candidate is unhealthy, open it and use Repair, Fix connection, or sign-in; require Connected plus the exact auth mode, Instance Name, and Resource URI.\n2. Only if no exact candidate exists, open {POWER_AUTOMATE_CONNECTIONS_URL}; fallback {POWER_APPS_URL}; select the exact environment -> Connections -> New connection, enter the expected values, and complete Entra sign-in.\n3. If sign-in reports `Invalid redirect_uri`, URL-decode that exact URI, update the ServiceNow OIDC Application Registry redirect URL, and retry without adding another normal-flow pause.\n\nThis connection is not shareable and proves only the current maker's physical connection. Do not return secrets or connection identifiers.\n\nWhen the row shows Connected, choose Completed. The system will freshly discover the connection, verify the exact environment/auth/Instance Name/Resource URI, and record it automatically.",
    "options": [
      { "label": "Completed" },
      { "label": "Not yet" }
    ],
    "allowFreeformInput": false
  }
]
```

After **Completed**, run:

```text
python scripts/connect_servicenow_da.py resolve-credential
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

If the Maker selects **Not yet**, return `ACTION_RESULT = "waiting"` without
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
    "question": "{CURRENT_PROGRESS}\n\nFresh read-only inventory found multiple healthy exact ServiceNow connections in this environment. Each already uses Microsoft Entra ID User Login with the required Instance Name and Resource URI.\n\nChoose the connection to bind to this lifecycle. No new connection will be created.",
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
python scripts/connect_servicenow_da.py resolve-credential --selection-key <internal-selection-key>
```

This second command performs another fresh inventory read and records the
selection only if it is still an exact healthy candidate. If it changed,
report the error and re-enter the phase later with fresh discovery.

Physical credential creation and sign-in are maker actions. Do not call a
connection-create API or persist secrets. Return `ACTION_RESULT = "applied"`
only after a currently healthy credential is selected; otherwise return
`ACTION_RESULT = "waiting"`.
