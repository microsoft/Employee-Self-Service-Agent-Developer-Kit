# Design Decision: SN-RUN-001 ServiceNow Active Connector Probe

Status: AC13 live-capture spike complete (PROD), GO with one required selection fix
Decision: Active managed-connector probe mirroring WD-RUN-001, with passive run-history fallback
Date: 2026-08-11
Owner: ESS FlightCheck (Dawn Jeong)

## Why this matters

The passive SN-RUN-001 read (checks/servicenow.py:_check_servicenow_run_health) answers nothing when no ServiceNow flow has run recently, and even with data it only exposes the flow run status and Response-action name, never the real ServiceNow faultstring (that sits behind a SAS-signed outputsLink FlightCheck never fetches).

The active probe closes that gap: it stands up one throwaway Power Automate flow bound to the maker's existing managed ServiceNow connection, runs one read-only ServiceNow operation through the real managed connector (the AzureConnectors egress path the agent actually uses), reads the synchronous result, then deletes the flow. It mirrors the Workday WD-RUN-001 active probe. Only the ServiceNow connection binding and error map are ServiceNow-specific.

## AC13 live-capture spike (PROD, 2026-08-11)

Recorder: tests/captures/record_flightcheck_sn_connector_probe.py
Cassette: tests/fixtures/cassettes/flightcheck_sn_connector_probe.yaml (the committed happy-path 200 capture)
Environment: [PROD] - ESS + Workday + ServiceNow (BAP env c3446975-..., Dataverse prod1-ess.crm.dynamics.com)
Operator identity: lmoulet@EmployeeHub.onmicrosoft.com (the signed-in FlightCheck operator, and owner of 17 of the 27 ServiceNow connections in this env)

Three probe runs were executed:

1. Owned connection, valid read. Connection shared-service-now-c8f7acdd-... (owned by the operator), operation GetRecords (List Records), parameters {tableType: sys_user, sysparm_limit: 1}.
   Result: create 201 -> activate 200 -> invoke -> connector returns HTTP 200, action Succeeded, code OK -> delete 204, no orphan.
   ConnectorProbeResult: succeeded=True, status=Succeeded, http=200, code=OK, stage=done.
   The synchronous Response body was: connectorActionStatus="Succeeded", connectorStatusCode=200, connectorErrorMessage=null, connectorErrorCode="OK". No ServiceNow record body was returned.

2. Owned connection, invalid table. Same connection, GetRecords with parameters {tableType: zzz_nonexistent_table_flightcheck, sysparm_limit: 1}.
   Result: the connector ran and returned an error. ConnectorProbeResult: succeeded=False, status=Failed, http=400, code=BadRequest, stage=done.

3. Non-owned connection (earlier pass). Connection shared-service-now-7c7b258d-... (owned by a different user, Goutham S), auto-picked before the selection fix below.
   Result: create 201 -> activate 400 ConnectionAuthorizationFailed -> delete 204, no orphan. The flow never reached the connector.

## Open-question resolution

Q1 (exact read-only ServiceNow operation id): ANSWERED.
GetRecords (the connector "List Records" operation) with parameters {tableType: sys_user, sysparm_limit: 1} is a valid read-only call. It returned HTTP 200 from the production ServiceNow instance. This is the confirmed value for _SN_DEFAULT_READ_OPERATION. It is read-only (a GET, no ServiceNow write), returns at most one record, and that record body is not surfaced in the probe Response.

Q2 (ServiceNow faultstring granularity): ANSWERED, with a stated limit.
The connector surfaces distinct HTTP statuses per fault class: a valid read returns 200/OK, an invalid table (application-contract fault) returns 400/BadRequest. So the error map should key off the HTTP status and connector code, not collapse every failure into one bucket. The hard limit: the synchronous Response exposes only two signals, connectorStatusCode (the connector @outputs statusCode) and connectorErrorCode (the connector @actions code). The human-readable ServiceNow error.message resolves to null in the synchronous body (confirmed: connectorErrorMessage=null on both the 200 and the 400). The precise ServiceNow faultstring sits behind the SAS-signed outputsLink FlightCheck does not fetch. So the error map can name the layer from (HTTP status, connector code) but cannot quote the vendor faultstring. This matches the fidelity-honesty AC (AC4, AC10).

Q3 (whether a FlightCheck-authored transient flow can resolve the maker's connection under the running identity): ANSWERED. GO, conditional on connection ownership.
A transient flow bound to a ServiceNow connection by connection-id (Embedded source) activates and invokes the connector only when the /flightcheck operator owns that connection (or the owner has shared it in the flow context). Run 1 proves the GO path: as the connection owner, activation succeeded and the connector executed a real 200. Run 3 proves the failure mode: bound to a connection owned by a different user, activation fails with ConnectionAuthorizationFailed before the connector runs.

The earlier reading that Q3 was a general no-go was wrong. It was caused by the probe auto-picking the first Connected connection, which happened to be owned by a different user, not by an inherent platform block. The same ownership constraint applies to the Workday WD-RUN-001 active probe, whose positive capture ran as the connection owner.

## Deeper fault-capture pass (PROD, 2026-08-12)

The 2026-08-11 capture confirmed the two ends of the map (200 valid, 400 invalid table). A follow-up sweep pushed five read-only shapes through one operator-owned connection to characterize the fault granularity more precisely. Cassette: tests/fixtures/cassettes/flightcheck_sn_connector_probe_faults.yaml (recorder env ESS_SN_PROBE_SHAPES_JSON).

| Shape | Operation / params | Connector result |
| --- | --- | --- |
| Healthy read | GetRecords, {tableType: sys_user, sysparm_limit: 1} | 200 / OK |
| Invalid table | GetRecords, {tableType: <nonexistent>} | 400 / BadRequest |
| Restricted table | GetRecords, {tableType: sys_user_password} | 400 / BadRequest |
| Non-existent record | GetRecord, {tableType: sys_user, sysId: <all-zero GUID>} | 404 / NotFound |
| Empty required params | GetRecords, {} | fails at flow activate, before the connector runs |

Findings:

1. The connector does NOT collapse every failure into 400. HTTP 404 is reachable and distinct (non-existent record). The error map's separate 404 branch is therefore live-verified, not assumed. 404 alone cannot distinguish a not-found record from a not-found table, operation, or instance URL, so the cause names all of them.

2. ServiceNow table/row ACL denial does NOT surface as 403. Reading a restricted table returned 400 / BadRequest, the same status as an invalid table. So the 401/403 authorization branch in the error map is a connector-AUTH assumption (token/credential rejection), NOT how ServiceNow ACL denial actually appears. A restricted-table failure lands in the indeterminate 400 bucket, and the probe must not claim an authorization-layer diagnosis from a 400.

3. Empty required parameters fail at flow activate (the required connector parameter is missing from the flow definition), before any ServiceNow call, not as a connector 400. This is why the default probe always supplies _SN_DEFAULT_READ_PARAMS.

Layers still NOT live-verified (documented assumptions only): the no-response network split (DNS / TLS / firewall / DLP), 401/403 connector-auth, 429 throttle, and 500 backend error. None can be induced non-destructively against a healthy production tenant (they require breaking auth, a throttle storm, or a network/backend fault). The error map keeps honest named branches for them, marked as assumptions in the code comment, per the fidelity-honesty ACs (AC4, AC10).

## Required code change (selection fix)

_select_servicenow_probe_connection must prefer a Connected ServiceNow connection owned by the running operator identity, comparing the connection's createdBy.userPrincipalName to the operator UPN. Only an operator-owned (or operator-shared) connection can activate the transient flow. When no operator-owned Connected connection exists, the probe must fall back to the passive run-history read with a clear reason (operator does not own a ServiceNow connection in this environment), not attempt an activation that will deterministically fail with ConnectionAuthorizationFailed.

Ownership reality in the PROD env inventoried (read-only, 2026-08-11): of 27 ServiceNow connections, 17 Connected are owned by the operator (lmoulet), the rest by other makers (Goutham S, Arjit Agarwal, Tang) with several in Error state. So in this environment the operator-owned selection has ample valid targets; a naive first-Connected pick does not.

Two smaller data-fidelity notes:
- runtimeSource is empty on every BAP connection record across the envs checked, so AC9's service-account-vs-invoker distinction cannot be read from that field. The current code treats empty as the service-account path. The captured connection reported the service-account / integration-user path.
- The shared harness Response body still emits legacy workday*-named keys alongside the connector*-named keys. They are redundant and harmless (interpret_connector_probe_response reads the connector* keys), but a later harness cleanup could drop the vendor-named duplicates.

## Safety notes confirmed by this capture

- Read-only to ServiceNow: the successful call was a List Records GET returning at most one record, and the operation is drawn from a read-only allowlist. No ServiceNow write occurred.
- No ServiceNow record data in the cassette: the transient flow's synchronous Response returns only the connector action status, HTTP status code, and action code. The 200 response body carried no sys_user record fields.
- Self-cleaning: every run deleted its flow (204) even when activate failed (run 3). The post-run orphan scan returned empty each time. No orphan flow was left in the production environment.
- Cassette scrubbed: env host rewritten to a mock, GUIDs and the caller object id zeroed, SAS sig and bearer tokens replaced with REDACTED placeholders. Verified by hand before commit.

## Go / no-go

GO. The active ServiceNow connector probe is viable and validated end to end in production against an operator-owned connection: it exercises the real managed-connector egress path, returns a fresh pass/fail independent of run history, distinguishes fault classes by HTTP status, stays read-only, and self-cleans. The one required change before this ships is the operator-owned connection selection in _select_servicenow_probe_connection, with passive fallback when the operator owns no ServiceNow connection.
