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

- If exactly one candidate is Connected and both values match, automatically
  reuse it and run `record-credential` with its connection ID. Do not ask the
  Maker to choose between reuse and creating another connection.
- If multiple exact healthy candidates match, ask the Maker to select only
  among those matches.
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
must return once with the non-secret connection display name and connection
ID after the row is Connected. Do not add separate pauses for create, sign-in,
or selection.

Use this exact visible handoff payload whenever maker input is required
(multiple exact candidates, repair, or new connection). Render
`{CURRENT_PROGRESS}`, `{INSTANCE_NAME}`, `{APP_CLIENT_ID}`,
`{POWER_AUTOMATE_CONNECTIONS_URL}`, `{POWER_APPS_URL}`, and the exact candidate
summary. The question body must include both reuse/repair/new behavior and the
required field values:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "ServiceNow connection",
    "question": "{CURRENT_PROGRESS}\n\nPurpose: reuse, repair, or create one exact healthy Connected Microsoft Entra ID User Login ServiceNow connection.\n\nOwner: Power Platform Maker/Admin who can create the connection and complete Entra sign-in.\n\nExpected values:\n- Authentication Type: Microsoft Entra ID User Login (`entraIDUserLogin`)\n- Instance Name: `{INSTANCE_NAME}` (name only, not the full URL)\n- Resource URI: `{APP_CLIENT_ID}` (the Application client ID, never `api://`, object ID, or connector app ID)\n\nCurrent exact candidates: {CONNECTION_CANDIDATE_SUMMARY}\n\nWhat to do:\n1. Reuse one exact Connected candidate automatically; if multiple exact healthy candidates exist, select only among those matches.\n2. If an exact candidate is unhealthy, open it and use Repair, Fix connection, or sign-in; then require Connected plus the exact auth mode, Instance Name, and Resource URI.\n3. Only if no exact candidate exists, open {POWER_AUTOMATE_CONNECTIONS_URL}; fallback {POWER_APPS_URL}; select the exact environment -> Connections -> New connection, enter the expected values, and complete Entra sign-in.\n4. If sign-in reports `Invalid redirect_uri`, URL-decode that exact URI, update the ServiceNow OIDC Application Registry redirect URL, and retry without adding another normal-flow pause.\n\nThis connection is not shareable and proves only the current maker's physical connection. Do not return secrets.\n\nAfter the row is Connected, provide the non-secret connection display name and connection ID. If it is not ready, answer `Not yet`.",
    "allowFreeformInput": true
  }
]
```

After that single return, run `inspect-admin-setup` again, match the returned
display name and connection ID, then run:

```text
python scripts/connect_servicenow_da.py record-credential --connection-id <id>
```

The command must use the connector-scoped read-only API and reject any
connection whose status, auth mode, Instance Name, or Resource URI differs
from the confirmed lifecycle values.

Physical credential creation and sign-in are maker actions. Do not call a
connection-create API or persist secrets. Return `ACTION_RESULT = "applied"`
only after a currently healthy credential is selected; otherwise return
`ACTION_RESULT = "waiting"`.
