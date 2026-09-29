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

- **Goal:** create or explicitly reuse one exact Connected
  `entraIDUserLogin` ServiceNow physical connection.
- **Owner role:** Power Platform Maker/Admin who can create the connection and
  complete Microsoft Entra sign-in.

Run:

```text
python scripts/connect_servicenow_da.py inspect-admin-setup
```

Show every discovered `entraIDUserLogin` candidate. Never auto-select or
auto-reuse an exactly-one result. Ask the Maker to choose an existing
connection or create a new one.

For a new connection, run:

```text
python scripts/connect_servicenow_da.py create
```

Show the exact field table from the output:

- **Authentication Type:** Microsoft Entra ID User Login.
- **Instance Name:** normalized from the confirmed
  `https://<instance>.service-now.com` URL; never the full URL.
- **Resource URI:** the verified App A Application client ID; never
  `api://<client-id>`, the app object ID, or the connector application ID.

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
