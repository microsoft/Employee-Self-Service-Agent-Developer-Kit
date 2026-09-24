# Connect ServiceNow HRSD to a DA-GA HR Agent

This prototype uses the DA foundation handoff, MinimalBot Components, and the
Power Platform Connectivity API. It does not query Dataverse or activate cloud
flows. In the GA HR package, ServiceNow HRSD topics use direct connector
actions; the packaged flows are Workday-only.

## 1. Inspect

Run:

```text
python scripts/connect_servicenow_da.py inspect
```

If setup is not schema v4, has not established the environment, exact editable
Dev agent, and local workspace, or is not the HR agent, show the returned error
and stop. Do not require aggregate `connect_ready`: setup can report the
ServiceNow connection as not configured, and this workflow exists to resolve
that condition.

Summarize:

- ServiceNow topic count and active count.
- ServiceNow connector-action count.
- Physical connection count.
- Whether the currently referenced connection exists and is Connected.

Do not treat `/setup` `connect_ready: true` as integration readiness.

## 2. Guide the maker to create the physical connection

If exactly one matching Connected Entra user-login connection already exists,
reuse it. Otherwise run:

```powershell
python scripts\connect_servicenow_da.py create
```

This command is read-only. It derives the instance name and resource URI from
the installed ServiceNow connection-reference metadata and returns the exact
values plus these maker steps:

1. Open Copilot Studio and select the target environment.
2. Open the Employee Self-Service HR agent.
3. Select **Settings** -> **Connection settings**.
4. Find ServiceNow and select the status link.
5. Open the connection configuration and select **Create new connection**.
6. Choose **Microsoft Entra ID User Login**.
7. Enter the displayed **Instance Name** and **Resource URI**.
8. Select **Sign in**, complete authentication, and select **Submit**.
9. Wait for the status to become **Connected**, then return to VS Code.

Stop and wait for the maker to confirm completion. Do not request
`Connectivity.Connections.Write` and do not call a connection-create API.

After the maker confirms, rerun:

```powershell
python scripts\connect_servicenow_da.py inspect
```

If exactly one matching Connected Entra user-login connection is present, show
its connection ID and continue. If none exists, explain that the manual
connection is not Connected yet and repeat only the relevant UI step. If
multiple matches exist, show their display names and IDs and ask the maker
which one to bind.

## 3. Bind the DA connection reference

Only continue when the physical connection reports `Connected`. Show the
connection ID and the current reference ID, then ask for explicit confirmation.

After confirmation, run:

```text
python scripts/connect_servicenow_da.py bind --connection-id <id> --yes
```

The command fetches a fresh change token, sends one
`ConnectionReferenceUpdate`, refetches the components, and verifies the new
connection ID. It persists only non-secret before/after evidence under:

```text
.local/connect/servicenow/agents/<agent-id>/state.json
```

## 4. Maker-assisted OBO sharing

Guide the maker through Copilot Studio connection sharing and OBO
configuration. No supported automation API has been proven for this step.

## 5. Publish

Show the connection and reference changes. Publish only after explicit
confirmation:

```text
python scripts/connect_servicenow_da.py publish --yes
```

## 6. Test

Ask the maker to run one HRSD request in the Copilot Studio Test pane. Record
the prompt and pass/fail attestation in the connector-owned state. Do not claim
success from connection health alone.
