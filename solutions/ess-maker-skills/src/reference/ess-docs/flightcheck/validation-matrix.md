# ESS FlightCheck — Validation Matrix

Comprehensive catalog of all pre-deployment validation checkpoints. Each
check has an ID, category, priority, automated/manual classification, and
a link to the relevant Microsoft Learn documentation.

Ported from the ESS Pre-flight Validator (JohnQuinn-Dev/ess-preflight-validator)
and extended with local file validation checks unique to the Copilot Kit.

---

## DA maker diagnostic scope

The catalog below spans legacy/custom-engine scopes and Connect profiles; it
is not a required checklist or a promised count for every DA run.

The maker skill and standalone CLI share one DA planner, registry and producer
path. `full`, explicit checkpoints and profiles reuse the same definitions;
`local` explicitly limits inspection to local authored files. A selected DA may run read-only diagnostics before
connection readiness is complete; invocation source does not change coverage.
Equivalent target, scope, permissions and evidence produce equivalent findings,
excluding timestamps/duration and actual changes to live data.

DA `full` inspects exactly the selected agent, regardless of whether Dataverse
is configured. `scripts/flightcheck/da_inventory.csv` attaches DA metadata to
the existing `REGISTRY`; it is the runtime coverage/disposition inventory, not
a second executor or a dependency on private planning documents. Its 168
identities comprise 85 executable definitions, 32 replacements, 25
legacy implementation definitions, two explicitly excluded assertions,
11 detail/family selectors, 10 guards and three
deferred ALM checks. These are definition counts, not 168 executed checks or
an arbitrary 100-pass target. Historical purposes and source revisions are
retained separately from current assertions and target scope.
`legacy` describes the old implementation, not its protocol: current Workday
DA uses both employee-authenticated REST and SOAP and requires no ISU.
`excluded` records missing admitted check coverage, not product obsolescence.
Learn provenance is exposed through each reconciled result's existing
`doc_link` field, separately from historical producer revisions.

The comprehensive selection includes:

| Check | What it establishes |
| --- | --- |
| DA-AGENT-001 | Exact native agent is accessible in the selected environment; no mandatory Dev/ALM enrollment |
| DA-CONTENT-001 | Readable, correctly identified authored components |
| ESS-SOLN-001 | Native ESS schema identity and readable content, not package origin or export/import proof |
| ENV-004 | Required active topic/flow references joined to exact physical bindings; unknown activation, incomplete inventories and inaccessible dependencies remain unverified |
| ENV-001 / ENV-003 / DA-ENV-LINK-001 | Exact environment identity, observed environment type and declared Dataverse linkage (optional for native-only agents); service ring is distinct from environment type |
| ENV-002 | Linked Dataverse provisioning state, when exposed by the supported environment read. Database type alone never proves successful provisioning |
| PRE-001/002/003/006/008/009 / AUTH-001/002/004 | Tenant SKU inventory, active role membership, exact Graph organization, Conditional Access enforcement-state inventory and a small user sample. These do not prove intended-user licensing, effective access, synchronization or require elevating the maker |
| PRE-004 / ENV-CAPACITY-001 / PRE-005 | Exact environment message-capacity observation and linked billing policies, subscription state and returned cost-budget records; effective capacity and spending sufficiency remain separate comparisons |
| ENV-008 / INFRA-006 | Effective environment DLP policy inventory and classification of the selected agent's actual connector dependencies |
| DA-TOPIC-001 | Selected cloud conversation activation inventory; unknown status is unverified, inactive is not a defect |
| DA-AUTH-001 / DA-INSTRUCTIONS-001 | Observed native sign-in settings and nonempty instructions in the captured template format, not employee sign-in or response quality |
| WD-INTEGRATION-001 / SN-INTEGRATION-001 | Optional integration applicability: enabled, disabled, configured without active use, not configured or uncertain; disabled/unconfigured is not a defect |
| WD-CONN-001 / SN-CONN-001 | Exact binding results for the enabled integration's selected-agent references, not unrelated environment connections |
| SN-FLOW-001 | State of ServiceNow flows actually invoked by this agent, if any; native direct actions do not require flows or legacy templates |
| SN-DA-AUTH-001 | Manual comparison of employee-delegated action sign-in, resource/client identity, short instance name and ServiceNow OIDC employee mapping; Knowledge crawl authentication is separate |
| SN-DA-TOPIC-001 | Manual inspection of the applicable HRSD or ITSM setup/system topics without guessing native schema/display-name mappings or requiring CEA templates |
| SN-DA-PORTAL-001 | Manual comparison of Setup Configurations > Set ServiceNow Portal BaseURI with the intended portal root, distinct from connector Instance name |
| WD-DA-PKG/FLOW/AUTH/TOPIC/WIRING-001 | Existing supported OOB Workday setup inspections when reviewed OOB topics are enabled in full; an explicit setup checkpoint/profile may inspect configuration before activation. Custom connectors alone do not require the OOB package |
| WD-DA-TOPIC-001 | All seven documented Workday system topics must be present once and active; unused optional employee scenarios need not be enabled. Presence/activation does not prove successful employee execution |
| WD-DA-TOPIC-001 / WD-DA-WIRING-001 | Native component inspection uses the exact selected-agent snapshot independently of Dataverse access; unrelated package/authorization read limits do not hide observed topic defects |
| WD-ASSIGN-001 / WD-ENTRA-* / WD-CONN-101/102 | Exact configured Workday Entra application, assignments, exposed scope, resource-bound consent and federation/certificate observations. Cross-system agreement and unsupported signing-option reads remain Manual; no tenant-wide first candidate substitutes for an unconfigured application |
| WD-CONN-012 / WD-REST-001 / WD-RUN-001 / SN-RUN-001 | Runtime-package plus selected-agent reference bindings, saved REST configuration and recent exact invoked-flow history. These do not certify deployed endpoint agreement or current intended-employee execution |
| DV-CONN-001 | Enabled OOB Workday runtime Dataverse reference |
| WD-REST-002 | Development checks the selected local component-map/YAML redirect. Test and Production inspect the exact selected native agent's active User Context setup and Workday UserContextV2 topics and their OnRedirect target, independently of local Development files and Dataverse package reads. Repair in Development and promote; do not push local files into a promoted realm. Neither assertion proves publication or employee runtime success |
| WD-DA-ATTACH-001 | Manual inspection of both agent connection references, ESS Workday Runtime and ESS Workday Runtime REST Execution, under Settings > Connection Settings > Manage; select the intended Workday connection and enable Allow permission to share parameters on both. Flow authorization is separate; never an automatic pass |
| WD-CONN-AUTH-001 / WD-API-CLIENT-001 / WD-TENANT-001 / WD-SEC-003 | Manual employee-auth, cross-system IDs/endpoints, SAML bearer grant, Workday Owned Scope, the four functional areas and intended employee domain permissions. Public Worker Reports requires Get under Integration Permissions; extra scenario domains remain conditional |
| WD-REST-001 | Strict saved HTTPS `/ccx/api` structure, without embedded credentials/query/fragment or extra resource suffix. Valid saved syntax remains Manual until compared with the actual deployed Workday connection and tenant |
| WD-REF-001 / LOCAL-TC-001 | Current OOB runtime-topic or custom reference IDs/labels compared with applicable tenant values; old template-file counting resolves to this shared check. XML-like topic entries are supported; unused reference-data types need no customization |
| WD-DA-MAKER-001 | Fresh unpublished Test-pane employee-ID or intended read-only scenario; no automatic email/phone update and no claim of published non-maker success |
| Selected local checks | Instructions/identity, starter-prompt notes, informational conversation inventory and placeholder-description detection; no sibling scan, description word-count threshold or legacy minimum-topic/User Context variable requirements |
| Knowledge, connected search, handoff, QA and publishing checks | Supported authored configuration observations plus scoped Manual verification for source mapping, indexing, effective employee access, evaluation, audience and rollout. No approval forms, employee transactions or default ALM probes |
| CONFIG-013 / EXT-002 / EXT-002-ACL | Authoritative SharePoint site/file scope, exact connected-source mapping, separate ServiceNow Knowledge ingestion authentication and Simple/Advanced user-criteria behavior; indexing is not employee ACL proof |
| DA-SP-FILTER-001 / DA-HANDOFF-001 | Conditional SharePoint metadata/user-context/KQL filtering and optional Hub connected-agent descriptions/publication/routing/access. Unsupported applicability remains unknown/Manual, not compulsory setup or invented absence |
| QA-001/002/012 | Scenario-specific test design, actual completed evaluation runs and organizational response-quality criteria; a dataset-quality gate or deployed test set is not a successful agent evaluation |
| PUB-003/006/011 / DA-RUNTIME-001 | Separate unpublished maker testing, later organization approval/pilot audience and published non-maker use in Microsoft 365 Copilot Chat; no automatic publishing or required approval to inspect Dev |

Every planned definition produces exactly one result, including a scoped
fallback or explicit not-applicable disposition. The additive JSON `coverage`
object records requested, planned and emitted IDs, aliases, completed automatic
checks, manual verification, not-applicable items and execution limitations.
Missing/duplicate producer rows, malformed data and unexpected service/auth
failures are Errors, not successful or routine manual results. A denied
delegated read or unsupported observation becomes Manual with the check ID,
purpose, target, responsible role, ordered steps and missing-setting guidance.
Failed identity/content prerequisites prevent dependent remote reads.

Graph uses its existing Graph-specific public client and delegated read scopes,
not the AgentBuilder application's `/.default` audience. Both authenticated
account and token tenant must match the selected native inspection before any
Graph read. A failed Graph sign-in is retained for dependent observations
without repeatedly prompting in the same run. Teams-bearing SKU absence is an
inventory observation, not a universal DA prerequisite or a direction to use
standalone Teams as the validation surface.

ServiceNow applicability is preserved across full/checkpoint/profile routes:
inactive/absent actions are not applicable, unknown discovery remains unverified,
and active actions receive the scoped checks. Knowledge/Hub/filtering guidance
does not authenticate unrelated connection providers merely to return manual
steps. A complete native component inventory is not a complete external-source
or connected-agent mapping, so unsupported applicability is never inferred from
zero projected components.

The explicit `local` scope remains unauthenticated in both entrypoints and
proves only local authored state, not deployment freshness. It never substitutes
for a requested full run. Missing extracted content is an inspection
limitation, not proof of a broken cloud agent.

Reports separate confirmed issues, unverified inspection, notes and Passed
checks, with explicit optional-integration dispositions and zero-inclusive
status totals. Specific access-denied inspections can need administrator
review without becoming mandatory approvals. The private local run header
includes exact target IDs, the verified account and duration.
`ISSUES_FOUND` / `SOME_CHECKS_UNVERIFIED` exit `1`;
`SETUP_CHECKS_PASSED` / `CHECKED_WITH_NOTES` exit `0`. JSON adds
`diagnostic_only` (versioned contract: `diagnosticOnly`) for this route.
Native-selected DA checkpoints share the diagnostic path. Profiles reuse the
same findings while preserving the existing `READY` / `READY_WITH_WARNINGS` /
`NOT_READY` aggregate and versioned Connect-consumer contract. Pre-agent setup
without a saved native `botId`, explicit legacy profiles and older narrow
scopes retain their compatibility routes; they are not comprehensive runs.

DA full does not run licensing approvals, ALM promotion or
revision-provenance gates, feature attestations, UAT evidence collection or
the mutating connectivity probe. Applicable
portal-only checks are grouped under Manual verification with their IDs,
purpose, responsible person, detailed steps and missing-setting guidance.
They remain Manual, with no completion/attestation form or release gate.
Customer categories consolidate Workday module names without changing raw
JSON identifiers or legacy/Connect contracts. Cloud and selected local-source
findings share the Agent category while retaining their separate assertion
scope and original recorded categories.

`WD-RUN-001` has the code-defined Workday Litmus Test tag. Its no-recent-response
guidance uses the selected agent's unpublished Test pane and an enabled,
approved read-only question such as "What is my employee ID". Running flows
require waiting, confirmed failures require repair, and denied history access
does not call for repeated test prompts. One recent scoreable agent-facing
success is sufficient for this passive check; mixed failures remain disclosed
and no prompt/employee correlation is claimed. Run just this check with
`python scripts/flightcheck/cli.py --checkpoint WD-RUN-001 --agent-slug {AGENT_SLUG}`.
The default `workspace/flightcheck/workday-litmus` output preserves a full
report. Focused HTML shows requested findings only; prerequisite blockers and
complete execution counts remain in its header, technical details and JSON.

Profiles emit declared client availability and verified target context.
Connect can reconcile a Manual saved REST observation only with its existing
validated Workday-admin response and matching maker-confirmed live connection
target; it does not change the standalone result to Passed or add mandatory
litmus correlation to Connect completion.

`PUB-001`, `PUB-002` and
`ENV-004-GRS` are explicitly deferred for the shared DA route; existing legacy
ALM behavior outside that route remains unchanged.

### Adding checks for a skill

Implement and verify a supported producer, then register its shared
`CheckpointSpec` and `DAValidation` metadata (or extend the shipped CSV-backed
definitions). Include purpose, target scope, prerequisites, applicability,
API-contract provenance, next-step owner and complete manual fallback.
An executable DA definition is automatically discovered by `full`; do not
add another per-check full-run list. Reference its stable ID in a named profile
for the skill. Skills consume structured JSON and own workflow progression,
not duplicate validation logic or rewrite Manual findings into Passed.

## Priority Levels

| Level    | Meaning                                         |
| -------- | ----------------------------------------------- |
| Critical | Must pass before proceeding to deployment       |
| High     | Should pass; requires remediation plan if fails |
| Medium   | Important but can be addressed post-deployment  |
| Low      | Nice-to-have; optional configuration            |

## Roles (next-step owner)

Every actionable result (Failed, Error, Warning, Manual, or
NotConfigured) is tagged with one or more **roles** — the admin
persona(s) who must take the next action to fix it or perform the
manual validation. The role(s) appear as a "Role" column in the HTML
report and `results.json`, and on the terminal action/manual rows.
Passed and Skipped rows have no next step, so no role is shown.

| Role                        | Acts in…                                                                                                 |
| --------------------------- | -------------------------------------------------------------------------------------------------------- |
| Entra Admin                 | Entra ID: app registrations, SAML, conditional access, directory-role assignment                         |
| Microsoft 365 Admin         | M365 admin center: license assignment, Office Cloud Policies, Graph connectors, Integrated-apps approval |
| Power Platform Admin        | Power Platform: environments, DLP, connections, solution import, cloud-flow state, Dataverse env vars    |
| Workday Admin               | The Workday tenant: ISU accounts, security groups, domain permissions, RaaS, auth policies               |
| ServiceNow Admin            | The ServiceNow instance: service accounts, roles, ACLs                                                   |
| SAP Admin                   | The SAP SuccessFactors tenant                                                                            |
| ESS Maker / Agent Developer | Local agent files: topics, variables, template configs, evaluations, publishing/QA gates                 |

A check can carry more than one role when the fix spans systems (e.g.
WD-CONN-102's SAML cert lives on the Entra app but is compared in
Workday → Entra Admin + Workday Admin).

---

## 1. Prerequisites (PRE-xxx)

| ID      | Check                                                                                    | Priority | Method                                                                                                                        | Doc Link                                                                                                                                                                   |
| ------- | ---------------------------------------------------------------------------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PRE-001 | Microsoft 365 Copilot licenses assigned                                                  | Critical | Graph API `/subscribedSkus`                                                                                                   | [prerequisites#licensing](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#licensing)                                           |
| PRE-002 | Copilot Studio licenses for admins/makers                                                | Critical | Graph API `/subscribedSkus`                                                                                                   | [prerequisites#licensing](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#licensing)                                           |
| PRE-003 | Microsoft Teams licenses for users                                                       | Critical | Graph API `/subscribedSkus`                                                                                                   | [prerequisites#licensing](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#licensing)                                           |
| PRE-004 | Copilot Studio capacity configured (sufficient for the shared/published user population) | Critical | Power Platform Licensing API (`MCSMessages` `entitlement.capacity.allocated.value`) + Dataverse sharing enumeration; cross-checks PRE-005 PayG | [requirements-messages-management#prepaid-capacity](https://learn.microsoft.com/en-us/microsoft-copilot-studio/requirements-messages-management?tabs=new#prepaid-capacity) |
| PRE-008 | Global Admin role assigned                                                               | Critical | Graph API `/directoryRoles`                                                                                                   | [prerequisites#required-roles](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#required-roles)                                 |
| PRE-009 | Power Platform Admin role assigned                                                       | Critical | Graph API `/directoryRoles`                                                                                                   | [prerequisites#required-roles](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#required-roles)                                 |

## 2. Environment Configuration (ENV-xxx)

| ID               | Check                                                                                                                                                                                                                                                                                                                                                                                                                                   | Priority | Method                                                | Doc Link                                                                                                                                                                       |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| ENV-001          | Power Platform environment exists                                                                                                                                                                                                                                                                                                                                                                                                       | Critical | BAP Admin API                                         | [prepare#set-up-your-power-platform-environment](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prepare#set-up-your-power-platform-environment) |
| ENV-002          | Dataverse database provisioned                                                                                                                                                                                                                                                                                                                                                                                                          | Critical | BAP Admin API                                         | [prepare#set-up-your-power-platform-environment](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prepare#set-up-your-power-platform-environment) |
| ENV-003          | Environment type                                                                                                                                                                                                                                                                                                                                                                                                                        | High     | BAP Admin API                                         | [prepare#set-up-your-power-platform-environment](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prepare#set-up-your-power-platform-environment) |
| ENV-004          | Connections & connection references — reads `connectionReferenceChanges` from the Declarative Agent minimalBots components payload via `runner.agentbuilder.fetch_components`; unions and de-dupes references across all configured agents; reports whether each agent-declared connection reference is bound to a real connection. Skips without an AgentBuilder client or configured agent `botId`; warns on a components read error. | High     | AgentBuilder (minimalBots components + ALM configure) | [prepare#set-up-your-power-platform-environment](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prepare#set-up-your-power-platform-environment) |
| ENV-004-UR-nnn   | Unbound reference (agent-declared reference has no connection bound)                                                                                                                                                                                                                                                                                                                                                                    | High     | —                                                     | —                                                                                                                                                                              |
| ENV-004-GRS      | Opt-in GRS commit pin. Skips unless `expectedGrsCommitSha` is configured in `.local/config.json`; reads `.../alm/{id}/configure`; passes when `commitSha` matches and fails on mismatch or missing `commitSha`.                                                                                                                                                                                                                         | High     | AgentBuilder (minimalBots ALM configure)              | —                                                                                                                                                                              |
| ENV-CAPACITY-001 | Copilot Studio message capacity provisioned                                                                                                                                                                                                                                                                                                                                                                                             | Critical | Power Platform Licensing API (`MCSMessages` `entitlement.capacity.allocated.value`) | [requirements-messages-management#prepaid-capacity](https://learn.microsoft.com/en-us/microsoft-copilot-studio/requirements-messages-management?tabs=new#prepaid-capacity)     |
| ENV-008          | DLP policies configured                                                                                                                                                                                                                                                                                                                                                                                                                 | High     | BAP Admin API                                         | [prepare#allow-the-external-systems-connector](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prepare#allow-the-external-systems-connector)     |

### Native no-Dataverse agent readiness (DA-xxx)

The shared DA route uses the maker scope above, including hybrid agents with Dataverse.
The table below describes retained older narrow-scope behavior;
its Dev-only authoring admission and candidate-connection fallback are not
used by DA full diagnostics.

| ID             | Check                                                                                                                                                                                                                                                        | Priority | Method                                                            | Doc Link |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- | ----------------------------------------------------------------- | -------- |
| DA-AGENT-001   | Saved active agent is directly accessible as the exact editable authoring target: enrolled Dev or explicitly unenrolled                                                                                                                                      | Critical | AgentBuilder Minimal Bot API                                      | —        |
| DA-CONTENT-001 | Exact agent returns an authored component footprint                                                                                                                                                                                                          | High     | AgentBuilder Minimal Bot API                                      | —        |
| DA-CONN-001    | Summary of native logical-to-physical connection readiness                                                                                                                                                                                                   | High     | AgentBuilder component snapshot + Power Platform Connectivity API | —        |
| DA-CONN-002+   | One detail row per logical connector reference. Exact ID matches are verified; a sole connected candidate passes with an explicit unverified-binding disclaimer; ambiguous candidates warn without guessing; missing or disconnected candidates do not pass. | High     | AgentBuilder component snapshot + Power Platform Connectivity API | —        |

## 2b. ESS Solution Installation (ESS-SOLN-xxx)

| ID           | Check                                                                      | Priority | Role              | Gate | Method                       | Doc Link                                                                                         |
| ------------ | -------------------------------------------------------------------------- | -------- | ----------------- | ---- | ---------------------------- | ------------------------------------------------------------------------------------------------ |
| ESS-SOLN-001 | ESS base agent solution (`msdyn_copilotforemployeeselfservice*`) installed | Critical | Environment Maker | prog | Dataverse REST (`solutions`) | [install](https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/install) |

## 3. Authentication & Identity (AUTH-xxx)

| ID       | Check                         | Priority | Method                                           | Doc Link                                                                                                                                                                                                   |
| -------- | ----------------------------- | -------- | ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AUTH-001 | Microsoft Entra ID configured | Critical | Graph API `/organization`                        | [prerequisites#identity-authentication-and-single-sign-on-sso](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#identity-authentication-and-single-sign-on-sso) |
| AUTH-002 | Conditional Access policies   | High     | Graph API `/identity/conditionalAccess/policies` | [prerequisites#identity-authentication-and-single-sign-on-sso](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#identity-authentication-and-single-sign-on-sso) |
| AUTH-004 | User identity synchronization | High     | Graph API `/users`                               | [prerequisites#identity-authentication-and-single-sign-on-sso](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#identity-authentication-and-single-sign-on-sso) |

## 3b. Entra App Provisioning (WD-ENTRA-xxx / WD-ASSIGN-xxx)

Minted by **skill-3** (`provision-workday-entra-app`) and runnable in isolation
via `--checkpoint`. These configure the Workday SSO/OBO Entra app; the app is
discovered by its gallery `applicationTemplateId` (rename-proof), so the config
`entraAppId` / `entraAppObjectId` are optional hints only. All are Entra-only
(Microsoft Graph) — none needs a Dataverse endpoint. See the setup catalog below
for the owning checklist rows (S3.1–S3.7).

| ID                   | Check                                                                                                                                   | Priority | Method                                                                                                          | Doc Link                                                                                        |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| WD-ENTRA-SCOPE-001   | `user_impersonation` exposed, Workday connector (`4e4707ca`) pre-authorized, Graph delegated perms (openid/profile/User.Read) requested | Critical | Graph `/applications` (`api.oauth2PermissionScopes`, `api.preAuthorizedApplications`, `requiredResourceAccess`) | [workday-tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial) |
| WD-ENTRA-CONSENT-001 | Tenant-wide admin consent (`AllPrincipals` grant) covers the Graph delegated perms                                                      | Critical | Graph `/oauth2PermissionGrants`                                                                                 | [workday-tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial) |
| WD-ASSIGN-001        | Enterprise-app user/group assignment (or confirmed not required). Shares logic with `AUTH-005`.                                         | Critical | Graph `/servicePrincipals/{id}/appRoleAssignedTo`                                                               | [workday-tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial) |
| WD-ENTRA-NAMEID-001  | `claimsMappingPolicy` overriding the SAML NameID claim is assigned (degrades to `MANUAL` when the policy route is unreadable)           | High     | Graph `/servicePrincipals/{id}/claimsMappingPolicies`                                                           | [workday-tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial) |
| WD-ENTRA-SIGNOPT-001 | "Sign SAML response and assertion" signing option — portal-only, always returns `MANUAL`                                                | High     | None (portal attestation; no Graph property)                                                                    | [workday-tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial) |

## 3c. Workday Tenant Configuration (WD-API-CLIENT-xxx / WD-TENANT-xxx)

Minted by **skill-4** (`configure-workday-tenant`) and runnable in isolation via
`--checkpoint`. These attest the Workday-tenant-side configuration (API client,
Tenant Setup – Security, authentication policy). Workday exposes **no queryable
admin API** the kit can reach, and self-verifying through a Workday connection
would be circular, so both are **always `MANUAL`**: they read only
`.local/connect/workday/config.json`, echo the captured values, and name the
Workday screen to verify. Neither needs a client or a Dataverse endpoint. The
signing-cert parity (S4.4) reuses `WD-CONN-102` — it is **not** minted
here. See the setup catalog below for the owning checklist rows (S4.1–S4.4).

| ID                | Check                                                                                                                                                                                                                                                           | Priority | Method                                     | Doc Link                                                                                        |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------- |
| WD-API-CLIENT-001 | Workday API client registered — SAML **\*\*** grant, functional areas (Core Payroll, Organizations and Roles, Staffing, Time Off and Leave), Include Workday Owned Scope = Yes. Echoes captured `oauthClientId` / `tokenEndpoint`.                              | Critical | None (attestation; echoes captured config) | [workday-tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial) |
| WD-TENANT-001     | Tenant Setup – Security (redirect URL, OAuth 2.0 Clients + SAML enabled, Service Provider ID matches Entra Identifier) and authentication policy scoped to the OAuth client + activated. Echoes captured `restBaseUrl` / `soapBaseUrl` / `tenant` / `appIdUri`. | High     | None (attestation; echoes captured config) | [workday-tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial) |

## 3d. Workday Extension Pack (WD-CONN-AUTH-xxx / DV-CONN-xxx / WD-REST-xxx / WD-NET-xxx)

Minted by **skill-5** (`install-workday-extension-pack`) and runnable in isolation
via `--checkpoint`. All five share
`checks/workday_extension.run_workday_extension_checks` (category **Workday
Extension**, ordered **after** Workday so `WD-PKG-001` hydrates the cached
connection references and install-flavor verdict first). Three are programmatic
(one Dataverse read, two pure-local checks); two are **always `MANUAL`** because
the kit has no verifiable signal for them. Skill-5 also **reuses** `WD-PKG-001`
(S5.1), `WD-CONN-012` (S5.2), and `WD-FLOW-*` (S5.6) from `checks/workday.py` — those
are **not** minted here. See the setup catalog below for the owning checklist rows
(S5.1–S5.8).

| ID               | Check                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Priority | Method                                                   | Doc Link                                                                                                                           |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- | -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| WD-CONN-AUTH-001 | Workday connection authentication is **Microsoft Entra ID Integrated**. Reads the cached Workday (`ff0df` or `msdyn_sharedworkdaysoap_workdayruntime`) reference and echoes the observed `connectionParametersSet.name` + owner from the Power Platform admin connection. **Always `MANUAL`** — the admin API exposes no kit-verifiable fingerprint for the "Microsoft Entra ID Integrated" auth type, so this echoes for operator confirmation rather than PASS/FAIL (see reconciliation note below). | High     | Power Platform admin connections (echo only)             | [workday-simplified-setup](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday-simplified-setup) |
| DV-CONN-001      | ESS Dataverse connection reference (`…_92b66` or `msdyn_sharedcommondataserviceforapps_workdayruntime`, connector `shared_commondataserviceforapps`) bound to an **active** connection; echoes the owner so the operator can confirm it is their own account. Programmatic PASS/FAIL on a documented-tier Dataverse `connectionreferences` read. **Non-`WD` family.**                                                                                                                                  | High     | Dataverse `connectionreferences` (+ PP admin owner echo) | [workday-simplified-setup](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday-simplified-setup) |
| WD-REST-001      | Captured `restBaseUrl` is present and **trimmed to** `/api`. Pure-config check — no client.                                                                                                                                                                                                                                                                                                                                                                                                            | High     | None (reads captured config)                             | [workday-simplified-setup](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday-simplified-setup) |
| WD-REST-002 | User Context redirects to Workday UserContextV2. DA Development inspects the selected local map/YAML; Test and Production read that exact promoted agent's active native topics and OnRedirect target. Local files cannot pass or block a promoted redirect check. The legacy producer remains local-only and skips the legacy install path. Neither mode certifies employee runtime success. | High | Local map/YAML or validated AgentBuilder component read | [workday-simplified-setup](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday-simplified-setup) |
| WD-NET-001       | Workday REST + SOAP endpoints allowlisted at the corporate firewall for the Power Platform managed connectors. **Always `MANUAL`** — the kit has no reliable probe (a local reachability test proves only the dev machine's egress, not the managed-connector outbound path), so it echoes the endpoints InfoSec/IT must allowlist.                                                                                                                                                                    | High     | None (InfoSec/IT attestation; echoes captured hosts)     | [workday-simplified-setup](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday-simplified-setup) |

> **Gate reconciliation (S5.3).** The master checklist historically tagged S5.3 as
> `prog`, but the shipped `WD-CONN-AUTH-001` is **always `MANUAL`** (v1 compromise):
> the Power Platform admin API exposes no documented, kit-verifiable fingerprint for
> the `shared_workdaysoap` "Microsoft Entra ID Integrated" auth type, and the
> validated `flightcheck_pp_admin.yaml` cassette contains no Workday connection to
> confirm one. Per the cardinal rule in
> [`scripts/flightcheck/AGENTS.md`](../../../../scripts/flightcheck/AGENTS.md)
> (never assert a verdict from an unconfirmed API response shape), S5.3 is therefore
> gated **`attest`** — the checkpoint echoes the observed auth parameter set for the
> operator to confirm, and the row completes only on explicit acknowledgement. If a
> cassette capturing a Workday connection's `connectionParametersSet.name` is added
> later, this can be promoted to a programmatic PASS/FAIL and the gate flipped back
> to `prog`.

## 3e. Workday Topics (TOPIC-TRIGGER-xxx / TOPIC-INTEGRATION-xxx)

Minted by **skill-6** (`create-new-topic`) and runnable in isolation via
`--checkpoint`. Both are **family** checkpoints that share
`checks/topics.run_topic_checks` (category **Workday Topics**, ordered **after**
Workday Extension) and expand to **one row per new/custom topic** — a topic is
"new" when its `topics/*.mcs.yml` differs from the OOTB `.baseline/topics/`
snapshot the extension-pack push mirrored (so OOTB pack topics never emit rows).
Both are **pure local-file** checks (they read only the extracted working copy —
no client, no config, no Dataverse endpoint, no cassette). When no custom topic
exists yet, each family returns a single `NotConfigured` "nothing to verify yet"
row (id `…-001`) so the wildcard always resolves. See the setup catalog below for
the owning checklist rows (S6.1–S6.2).

> **Advisory review (S6.3).** After both checkpoints pass, skill-6 runs an
> advisory **topic review** over the finished topic (checklist row S6.3, `advisory`
> gate). It is **not** a flightcheck checkpoint — it surfaces authoring findings
> and never blocks; the row completes once the report is shown. See
> `src/skills/topics/review/SKILL.md`.

| ID                   | Check                                                                                                                                                                                                                                                                                  | Priority | Method                                              | Doc Link                                                                                                       |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| TOPIC-TRIGGER-\*     | Each new topic is a well-formed `kind: AdaptiveDialog` **and** has a trigger (a `beginDialog` with `OnRecognizedIntent`/`OnRedirect`/…); an intent-routed topic additionally needs trigger phrases (`modelDescription` content or `triggerQueries`). Programmatic PASS/FAIL per topic. | High     | None (reads local agent topic YAML vs `.baseline/`) | [workday#topics](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#topics) |
| TOPIC-INTEGRATION-\* | Each new topic's integration wiring resolves — no unresolved `{{PLACEHOLDER}}` scaffolding or `<UPPERCASE>` tenant reference-ID tokens (e.g. `<TENANT_NAME>`) remain. A topic with no external wiring is a benign PASS. Programmatic PASS/FAIL on placeholder resolution only.         | High     | None (reads local agent topic YAML vs `.baseline/`) | [workday#topics](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#topics) |

> **Gate note (S6.2).** `TOPIC-INTEGRATION-*` is a `prog (+ SME for IDs)` row.
> The checkpoint proves the placeholder tokens were **resolved**, but the kit
> cannot validate that each wired tenant reference-ID _value_ (e.g. the Time Off
> Type ID) is correct against the live Workday instance — that would require a
> Workday API read the check deliberately avoids (pure local-file). Per the
> cardinal rule in
> [`scripts/flightcheck/AGENTS.md`](../../../../scripts/flightcheck/AGENTS.md),
> the checkpoint asserts only what it can prove; S6.2 therefore also carries a
> **Workday SME attestation** that the reference-ID values are correct, captured
> in the skill-6 playbook (P6.4). A checkpoint PASS is necessary but not
> sufficient for the row to complete.

## 4. External Systems Discovery

| ID      | Check                                 | Priority | Method                   | Doc Link                                                                                                               |
| ------- | ------------------------------------- | -------- | ------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| WD-001  | Workday solution installed            | High     | PP Admin API (flow scan) | [workday](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday)                       |
| SN-001  | ServiceNow solution installed         | High     | PP Admin API (flow scan) | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow)                 |
| SAP-001 | SAP SuccessFactors solution installed | High     | PP Admin API (flow scan) | [sap-successfactors](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/sap-successfactors) |

## 4b. Workday DA validation (WD-DA-xxx)

These independent profiles can be run directly with
`/flightcheck --profile <profile-name>`. Connect workflows may select a profile
when they need a boundary-specific readiness decision, but profile execution is
not coupled to a Connect lifecycle.

| Profile                             | Coverage                                                                                                                     |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `workday-da:setup-readiness`        | Live readiness of the selected ESS HR declarative agent and its materialized workspace content                                |
| `workday-da:package-ready`          | Selected-agent Workday runtime package installation                                                                          |
| `workday-da:dataverse-ready`        | Workday runtime package, Dataverse workflow inventory, and runtime connection-reference readiness                            |
| `workday-da:external-prerequisites` | Entra signing, Workday API-client and tenant prerequisites; network attestation remains a separate conditional diagnostic |
| `workday-da:post-runtime`           | Reviewed runtime-flow inventory                                                                                              |
| `workday-da:post-connection`        | Connection-reference, delegated authorization, and Workday endpoint readiness                                                |
| `workday-da:post-agent-wiring`      | Workday topic, wiring, guided flow attachment, and endpoint validation for the selected DA                                   |
| `workday-da:final`                  | Complete Workday DA readiness contract across all profile boundaries                                                         |

| ID               | Check                                                                                                                                                                                        | Priority | Method                                                 | Doc Link                                                                                                       |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| WD-DA-PKG-001    | Supported Workday runtime package is installed for the selected ESS HR DA                                                                                                                    | Critical | Dataverse solution inventory                           | [workday](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday)               |
| WD-DA-FLOW-001   | Reviewed Workday runtime flows are present, uniquely identified, and enabled                                                                                                                 | Critical | Dataverse workflow inventory                           | [workday#topics](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#topics) |
| WD-DA-AUTH-001   | Runtime flows use the required delegated employee authorization contract                                                                                                                     | Critical | Dataverse workflow and delegated-authorization records | [workday](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday)               |
| WD-DA-TOPIC-001  | Complete reviewed out-of-box Workday topic inventory is present and active                                                                                                                   | Critical | Native AgentBuilder components API                     | [workday#topics](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#topics) |
| WD-DA-WIRING-001 | Conversation Start invokes the reviewed active runtime-template topic immediately before User Context Validate, and User Context does not retain the obsolete nested runtime-template call   | Critical | Native AgentBuilder components API                     | [workday#topics](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#topics) |
| WD-DA-ATTACH-001 | Guided attestation that the reviewed Workday flows are attached to the selected ESS HR DA with the required parameter-sharing settings                                                       | High     | Manual Copilot Studio verification                     | [workday](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday)               |

## 5. Workday Deep Validation (WD-xxx)

| ID          | Check                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | Priority | Method                                                                 | Doc Link                                                                                                                                                             |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| WD-ENV-001  | EmployeeContextRequestAccountName configured                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Critical | Dataverse REST                                                         | [workday#step-4-environment-variables](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#step-4-environment-variables)           |
| WD-ENV-002  | EmployeeContextRequestReportName verified                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | High     | Dataverse REST                                                         | [workday#step-4-environment-variables](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#step-4-environment-variables)           |
| WD-ENV-003  | EmployeeContextRequestReportInstanceName verified                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | High     | Dataverse REST                                                         | [workday#step-4-environment-variables](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#step-4-environment-variables)           |
| WD-CONN-001 | Workday connections summary                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | High     | PP Admin API                                                           | [workday#step-3-connection-references](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#step-3-connection-references)           |
| WD-CONN-nnn | Individual connection status                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | High     | PP Admin API                                                           | [workday#step-3-connection-references](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#step-3-connection-references)           |
| WD-CONN-102 | Workday SAML signing certificate health (Entra-automated, Workday-manual comparison)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | High     | Microsoft Graph (servicePrincipal.keyCredentials)                      | [workday#task-1-create-the-x509-public-key](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#task-1-create-the-x509-public-key) |
| WD-RUN-001  | Workday end-to-end runtime health. **Passive-only, user-assisted** — grades a real, fresh end-to-end Workday run (`Copilot → Workday → response back to Copilot`) from run history; never writes to the tenant. Direct/headless flow invocation was ruled out: the Workday connector is invoker-scoped (the flow does not carry the end user's Workday token), it hits auth/runtime-context walls outside the user path, and it only tests the `Flow → Workday` leg — flows have succeeded while the Copilot experience still failed. PASS when a terminal Workday run **started within the last 60 minutes** succeeded; FAILED when the fresh run(s) failed; NOT_CONFIGURED when no run started in the last 60 minutes (older successes are not counted as a pass), returning guided remediation that steers the operator to sign in to ESS Copilot, ask a safe read-only question ("Who is my manager?" / "What is my job title?"), then re-run within the window. Links ADO 7944807. | High     | Passive run-history read (PP Admin API), 60-minute freshness window     | [workday](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday)                                                                     |
| WD-FLOW-nnn | Individual flow enabled/disabled                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | High     | PP Admin API                                                           | [workday#topics](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#topics)                                                       |
| WD-SEC-003  | Personal Data domain write permission (Employee as Self). See [remediation guide](./remediation-guide.md#wd-sec-003-personal-data-domain-write-permission-employee-as-self) for full details.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | High     | Workday SOAP runtime probe + MANUAL fallback                           | [workday](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday)                                                                     |

### Workday SOAP Workflow Tests (WD-WF-xxx)

Tests all 17 ESS pre-configured workflows against the Workday API. Requires ISU credentials.

| ID        | Workflow            | Service         | Type  | PII | Security Domain                                                                                                                       |
| --------- | ------------------- | --------------- | ----- | --- | ------------------------------------------------------------------------------------------------------------------------------------- |
| WD-WF-001 | Employee ID         | Human_Resources | Read  |     | Worker Profile                                                                                                                        |
| WD-WF-002 | Company Code        | Human_Resources | Read  |     | Organizations                                                                                                                         |
| WD-WF-003 | Cost Center         | Human_Resources | Read  |     | Organizations                                                                                                                         |
| WD-WF-004 | Hire Date           | Human_Resources | Read  |     | Worker Profile                                                                                                                        |
| WD-WF-005 | Employment Info     | Human_Resources | Read  |     | Worker Profile                                                                                                                        |
| WD-WF-006 | Position Number     | Human_Resources | Read  |     | Worker Profile                                                                                                                        |
| WD-WF-007 | Service Anniversary | Human_Resources | Read  |     | Worker Profile                                                                                                                        |
| WD-WF-008 | National IDs        | Human_Resources | Read  | ⚠️  | Personal Data                                                                                                                         |
| WD-WF-009 | Passports           | Human_Resources | Read  | ⚠️  | Personal Data                                                                                                                         |
| WD-WF-010 | Visas               | Human_Resources | Read  | ⚠️  | Personal Data                                                                                                                         |
| WD-WF-011 | Language Info       | Human_Resources | Read  |     | Qualifications                                                                                                                        |
| WD-WF-012 | Certifications      | Human_Resources | Read  |     | Qualifications                                                                                                                        |
| WD-WF-013 | Base Compensation   | Compensation    | Read  |     | Compensation                                                                                                                          |
| WD-WF-014 | Compensation Ratio  | Compensation    | Read  |     | Compensation                                                                                                                          |
| WD-WF-015 | Emergency Contact   | Human_Resources | Read  | ⚠️  | Personal Data                                                                                                                         |
| WD-WF-016 | Update Email        | Human_Resources | Write |     | Contact Information (see WD-SEC-003 for the precise Personal Data + Maintain Contact Information / Edit Worker Additional Data check) |
| WD-WF-017 | Update Phone        | Human_Resources | Write |     | Contact Information (see WD-SEC-003 for the precise Personal Data + Maintain Contact Information / Edit Worker Additional Data check) |

### Workday Custom-Workflow Inventory (WD-WF-CAT-xxx) — Manual

The 17 SOAP tests above cover only the OOTB workflows the kit ships
SOAP envelopes for. Customers routinely wire up additional Workday
scenarios via two patterns:

- **Pattern A** — Topic that calls
  `WorkdaySystemGetCommonExecution` with a `scenarioName` of a
  template-config record in Dataverse.
- **Pattern B** — Standalone topic that calls a customer-built cloud
  flow bound to the `shared_workdaysoap` connector via
  `InvokeFlowAction`.

Both patterns exit the automated validation surface (the kit doesn't
ship a Workday WSDL parser; per-tenant security domain / ISU config
varies). WD-WF-CAT-001 walks `workspace/agents/*/topics/*.mcs.yml`
for these patterns and emits a MANUAL row enumerating any scenarios
that aren't in the OOTB catalog. The OOTB catalog is resolved live
from the customer's own Dataverse: the check queries
`msdyn_employeeselfservicetemplateconfigs` and treats every
`ismanaged=true` row as OOTB (auto-detects every scenario shipped by
the installed Workday extension pack, with no kit-side curation
needed). There is no fallback — if Dataverse credentials are missing
the check returns SKIPPED, and if the Dataverse query errors the
check returns WARNING surfacing the error verbatim. Returning PASSED
without a tenant-accurate catalog would violate FlightCheck design
principle #1 ("never return PASSED when the check cannot actually
validate what it claims to validate"). The MANUAL remediation
carries a 4-item checklist (ISU account, payload shape vs. Workday
WSDL, evaluation test prompt, connection-ref auth health).

| ID             | Check                                                                      | Priority | Method                                                                                           | Doc Link                                                                                                                     |
| -------------- | -------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| WD-WF-CAT-001  | Workday custom-workflow inventory checklist (MANUAL)                       | High     | Local file walk + Dataverse managed-template-config diff (SKIP on no token, WARN on query error) | [workday-extensibility](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday-extensibility) |
| WD-WF-CAT-LINK | Cross-link trailer surfacing WD-WF-CAT-001 from inside the SOAP-test block | Medium   | Computed from WD-WF-CAT-001 cache                                                                | [workday-extensibility](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday-extensibility) |

MANUAL rows do not fail readiness (per FlightCheck design principle #2)
— they direct the operator to verify what the kit cannot. Address
each scenario by confirming it against the 4-item checklist in the
customer's environment. A scenario surfacing as MANUAL means it is
NOT a managed row in the customer's tenant — either it is genuinely
custom or the Workday extension pack is not installed in this
environment.

## 6. Local Agent File Validation (Kit-exclusive)

These checks parse the extracted agent files on disk — a capability the
standalone FlightCheck tool did not have.

| ID           | Check                                       | Priority | Method                    |
| ------------ | ------------------------------------------- | -------- | ------------------------- |
| CONFIG-007   | Agent instructions present and substantive  | Critical | Parse `agent.mcs.yml`     |
| CONFIG-005   | Starter prompts configured (recommend 6-12) | High     | Parse `agent.mcs.yml`     |
| CONFIG-012   | User Context variables exist                | Critical | Scan `variables/`         |
| TOPIC-001    | [Admin] User Context - Setup topic exists   | Critical | Scan `topics/`            |
| TOPIC-002    | [System] Response Preparation topic exists  | Critical | Scan `topics/`            |
| TOPIC-004    | [Example] Sensitive Topics exists           | High     | Scan `topics/`            |
| TOPIC-005    | [System] On Error topic exists              | High     | Scan `topics/`            |
| TOPIC-009    | Emotional Intelligence topic exists         | High     | Scan `topics/`            |
| TOPIC-010    | Ambiguity Clarification topic exists        | High     | Scan `topics/`            |
| TOPIC-011    | Topic inventory count                       | Medium   | Count `topics/*.mcs.yml`  |
| LOCAL-TC-001 | Template configuration inventory            | Medium   | Count `template-configs/` |

## 5b. ServiceNow Deep Validation (SN-xxx)

| ID           | Check                                          | Priority | Method         | Doc Link                                                                                               |
| ------------ | ---------------------------------------------- | -------- | -------------- | ------------------------------------------------------------------------------------------------------ |
| SN-CONN-001  | ServiceNow connections summary                 | High     | PP Admin API   | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-CONN-nnn  | Individual connection status                   | High     | PP Admin API   | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-FLOW-000  | ServiceNow flow status summary                 | High     | PP Admin API   | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-FLOW-nnn  | Individual flow enabled/disabled (HRSD/ITSM)   | High     | PP Admin API   | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-CFG-001   | ServiceNow template configs exist in Dataverse | High     | Dataverse REST | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-CFG-010   | HRSD expected template configs present         | Medium   | Dataverse REST | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-CFG-020   | ITSM expected template configs present         | Medium   | Dataverse REST | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-LOCAL-001 | ServiceNow topics present in local agent files | Medium   | Scan `topics/` | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-LOCAL-002 | HRSD topics present                            | Medium   | Scan `topics/` | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-LOCAL-003 | ITSM topics present                            | Medium   | Scan `topics/` | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |

## 6.5. Cloud Policies / Telemetry & Feedback (POL-FB-xxx)

These checkpoints validate the two Microsoft 365 Cloud Policies (Office Cloud
Policy Service, managed in the Microsoft 365 Apps admin center → Policy
Management → Cloud policies) that gate end-user Copilot feedback — the primary
closed-loop signal for product quality, IcM correlation, and the FlightCheck
Trend Miner. Cloud Policy is admin-controlled, so these are IT-admin scope.

| ID         | Check                                                                                                                                         | Priority | Method                         | Doc Link                                                                                                         |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| POL-FB-001 | Cloud Policy "Allow users to send feedback to Microsoft about Microsoft 365 apps" Enabled for the ESS deployment group                        | High     | Manual (no supported OCPS API) | [overview-cloud-policy](https://learn.microsoft.com/en-us/microsoft-365-apps/admin-center/overview-cloud-policy) |
| POL-FB-002 | Cloud Policy "Allow users to include screenshots and attachments when they submit feedback to Microsoft" Enabled for the ESS deployment group | High     | Manual (no supported OCPS API) | [overview-cloud-policy](https://learn.microsoft.com/en-us/microsoft-365-apps/admin-center/overview-cloud-policy) |

**Why manual:** The Office Cloud Policy Service has no GA / publicly-documented
API for reading effective per-security-group feedback policy state, and its
admin-center backend rejects a service-acquired token. So these checkpoints are
`Manual` (they don't fail readiness): FlightCheck names the exact policies, deep
-links to the Microsoft 365 Apps admin center, emits the role-aware deployment
directive, and emits the **verbatim maker-facing data-sharing notice** (see the
[remediation guide](./remediation-guide.md#cloud-policies--telemetry--feedback)).
The operator confirms the effective per-group state in the portal.

## 7. Publishing & QA (Manual Checklist)

| ID      | Check                                 | Priority | Method |
| ------- | ------------------------------------- | -------- | ------ |
| QA-001  | Golden prompts library (50+ prompts)  | Critical | Manual |
| QA-002  | Core functionality prompts tested     | Critical | Manual |
| QA-012  | Accuracy validation completed         | Critical | Manual |
| PUB-001 | Solution exported as managed          | Critical | Manual |
| PUB-002 | Test environment deployment completed | Critical | Manual |
| PUB-003 | UAT testing completed with sign-off   | Critical | Manual |
| PUB-006 | Microsoft 365 admin approval obtained | Critical | Manual |
| PUB-011 | Publishing delay expected (48 hrs)    | Medium   | Manual |

---

## 8. Infrastructure & Security

| ID        | Check                                                                                                               | Priority | Method                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | PASS                                                                  | FAIL                                                                                                       | WARN                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| --------- | ------------------------------------------------------------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| INFRA-001 | Inbound connectivity to Microsoft services                                                                          | Critical | TCP probe (DNS → TCP → TLS) to required Microsoft endpoints (Entra ID, Power Platform, Dataverse, Copilot Studio, Graph)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | All endpoints reachable with valid TLS                                | Any Microsoft endpoint unreachable (DNS failure, TCP timeout, connection refused)                          | TLS handshake failure (proxy interception, certificate issue)                                                                                                                                                                                                                                                                                                                                                                                                     |
| INFRA-002 | HR system reachability from the maker's machine                                                                     | High     | Layer-by-layer DNS → TCP → TLS probe (`probe_endpoint()`) to each configured external system host, run locally. Accuracy MEDIUM: a FAIL is always meaningful, a PASS is necessary but not sufficient (the maker's network path differs from Power Platform's egress)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | Host reachable with valid TLS                                         | Host unreachable (DNS failure or connection refused)                                                       | TCP timeout, TLS handshake failure, or endpoint URL unverifiable                                                                                                                                                                                                                                                                                                                                                                                                  |
| INFRA-003 | External endpoint reachability from Power Platform egress                                                           | Critical | Enumerate external endpoints (Workday / ServiceNow / SAP SuccessFactors / custom HTTP) from the agent's connection config. Reachability is verified only from Power Platform's own egress via the opt-in, consent-gated `--runtime-reachability` probe: a transient cloud flow (Dataverse `workflow` row) sends one real HTTP request from the environment's egress, then is deleted — the kit's only mutating tenant path, with guaranteed cleanup and orphan sweep. When the probe is not run (flag omitted/declined or prerequisites missing) the check returns MANUAL guidance; there is no local TCP/TLS fallback (a laptop probe runs from the wrong network and cannot prove the runtime path). Read-only and idempotent by default | All enumerated endpoints reachable                                    | Any endpoint unreachable (DNS failure or connection refused) — names the endpoint URL and the blocking hop | Unverifiable endpoint (no recorded URL) or an indeterminate egress probe; also returns MANUAL guidance when the probe is not run (flag omitted/declined or prerequisites missing)                                                                                                                                                                                                                                                                                 |
| INFRA-006 | DLP policies permit every agent connector (classic data policies; ACP / custom-connector URL patterns out of scope) | Critical | Power Platform Admin API (apiPolicies) + Dataverse connection references; reconciles each agent connector against effective DLP connector groups (most-restrictive policy wins)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | All agent connectors allowed and in the same data-group, none Blocked | Any required connector Blocked                                                                             | Connectors allowed but split across data-groups (cross-group) — all allowed, but can't be combined in one agent action; or some connectors not explicitly classified AND no default group is known (legacy `connectorGroups` policies; modern `definition.apiGroups` policies resolve unlisted connectors via `defaultApiGroup`), or classification could not be determined (permissions / Dataverse unreadable). No policy → SKIPPED (coverage owned by ENV-008) |

---

## Running FlightCheck

```bash
# Full validation
python scripts/flightcheck/cli.py --scope full

# Workday-specific
python scripts/flightcheck/cli.py --scope workday

# ServiceNow-specific
python scripts/flightcheck/cli.py --scope servicenow

# Local files only (no API calls)
python scripts/flightcheck/cli.py --scope local

# Prerequisites only
python scripts/flightcheck/cli.py --scope prerequisites
```

Or use the `/flightcheck` command in the Copilot Kit.

### Single-checkpoint invocation

In addition to broad `--scope` runs, FlightCheck can run **exactly one
checkpoint** (or one dynamic family) so a setup skill can verify just the
atomic outcome it produced, immediately after the step that produces it.

```bash
# List the setup checkpoints/families available for single-checkpoint runs
python scripts/flightcheck/cli.py --list-checkpoints

# Run one checkpoint (plus only the prerequisites needed to hydrate it)
python scripts/flightcheck/cli.py --checkpoint WD-CONN-102

# Run a dynamic family (every emitted ID under the prefix)
python scripts/flightcheck/cli.py --checkpoint WD-FLOW
```

Behavior:

- **`--list-checkpoints`** prints the registered, listable checkpoint IDs and
  families (families shown with a trailing `*`, e.g. `WD-FLOW-*`) with their
  category, priority, and role(s), then exits without running anything.
- **`--checkpoint <ID>`** resolves the ID (exact entry first, otherwise the
  longest-matching family prefix), runs the owning category function plus the
  transitive prerequisites required to hydrate shared runner state, then
  reports **only** the target result. It initializes **only** the clients the
  checkpoint declares — an Entra-only checkpoint such as `WD-CONN-102` runs
  with Microsoft Graph alone and needs no Dataverse endpoint configured, while
  a Dataverse-backed checkpoint such as `WD-PKG-001` requires it.
- A checkpoint that is `Manual` reports `MANUAL` and exits `0` (manual results
  never count as failures).
- An unknown ID exits non-zero and prints the list of valid checkpoint IDs.
- `--checkpoint` and `--scope` are **mutually exclusive**; passing both is an
  error. Omitting both runs the full scope, exactly as before (additive — no
  existing `--scope` behavior changes).

The set of selectable checkpoint IDs is defined by the FlightCheck registry
(`scripts/flightcheck/registry.py`). That registry, rather than an installation
checklist, is the source of truth for runnable IDs.

---

## Historical CEA Workday checkpoint catalog (reference only)

This catalog records checkpoint provenance from the retired CEA setup flow.
The `Skill` and `Step(s)` columns are historical labels, not runnable skill
paths or current installation instructions. The old playbooks and master
checklist are not shipped on this DA-only branch. Current DA Workday guidance
is in `src/skills/connect/workday/SKILL.md`; CEA Connect belongs on `main-ca`.

> Consult `scripts/flightcheck/registry.py` for each ID's current implementation
> and availability. Inclusion in this historical table does not prove an ID is
> runnable or applicable to DA.

`Origin`: **reuse** = the checkpoint predates this flow and is simplified-aware;
**mint** = introduced by the named historical skill. `Gate` records the old
check category; it is not an active DA permission gate.

| Checkpoint             | Origin | Skill            | Step(s)    | Gate                     | What it verifies                                                                                                    |
| ---------------------- | ------ | ---------------- | ---------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `ENV-001`              | reuse  | skill-1          | S1.1       | prog                     | Power Platform environment exists                                                                                   |
| `ENV-002`              | reuse  | skill-1          | S1.1       | prog                     | Dataverse database provisioned                                                                                      |
| `ENV-CAPACITY-001`     | mint   | skill-1          | S1.2       | prog, else attest        | Copilot Studio capacity available                                                                                   |
| `ESS-SOLN-001`         | mint   | skill-2          | S2.1       | prog                     | ESS base solution (`msdyn_copilotforemployeeselfservice*`) installed                                                |
| `WD-ENTRA-SCOPE-001`   | mint   | skill-3          | S3.2       | prog                     | `user_impersonation` exposed, `4e4707ca` pre-authorized, Graph perms granted                                        |
| `WD-ENTRA-CONSENT-001` | mint   | skill-3          | S3.3       | prog → manual if blocked | Admin consent on the Graph delegated perms                                                                          |
| `WD-ASSIGN-001`        | mint   | skill-3          | S3.4       | prog                     | Enterprise-app user/group assignment (or confirmed not required)                                                    |
| `WD-CONN-102`          | reuse  | skill-3, skill-4 | S3.1, S4.4 | manual/attest            | SAML signing-certificate health / certificate parity (returns `MANUAL`)                                             |
| `WD-ENTRA-NAMEID-001`  | mint   | skill-3          | S3.5       | prog → manual if brittle | NameID claim mapping (`claimsMappingPolicy`)                                                                        |
| `WD-ENTRA-SIGNOPT-001` | mint   | skill-3          | S3.6       | manual                   | "Sign SAML response and assertion" signing option (portal-only)                                                     |
| `WD-CONN-010`          | reuse  | skill-3          | S3.7       | attest                   | Single-Entra-tenant federation alignment                                                                            |
| `WD-API-CLIENT-001`    | mint   | skill-4          | S4.1       | attest                   | Workday API client registered (functional areas + Workday-owned scope)                                              |
| `WD-TENANT-001`        | mint   | skill-4          | S4.2, S4.3 | attest                   | Connection fields captured; auth policies scoped to the OAuth client                                                |
| `WD-PKG-001`           | reuse  | skill-5          | S5.1       | manual                   | Extension-pack flavor = `simplified` (exact `ff0df` or `msdyn_EssWorkdayRuntime` reference shape)                   |
| `WD-CONN-012`          | reuse  | skill-5          | S5.2       | prog                     | Workday connection ref (`ff0df` or `msdyn_sharedworkdaysoap_workdayruntime`) bound, own account                     |
| `WD-CONN-AUTH-001`     | mint   | skill-5          | S5.3       | attest                   | Connection auth type = Entra ID Integrated (echoes `MANUAL`; see §3d reconciliation)                                |
| `DV-CONN-001`          | mint   | skill-5          | S5.4       | prog                     | Dataverse connection (`92b66` or `msdyn_sharedcommondataserviceforapps_workdayruntime`) bound — **non-`WD` family** |
| `WD-REST-001`          | mint   | skill-5          | S5.5       | prog                     | REST base URL present and trimmed to `/api`                                                                         |
| `WD-FLOW-*`            | reuse  | skill-5          | S5.6       | prog                     | Cloud flows on (one row per discovered flow)                                                                        |
| `WD-REST-002`          | mint   | skill-5          | S5.7       | prog w/ rollback         | User-context redirect pushed → REST resolves `/workers/me`                                                          |
| `WD-NET-001`           | mint   | skill-5          | S5.8       | attest                   | Firewall allowlisting (REST + SOAP) — InfoSec attestation                                                           |
| `TOPIC-TRIGGER-*`      | mint   | skill-6          | S6.1       | prog                     | New-topic trigger phrases + definition (one row per topic)                                                          |
| `TOPIC-INTEGRATION-*`  | mint   | skill-6          | S6.2       | prog                     | New-topic integration wiring (one row per topic)                                                                    |

**Notes**

- **The Dataverse reference is not a Workday ref.** The simplified family
  fingerprints `ff0df`; the runtime package fingerprints
  `msdyn_sharedworkdaysoap_workdayruntime`. Their corresponding Dataverse
  references (`92b66` or
  `msdyn_sharedcommondataserviceforapps_workdayruntime`) are verified under
  the non-`WD` ID `DV-CONN-001`, never as a second `WD-CONN` ref.
- **Legacy `WD-ENV-*` / `WD-WF-*` are not reused for simplified.** They test
  ISU/RaaS artifacts that simplified setup removes (reusing them yields false
  failures / N/A noise); the families are registered only so the registry resolves
  them. The new simplified-only IDs above are used instead.
- **Reuse before minting.** New IDs are minted only for outputs no existing
  simplified-aware checkpoint covers.
