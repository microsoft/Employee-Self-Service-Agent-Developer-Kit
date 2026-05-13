# Cassette index — confirmed real endpoints

Every cassette in this directory is a redacted recording of one real
session against a live Microsoft / Workday / ServiceNow tenant. The
cassettes are the ground truth for what the production APIs actually
return. Mock builders in `tests/mocks/` are derived from these cassettes;
when a builder and a cassette disagree, the cassette wins.

If you (human or agent) need to know whether a given endpoint is
confirmed real, look it up in the table below. If it is not in the
table, it is not confirmed — see `tests/AGENTS.md` for what to do next.

When you add a new cassette, add a row to this table covering every
endpoint it captures.

---

## Confirmed endpoints

| Service | Method + URL pattern | Status seen | Cassette |
|---|---|---|---|
| Dataverse Web API v9.2 | `GET /api/data/v9.2/WhoAmI()` | 200 | `dataverse_whoami.yaml` |
| Microsoft Graph v1.0 | `GET /v1.0/organization` | 200 | `flightcheck_graph.yaml` |
| Microsoft Graph v1.0 | `GET /v1.0/users?$top=10` | 200 | `flightcheck_graph.yaml` |
| Microsoft Graph v1.0 | `GET /v1.0/directoryRoles` | 200 | `flightcheck_graph.yaml` |
| Microsoft Graph v1.0 | `GET /v1.0/identity/conditionalAccess/policies` | 200 | `flightcheck_graph.yaml` |
| Power Platform Admin (BAP) | `GET /providers/Microsoft.BusinessAppPlatform/scopes/admin/environments` | 200 | `flightcheck_pp_admin.yaml` |
| Power Platform Admin (BAP) | `GET /providers/Microsoft.BusinessAppPlatform/scopes/admin/environments/{env_id}` | 200 | `flightcheck_pp_admin.yaml` |
| Power Platform Admin (BAP) | `GET /providers/Microsoft.BusinessAppPlatform/scopes/admin/apiPolicies` | 200 | `flightcheck_pp_admin.yaml` |
| PowerApps | `GET /providers/Microsoft.ProcessSimple/scopes/admin/environments/{env_id}/v2/flows` | **404** (Dataverse-only env) | `flightcheck_pp_admin.yaml` |
| PowerApps | `GET /providers/Microsoft.PowerApps/scopes/admin/environments/{env_id}/connections` | 200 | `flightcheck_pp_admin.yaml` |
| Workday OAuth2 | `POST /ccx/oauth2/{tenant}/token` (refresh_token grant via Basic auth) | 200 | `workday_wql_admin.yaml` |
| Workday WQL | `GET /ccx/api/wql/v1/{tenant}/dataSources?limit=100&offset=N` (paginated catalog of all data sources) | 200 | `workday_wql_admin.yaml` |
| Workday WQL | `GET /ccx/api/wql/v1/{tenant}/dataSources/{wid}` (data source detail incl. `requiredParameters`, `dataSourceFilters`, `filterIsRequired`) | 200 | `workday_wql_admin.yaml` |
| Workday WQL | `GET /ccx/api/wql/v1/{tenant}/dataSources/{wid}/fields?limit=50` (field metadata) | 200 | `workday_wql_admin.yaml` |
| Workday WQL | `POST /ccx/api/wql/v1/{tenant}/data` (`SELECT … FROM allWorkers LIMIT 5`) | 200 | `workday_wql_admin.yaml` |
| Workday WQL | `POST /ccx/api/wql/v1/{tenant}/data` (`SELECT … FROM oAuth20RefreshTokenDataSource LIMIT 5`) | 200 | `workday_wql_admin.yaml` |
| Workday WQL | `POST /ccx/api/wql/v1/{tenant}/data` (`SELECT … FROM publicWebServices LIMIT 5`) | 200 | `workday_wql_admin.yaml` |
| Workday WQL | `POST /ccx/api/wql/v1/{tenant}/data` (`SELECT … FROM allSecurityGroups LIMIT 5`) | 200 | `workday_wql_admin.yaml` |
| Workday WQL | `POST /ccx/api/wql/v1/{tenant}/data` (`SELECT … FROM allCustomReports LIMIT 5`) | 200 | `workday_wql_admin.yaml` |
| Workday WQL | `POST /ccx/api/wql/v1/{tenant}/data` (`SELECT … FROM allIntegrationSystemsAudited LIMIT 5`) | 200 | `workday_wql_admin.yaml` |
| Microsoft Entra (token) | `POST /{tenant}/oauth2/v2.0/token` (device-code flow against PVA Service audience `96ff4394-9197-43aa-b393-6a41652e21f8`) | 200 | `island_gateway_botcomponents.yaml` |
| PVA Island Gateway | `GET /api/botmanagement/v1/environments/{env}/bots` (snapshot list of all agents in environment) | 200 | `island_gateway_botcomponents.yaml` |
| PVA Island Gateway | `POST /api/botmanagement/v1/environments/{env}/bots/{bot}/content/botcomponents` body `{"componentDeltaToken":""}` (full bot-component sync — empty token returns ALL components, not just deltas) | 200 | `island_gateway_botcomponents.yaml` |
| ServiceNow Table API | `GET /api/now/table/oauth_entity?sysparm_query=type=external_client` (Knowledge Connector OAuth registry — Task 1 of MS Learn doc) | 200 (empty result if not configured) | `flightcheck_servicenow.yaml` |
| ServiceNow Table API | `GET /api/now/table/sys_user?sysparm_query=active=true&sysparm_fields=user_name,name,active,roles` (service account discovery) | 200 | `flightcheck_servicenow.yaml` |
| ServiceNow Table API | `GET /api/now/table/kb_knowledge?sysparm_limit=1` (Knowledge connector required permission probe — knowledge articles) | 200 | `flightcheck_servicenow.yaml` |
| ServiceNow Table API | `GET /api/now/table/user_criteria?sysparm_limit=1` (THE critical permissions probe — most-cited setup gotcha) | 200 | `flightcheck_servicenow.yaml` |
| ServiceNow Table API | `GET /api/now/table/sys_user_group?sysparm_limit=1` (group references in user_criteria) | 200 | `flightcheck_servicenow.yaml` |
| ServiceNow Table API | `GET /api/now/table/sys_user_role?sysparm_limit=1` (role references in user_criteria) | 200 | `flightcheck_servicenow.yaml` |
| ServiceNow Table API | `GET /api/now/table/sys_security_acl?sysparm_query=type=REST_Endpoint` (Task 2 — Advanced Scripts ACL) | 200 | `flightcheck_servicenow.yaml` |
| ServiceNow Table API | `GET /api/now/table/sys_ws_definition?sysparm_query=active=true` (Task 3 — Scripted REST APIs) | 200 | `flightcheck_servicenow.yaml` |
| ServiceNow Table API | `GET /api/now/table/sys_ws_operation?sysparm_query=relative_path=/user_criteria` (Task 4 — `/user_criteria` API resource) | 200 | `flightcheck_servicenow.yaml` |
| ServiceNow Table API | `GET /api/now/table/oauth_entity` with bad-password Basic auth (negative path) | **401** | `flightcheck_servicenow.yaml` |

The 404 row above is intentional — it captures the response shape the
kit hits when an environment exists in BAP but not in PowerApps
ProcessSimple (a Dataverse-only env). See bug 4 in
`tests/flightcheck/test_pp_admin_client.py`.

### Workday WQL config-validation pattern (`workday_wql_admin.yaml`)

This cassette is the foundation for any future FlightCheck check that
validates Workday tenant configuration via WQL (Workday Query Language).
The recorder discovers data sources by name from the live tenant catalog,
fetches their field schema, and runs real SELECT queries with real
fields — so the captured shapes are exactly what a check would consume.

| WQL data source | Validates |
|---|---|
| `allWorkers` | API client has basic Worker access — sanity check that auth + scope are wired correctly |
| `oAuth20RefreshTokenDataSource` | Task 5: API Client is registered AND has at least one usable refresh token. Workday does NOT expose an "API Clients" table directly; this is the canonical proxy. |
| `publicWebServices` | Task 5 (scope half): `Workday Query Language` appears in the list of services exposed to this API client — i.e. the API client has the WQL functional area in its scope |
| `allSecurityGroups` | Legacy Task 3 ISSG validation — filter to `ISSG_*_COPILOT` to confirm groups exist |
| `allCustomReports` | Legacy Task 8 RaaS report validation — filter to `WD_User_Context` to confirm report exists |
| `allIntegrationSystemsAudited` | Legacy Task 3 ISU validation (indirect, via integration audit metadata) AND a proxy for "Auth Policy is letting the ISU sign on" — if `asOfEntryDateTimeOfLastCompletedIntegrationEvent` is recent, the ISU is authenticating |

**Known gap — `allSystemAccountSignons` not captured.** This data source
has `filterIsRequired: true` and exposes `requiredParameters` (`fromMoment`,
`toMoment`) plus 4 named `dataSourceFilters`. We could not determine the
correct WQL syntax to invoke a filter from the `/data` REST endpoint
through experimentation alone — function-call FROM, qualified names, URL
params, and body wrappers all returned 400 with various errors. The
recorder still captures the data source's full discovery metadata so a
future agent with access to Workday's WQL REST API reference docs can
fill in the syntax. For "is the ISU authenticating?" today, use
`allIntegrationSystemsAudited` instead — it shows audit metadata for
every integration the ISU has executed, which is a sufficient proxy.

**KNOWN BLOCKER — chicken-and-egg auth problem (do not build a WQL FlightCheck
on this cassette without solving this first).**

The cassette captures the API surface, but **a runtime FlightCheck check
cannot consume it without first solving an auth bootstrap problem that
mirrors the very setup the check would validate.** Detail:

  - Workday's REST/WQL endpoints accept ONLY OAuth 2.0 Bearer tokens. There
    is no Basic auth, no session cookie, no "log in as the admin user"
    path. OAuth requires an API Client registered in Workday.
  - To validate "the customer's ESS API Client is registered correctly via
    WQL," FlightCheck itself needs its own OAuth API Client registered in
    the same Workday tenant.
  - That registration (Workday tasks: "Register API Client for Integrations"
    + functional area scope + "Manage Refresh Tokens for Integrations") is
    nearly the same workflow as the ESS Workday integration setup the
    check is supposed to verify.
  - Net effect: shipping a WQL-based FlightCheck check would push the
    setup-pain problem one level deeper, not solve it. A customer who
    can't (or won't) complete the ESS Workday setup probably also can't
    (or won't) complete the FlightCheck OAuth setup.

  Workarounds considered and their tradeoffs:

  1. **`authorization_code` + PKCE flow** (FlightCheck opens a browser
     to Workday's login page). Removes the painful "Manage Refresh Tokens"
     bootstrap step but STILL requires registering an OAuth API Client
     with FlightCheck's redirect URI. Doesn't escape the chicken-and-egg.
  2. **Piggyback on the API Client the ESS Workday extension pack
     already registers**, with Microsoft adding FlightCheck's redirect
     URI to the existing registration. Closest to "zero customer setup"
     but requires a Microsoft-side change and only works AFTER the ESS
     extension is installed (so the check can't validate "is ESS
     installed" — it only works once it is).
  3. **SOAP with WS-Security UsernameToken** (admin user/password
     directly into a SOAP envelope). NO API Client registration needed.
     But Workday admin operations like `Get_API_Clients` and
     `Get_Authentication_Policies` were NOT in the publicly-exposed SOAP
     service list per a 2026-05 capture attempt. May not be reachable
     from outside the Workday UI.
  4. **Drop Workday config validation entirely** and check only what's
     visible from outside Workday (Power Platform connection refs, env
     vars — what `WD-CONN-001` and `WD-ENV-001` already do).

  **Decision (2026-05): pause on building any WQL-backed FlightCheck check.**
  The cassette stays committed because it's still valuable as discovery
  evidence (proves the WQL admin surface exists, captures the response
  shapes for 6 useful data sources, documents the `dataSourceFilters` /
  `requiredParameters` mechanism). It's just not the foundation for a
  runtime check until one of the above tradeoffs is resolved.

### PVA Island Gateway config-validation pattern (`island_gateway_botcomponents.yaml`)

This cassette captures the Power Virtual Agents / Copilot Studio
"Island Gateway" REST API — the backend the Copilot Studio web editor
calls to manage bot components. It backs future "is the agent
provisioned and healthy" checks (e.g. CONFIG-013 knowledge source crawl
status) and any check that needs to inspect the customer's installed
topics, knowledge sources, env vars, or generative-AI configuration.

| Endpoint | Returns |
|---|---|
| `GET /bots` | List of all agents in the environment with `aadTenantId`, `cdsBotId`, `name`, `region`, `language`, `lastPublishedVersion`, `isManaged`, `provisioningStatus`. Use to validate the ESS agent is published and managed correctly. |
| `POST /bots/{bot}/content/botcomponents` (empty deltaToken) | Full snapshot of all bot components. This recording captured 30 components in a representative ESS agent, broken down as: 15 GlobalVariableComponent, 13 DialogComponent (topics), 1 GptComponent (orchestrator), 1 KnowledgeSourceComponent. Each component is wrapped in a `BotComponentInsert` envelope with the real type on `component.$kind`. Also returns 14 environment variable changes. |

**Auth pattern**: the recorder uses MSAL device-code flow against the
PVA Service first-party app `96ff4394-9197-43aa-b393-6a41652e21f8`
with the Azure CLI public client (no service principal needed). Token
caches to `~/.copilot/island-gateway-msal-cache.bin` between runs.

**Region suffix**: the gateway hostname is region-prefixed
(`powervamg.{region}.gateway.prod.island.powerapps.com`). This
recording was made against `us-il107`. Different tenants are routed
to different regions — a customer can find theirs by inspecting any
PVA portal network call (`Network` tab, look for `gateway.prod.island.powerapps.com`).

**Known scrubber gap — bot display names**: the global redactor scrubs
GUIDs, emails, and many JSON keys (`displayName`, `descriptor`, etc.)
but NOT the JSON key `name`, because `name` is too common (Graph
directoryRoles, Power Platform environment IDs, etc. all use `name`
for non-PII values). The `/bots` list response uses `name` for the
customer-chosen agent display name, so after recording **eyeball the
cassette for any `"name":"<your bot>"` strings** and scrub them by
hand. This recording's `Test_Hr_0212` and `Test IT_0212` were scrubbed
to `MockBot_HR` / `MockBot_IT`.

## Endpoints we'd like cassettes for

### ServiceNow Knowledge Connector setup-validation pattern (`flightcheck_servicenow.yaml`)

This cassette captures the API surface a future FlightCheck check would
consume to validate that a customer's ServiceNow instance is configured
per the [ServiceNow Knowledge connector setup doc](https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/servicenow).

**Important — not the same as ServiceNow HRSD/ITSM ticket flows.** ESS
has two distinct ServiceNow integrations:

| Integration | What it does | Tables |
|---|---|---|
| **ServiceNow Knowledge** (this cassette) | Indexes ServiceNow KB articles into M365 Copilot Search via the M365 Copilot Connector | `oauth_entity`, `kb_knowledge`, `user_criteria`, `sys_user_group`, `sys_user_role`, `sys_security_acl`, `sys_ws_definition`, `sys_ws_operation` |
| **ServiceNow HRSD/ITSM** (separate cassette, not yet captured) | Creates/updates tickets, looks up CMDB via Power Platform connector + topics + flows | `incident`, `sn_hr_core_case`, `sc_cat_item`, `cmdb_ci`, `interaction` |

**What each call validates** (mapped to the doc's task numbers):

| Doc step | Validates | Captured shape |
|---|---|---|
| Task 1 — OAuth Application Registry | OAuth client exists, active, callback URL is `https://gcs.office.com/v1.0/admin/oauth/callback` (commercial) or GCC equivalent, sensible token lifetimes | This recording captured ZERO records → "not configured" empty-result shape. A check would FAIL. Re-record with the registry installed for the success-shape. |
| Service account exists | Crawling account from doc Task 1 is active, has the right roles | List of active users with role hints |
| Critical: kb_knowledge read | The crawling account can read knowledge articles | 200 with article record |
| **Critical: user_criteria read** | The single most-cited setup failure per the doc — without this, restricted articles silently disappear from M365 Copilot results | 200 with criteria record |
| Critical: sys_user_group / sys_user_role | The crawling account can resolve groups/roles referenced in user_criteria records | 200 with example records |
| Task 2 — REST_Endpoint ACL | Only required if Advanced Scripts in use. ACL restricts custom scripted endpoint to crawling account | 200 with list of REST_Endpoint ACLs |
| Task 3 — Scripted REST APIs | Custom REST API exists for user_criteria advanced lookup | 200 with list of active scripted APIs |
| Task 4 — `/user_criteria` resource | The specific resource on the scripted REST API exists with correct relative path | 200 with the matching resource |
| Negative — bad password | 401 shape so a check can assert the opposite of "auth works" | 401 |

**Eyeball / scrub gap — ServiceNow user_name fields:**
The global redactor scrubs GUIDs, emails, and dev instance hostnames
(`devNNNNN.service-now.com` → `devmocktenant.service-now.com`). It does
NOT know about ServiceNow's `user_name` or `name` fields, which can
contain real user accounts that were added to the dev instance. After
recording, eyeball the cassette for any real-person user names and scrub
them by hand. This recording's `ankurrana` (the dev instance owner) was
scrubbed to `mock.user.001`, and the well-known ServiceNow demo accounts
(`abel.tuter`, `abel.phelps`, `abraham.lincoln`, `alopez`) were scrubbed
to `mock.user.002`–`005` for consistency even though they're public
demo data.

**Open follow-up:**
- Capture the success-shape for Task 1 by setting up an OAuth registry on the dev instance with the Microsoft 365 Copilot callback URL, then re-record. Today's cassette has the empty-result shape.
- Capture the 403 shape on `user_criteria` by creating a limited-access user on the dev instance and setting `SERVICENOW_LIMITED_USERNAME` / `SERVICENOW_LIMITED_PASSWORD` before re-running. The recorder already supports this; just needs a second account.
- Microsoft-side validation (the Microsoft 365 Admin Center "Search & intelligence → Data sources" page where the connector itself is registered) is on a different API surface (Microsoft Graph) and would need its own cassette — see the existing `flightcheck_graph.yaml` for a starting point.

These are not yet captured. If you need to write a check that consumes
one of these, capture the cassette first and move it to the table above.

### Runtime data path (what topics call to fetch employee data)

| Service | Method + URL pattern | Why we'd want it | Recording wrapper |
|---|---|---|---|
| Workday SOAP | `POST /ccx/service/{tenant}/Human_Resources/v40.0` (Get_Workers) | All 17 ESS workflow checks under WD-WF-* | `tests/captures/record_flightcheck_workday.py` |
| Workday SOAP | Same, with invalid Worker_Reference | Pin SOAP fault response shape for negative-path tests | extend `record_flightcheck_workday.py` |
| Workday SOAP | `POST /ccx/service/{tenant}/Absence_Management/v40.0` | Time-off / absence checks | extend `record_flightcheck_workday.py` |
| Workday SOAP | `POST /ccx/service/{tenant}/Compensation/v40.0` | Compensation checks (existing wrapper sends Get_Workers there which is invalid for that service — needs custom body) | extend `record_flightcheck_workday.py` |
| ServiceNow REST | `GET /api/now/table/incident?sysparm_limit=5` | Future ServiceNow checks; also validates the kit's MCP server client | new wrapper `tests/captures/record_flightcheck_servicenow.py` |
| ServiceNow REST | `GET /api/now/table/sn_hr_core_case?sysparm_limit=5` | HR case checks | same |

### Configuration validation path (what FlightCheck would call to verify the customer set things up correctly)

These cover the steps in the [Workday integration docs](https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/workday-simplified-setup)
and the [legacy Workday docs](https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/workday).
Future FlightCheck checks based on these would verify the customer's
configuration matches what the docs prescribe — e.g. "ISU users exist",
"API client has the right scopes", "auth policy includes SAML".

Most Workday config-validation checks now have a working **WQL alternative**
captured in `workday_wql_admin.yaml` (see the "WQL config-validation
pattern" section above). The SOAP rows below remain useful for checks
where SOAP exposes config detail that WQL does not (e.g.
`Get_Domain_Security_Policies` — domain-level permissions are not
modeled as a WQL data source). When WQL covers a use case, prefer it:
one auth flow, one cassette, simpler request shape.

| Service | Method + URL pattern | Validates which doc step | Recording wrapper |
|---|---|---|---|
| Workday SOAP | `POST /ccx/service/{tenant}/Identity_Management/v40.0` (Get_API_Clients) | Simplified Task 4 + Legacy Task 5: API client registered with right scopes | `tests/captures/record_workday_config.py` |
| Workday SOAP | `POST /ccx/service/{tenant}/Identity_Management/v40.0` (Get_Authentication_Policies) | Simplified Task 3 + Legacy Task 4: SAML auth policy enabled for OAuth client / ISU users | `tests/captures/record_workday_config.py` |
| Workday SOAP | `POST /ccx/service/{tenant}/Human_Resources/v40.0` (Get_Integration_System_Users) | Legacy Task 3: ISU_WQL_COPILOT and ISU_Generic_COPILOT exist | `tests/captures/record_workday_config.py` (with `WORKDAY_RECORD_LEGACY=1`) |
| Workday SOAP | `POST /ccx/service/{tenant}/Identity_Management/v40.0` (Get_Integration_System_Security_Groups) | Legacy Task 3: ISSG_WQL_COPILOT and ISSG_Generic_COPILOT exist | same |
| Workday SOAP | `POST /ccx/service/{tenant}/Identity_Management/v40.0` (Get_Domain_Security_Policies) | Legacy Task 6: Domain permissions on each ISSG | same |
| Workday REST | `GET /ccx/api/v1/{tenant}/workers/me` | Simplified setup user-context lookup (replaces RaaS) | needs new wrapper — different auth flow (OAuth user, not basic ISU) |
| Workday RaaS | `GET /ccx/service/customreport2/{tenant}/{user}/WD_User_Context` | Legacy: RaaS report exists and runs | needs new wrapper |
| Microsoft Graph v1.0 | `GET /v1.0/applications?$filter=appId eq '<workday-app-id>'` | Entra: Workday SSO app registered | extend `record_flightcheck_graph.py` |
| Microsoft Graph v1.0 | `GET /v1.0/applications/{id}` | Entra: app exposes user_impersonation scope; preauthorized clients includes `4e4707ca-5f53-46a6-a819-f7765446e6ff` (Workday connector) | extend `record_flightcheck_graph.py` |
| Microsoft Graph v1.0 | `GET /v1.0/oauth2PermissionGrants?$filter=clientId eq '...'` | Entra: admin consent granted for openid/profile/User.Read | extend `record_flightcheck_graph.py` |
| Microsoft Graph v1.0 | `GET /v1.0/subscribedSkus` | License / SKU validation | extend `record_flightcheck_graph.py` (wrapper already updated; needs run) |
| Microsoft Graph v1.0 | `GET /v1.0/servicePrincipals?$filter=appId eq '...'` | App registration verification | extend `record_flightcheck_graph.py` (wrapper already updated; needs run) |
| Dataverse | `GET /api/data/v9.2/solutions?$filter=uniquename eq 'WorkdayExt...'` | Workday extension pack installed | already in `record_flightcheck_dataverse.py` |
| Dataverse | `GET /api/data/v9.2/botcomponents?$filter=name eq 'Workday [System] - 1: Set User Context V2'` | Required Workday topic installed | extend `record_flightcheck_dataverse.py` |
