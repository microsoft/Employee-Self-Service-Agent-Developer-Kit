# ESS FlightCheck — Validation Matrix

Comprehensive catalog of all pre-deployment validation checkpoints. Each
check has an ID, category, priority, automated/manual classification, and
a link to the relevant Microsoft Learn documentation.

Ported from the ESS Pre-flight Validator (JohnQuinn-Dev/ess-preflight-validator)
and extended with local file validation checks unique to the Copilot Kit.

---

## Priority Levels

| Level | Meaning |
|-------|---------|
| Critical | Must pass before proceeding to deployment |
| High | Should pass; requires remediation plan if fails |
| Medium | Important but can be addressed post-deployment |
| Low | Nice-to-have; optional configuration |

## Roles (next-step owner)

Every actionable result (Failed, Error, Warning, Manual, or
NotConfigured) is tagged with one or more **roles** — the admin
persona(s) who must take the next action to fix it or perform the
manual validation. The role(s) appear as a "Role" column in the HTML
report and `results.json`, and on the terminal action/manual rows.
Passed and Skipped rows have no next step, so no role is shown.

| Role | Acts in… |
|------|----------|
| Entra Admin | Entra ID: app registrations, SAML, conditional access, directory-role assignment |
| Microsoft 365 Admin | M365 admin center: license assignment, Office Cloud Policies, Graph connectors, Integrated-apps approval |
| Power Platform Admin | Power Platform: environments, DLP, connections, solution import, cloud-flow state, Dataverse env vars |
| Workday Admin | The Workday tenant: ISU accounts, security groups, domain permissions, RaaS, auth policies |
| ServiceNow Admin | The ServiceNow instance: service accounts, roles, ACLs |
| SAP Admin | The SAP SuccessFactors tenant |
| ESS Maker / Agent Developer | Local agent files: topics, variables, template configs, evaluations, publishing/QA gates |

A check can carry more than one role when the fix spans systems (e.g.
WD-CONN-102's SAML cert lives on the Entra app but is compared in
Workday → Entra Admin + Workday Admin).


---

## 1. Prerequisites (PRE-xxx)

| ID | Check | Priority | Method | Doc Link |
|----|-------|----------|--------|----------|
| PRE-001 | Microsoft 365 Copilot licenses assigned | Critical | Graph API `/subscribedSkus` | [prerequisites#licensing](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#licensing) |
| PRE-002 | Copilot Studio licenses for admins/makers | Critical | Graph API `/subscribedSkus` | [prerequisites#licensing](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#licensing) |
| PRE-003 | Microsoft Teams licenses for users | Critical | Graph API `/subscribedSkus` | [prerequisites#licensing](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#licensing) |
| PRE-004 | Copilot Studio capacity configured (sufficient for the shared/published user population) | Critical | Power Platform Licensing API (per-environment currency allocation) + Dataverse sharing enumeration; cross-checks PRE-005 PayG | [requirements-messages-management#prepaid-capacity](https://learn.microsoft.com/en-us/microsoft-copilot-studio/requirements-messages-management?tabs=new#prepaid-capacity) |
| PRE-008 | Global Admin role assigned | Critical | Graph API `/directoryRoles` | [prerequisites#required-roles](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#required-roles) |
| PRE-009 | Power Platform Admin role assigned | Critical | Graph API `/directoryRoles` | [prerequisites#required-roles](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#required-roles) |

## 2. Environment Configuration (ENV-xxx)

| ID | Check | Priority | Method | Doc Link |
|----|-------|----------|--------|----------|
| ENV-001 | Power Platform environment exists | Critical | BAP Admin API | [prepare#set-up-your-power-platform-environment](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prepare#set-up-your-power-platform-environment) |
| ENV-002 | Dataverse database provisioned | Critical | BAP Admin API | [prepare#set-up-your-power-platform-environment](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prepare#set-up-your-power-platform-environment) |
| ENV-003 | Environment type | High | BAP Admin API | [prepare#set-up-your-power-platform-environment](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prepare#set-up-your-power-platform-environment) |
| ENV-004 | Connections & connection references — binding + orphan detection, scoped to the references the ESS agent's enabled topics actually use (resolved via topic InvokeFlowAction flowIds → cloud flow `connectionReferences`). Skips when that scope can't be resolved; warns on a flow-listing API error. | High | BAP Admin API + Dataverse REST | [prepare#set-up-your-power-platform-environment](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prepare#set-up-your-power-platform-environment) |
| ENV-004-OR-nnn | Orphan reference (in-scope reference points to a missing connection) | High | — | — |
| ENV-004-UR-nnn | Unbound reference (in-scope reference has no connection bound) | High | — | — |
| ENV-004-MR-nnn | Missing reference (agent flow uses a connection reference that does not exist in the environment) | High | — | — |
| ENV-004-UC-nnn | Unbound connection (no in-scope reference uses it; limited to the agent's connectors) | Medium | — | — |
| ENV-CAPACITY-001 | Copilot Studio message capacity provisioned | Critical | Power Platform Licensing API | [requirements-messages-management#prepaid-capacity](https://learn.microsoft.com/en-us/microsoft-copilot-studio/requirements-messages-management?tabs=new#prepaid-capacity) |
| ENV-008 | DLP policies configured | High | BAP Admin API | [prepare#allow-the-external-systems-connector](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prepare#allow-the-external-systems-connector) |

## 2b. ESS Solution Installation (ESS-SOLN-xxx)

| ID | Check | Priority | Role | Gate | Method | Doc Link |
|----|-------|----------|------|------|--------|----------|
| ESS-SOLN-001 | ESS base agent solution (`msdyn_copilotforemployeeselfservice*`) installed | Critical | Environment Maker | prog | Dataverse REST (`solutions`) | [install](https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/install) |

## 3. Authentication & Identity (AUTH-xxx)

| ID | Check | Priority | Method | Doc Link |
|----|-------|----------|--------|----------|
| AUTH-001 | Microsoft Entra ID configured | Critical | Graph API `/organization` | [prerequisites#identity-authentication-and-single-sign-on-sso](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#identity-authentication-and-single-sign-on-sso) |
| AUTH-002 | Conditional Access policies | High | Graph API `/identity/conditionalAccess/policies` | [prerequisites#identity-authentication-and-single-sign-on-sso](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#identity-authentication-and-single-sign-on-sso) |
| AUTH-004 | User identity synchronization | High | Graph API `/users` | [prerequisites#identity-authentication-and-single-sign-on-sso](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#identity-authentication-and-single-sign-on-sso) |

## 3b. Entra App Provisioning (WD-ENTRA-xxx / WD-ASSIGN-xxx)

Minted by **skill-3** (`provision-workday-entra-app`) and runnable in isolation
via `--checkpoint`. These configure the Workday SSO/OBO Entra app; the app is
discovered by its gallery `applicationTemplateId` (rename-proof), so the config
`entraAppId` / `entraAppObjectId` are optional hints only. All are Entra-only
(Microsoft Graph) — none needs a Dataverse endpoint. See the setup catalog below
for the owning checklist rows (S3.1–S3.7).

| ID | Check | Priority | Method | Doc Link |
|----|-------|----------|--------|----------|
| WD-ENTRA-SCOPE-001 | `user_impersonation` exposed, Workday connector (`4e4707ca`) pre-authorized, Graph delegated perms (openid/profile/User.Read) requested | Critical | Graph `/applications` (`api.oauth2PermissionScopes`, `api.preAuthorizedApplications`, `requiredResourceAccess`) | [workday-tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial) |
| WD-ENTRA-CONSENT-001 | Tenant-wide admin consent (`AllPrincipals` grant) covers the Graph delegated perms | Critical | Graph `/oauth2PermissionGrants` | [workday-tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial) |
| WD-ASSIGN-001 | Enterprise-app user/group assignment (or confirmed not required). Shares logic with `AUTH-005`. | Critical | Graph `/servicePrincipals/{id}/appRoleAssignedTo` | [workday-tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial) |
| WD-ENTRA-NAMEID-001 | `claimsMappingPolicy` overriding the SAML NameID claim is assigned (degrades to `MANUAL` when the policy route is unreadable) | High | Graph `/servicePrincipals/{id}/claimsMappingPolicies` | [workday-tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial) |
| WD-ENTRA-SIGNOPT-001 | "Sign SAML response and assertion" signing option — portal-only, always returns `MANUAL` | High | None (portal attestation; no Graph property) | [workday-tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial) |

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

| ID | Check | Priority | Method | Doc Link |
|----|-------|----------|--------|----------|
| WD-API-CLIENT-001 | Workday API client registered — SAML ****** grant, functional areas (Core Payroll, Organizations and Roles, Staffing, Time Off and Leave), Include Workday Owned Scope = Yes. Echoes captured `oauthClientId` / `tokenEndpoint`. | Critical | None (attestation; echoes captured config) | [workday-tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial) |
| WD-TENANT-001 | Tenant Setup – Security (redirect URL, OAuth 2.0 Clients + SAML enabled, Service Provider ID matches Entra Identifier) and authentication policy scoped to the OAuth client + activated. Echoes captured `restBaseUrl` / `soapBaseUrl` / `tenant` / `appIdUri`. | High | None (attestation; echoes captured config) | [workday-tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial) |

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

| ID | Check | Priority | Method | Doc Link |
|----|-------|----------|--------|----------|
| WD-CONN-AUTH-001 | Workday connection authentication is **Microsoft Entra ID Integrated**. Reads the cached Workday (`ff0df`) reference and echoes the observed `connectionParametersSet.name` + owner from the Power Platform admin connection. **Always `MANUAL`** — the admin API exposes no kit-verifiable fingerprint for the "Microsoft Entra ID Integrated" auth type, so this echoes for operator confirmation rather than PASS/FAIL (see reconciliation note below). | High | Power Platform admin connections (echo only) | [workday-simplified-setup](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday-simplified-setup) |
| DV-CONN-001 | ESS Dataverse connection reference (`…_92b66`, connector `shared_commondataserviceforapps`) bound to an **active** connection; echoes the owner so the operator can confirm it is their own account. Programmatic PASS/FAIL on a documented-tier Dataverse `connectionreferences` read. **Non-`WD` family.** | High | Dataverse `connectionreferences` (+ PP admin owner echo) | [workday-simplified-setup](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday-simplified-setup) |
| WD-REST-001 | Captured `restBaseUrl` is present and **trimmed to** `/api`. Pure-config check — no client. | High | None (reads captured config) | [workday-simplified-setup](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday-simplified-setup) |
| WD-REST-002 | Agent's `user-context-setup.mcs.yml` topic contains a `BeginDialog` redirect to the Workday user-context system topic (`WorkdaySystemGetUserContextV2` on the simplified pack). Pure local-file check; `SKIPPED` on the legacy install path. | High | None (reads local agent YAML) | [workday-simplified-setup](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday-simplified-setup) |
| WD-NET-001 | Workday REST + SOAP endpoints allowlisted at the corporate firewall for the Power Platform managed connectors. **Always `MANUAL`** — the kit has no reliable probe (a local reachability test proves only the dev machine's egress, not the managed-connector outbound path), so it echoes the endpoints InfoSec/IT must allowlist. | High | None (InfoSec/IT attestation; echoes captured hosts) | [workday-simplified-setup](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday-simplified-setup) |

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

| ID | Check | Priority | Method | Doc Link |
|----|-------|----------|--------|----------|
| TOPIC-TRIGGER-* | Each new topic is a well-formed `kind: AdaptiveDialog` **and** has a trigger (a `beginDialog` with `OnRecognizedIntent`/`OnRedirect`/…); an intent-routed topic additionally needs trigger phrases (`modelDescription` content or `triggerQueries`). Programmatic PASS/FAIL per topic. | High | None (reads local agent topic YAML vs `.baseline/`) | [workday#topics](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#topics) |
| TOPIC-INTEGRATION-* | Each new topic's integration wiring resolves — no unresolved `{{PLACEHOLDER}}` scaffolding or `<UPPERCASE>` tenant reference-ID tokens (e.g. `<TENANT_NAME>`) remain. A topic with no external wiring is a benign PASS. Programmatic PASS/FAIL on placeholder resolution only. | High | None (reads local agent topic YAML vs `.baseline/`) | [workday#topics](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#topics) |

> **Gate note (S6.2).** `TOPIC-INTEGRATION-*` is a `prog (+ SME for IDs)` row.
> The checkpoint proves the placeholder tokens were **resolved**, but the kit
> cannot validate that each wired tenant reference-ID *value* (e.g. the Time Off
> Type ID) is correct against the live Workday instance — that would require a
> Workday API read the check deliberately avoids (pure local-file). Per the
> cardinal rule in
> [`scripts/flightcheck/AGENTS.md`](../../../../scripts/flightcheck/AGENTS.md),
> the checkpoint asserts only what it can prove; S6.2 therefore also carries a
> **Workday SME attestation** that the reference-ID values are correct, captured
> in the skill-6 playbook (P6.4). A checkpoint PASS is necessary but not
> sufficient for the row to complete.

## 4. External Systems Discovery

| ID | Check | Priority | Method | Doc Link |
|----|-------|----------|--------|----------|
| WD-001 | Workday solution installed | High | PP Admin API (flow scan) | [workday](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday) |
| SN-001 | ServiceNow solution installed | High | PP Admin API (flow scan) | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SAP-001 | SAP SuccessFactors solution installed | High | PP Admin API (flow scan) | [sap-successfactors](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/sap-successfactors) |

## 5. Workday Deep Validation (WD-xxx)

| ID | Check | Priority | Method | Doc Link |
|----|-------|----------|--------|----------|
| WD-ENV-001 | EmployeeContextRequestAccountName configured | Critical | Dataverse REST | [workday#step-4-environment-variables](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#step-4-environment-variables) |
| WD-ENV-002 | EmployeeContextRequestReportName verified | High | Dataverse REST | [workday#step-4-environment-variables](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#step-4-environment-variables) |
| WD-ENV-003 | EmployeeContextRequestReportInstanceName verified | High | Dataverse REST | [workday#step-4-environment-variables](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#step-4-environment-variables) |
| WD-CONN-001 | Workday connections summary | High | PP Admin API | [workday#step-3-connection-references](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#step-3-connection-references) |
| WD-CONN-nnn | Individual connection status | High | PP Admin API | [workday#step-3-connection-references](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#step-3-connection-references) |
| WD-CONN-102 | Workday SAML signing certificate health (Entra-automated, Workday-manual comparison) | High | Microsoft Graph (servicePrincipal.keyCredentials) | [workday#task-1-create-the-x509-public-key](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#task-1-create-the-x509-public-key) |
| WD-FLOW-nnn | Individual flow enabled/disabled | High | PP Admin API | [workday#topics](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday#topics) |
| WD-SEC-003 | Personal Data domain write permission (Employee as Self). See [remediation guide](./remediation-guide.md#wd-sec-003-personal-data-domain-write-permission-employee-as-self) for full details. | High | Workday SOAP runtime probe + MANUAL fallback | [workday](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday) |

### Workday SOAP Workflow Tests (WD-WF-xxx)

Tests all 17 ESS pre-configured workflows against the Workday API. Requires ISU credentials.

| ID | Workflow | Service | Type | PII | Security Domain |
|----|----------|---------|------|-----|-----------------|
| WD-WF-001 | Employee ID | Human_Resources | Read | | Worker Profile |
| WD-WF-002 | Company Code | Human_Resources | Read | | Organizations |
| WD-WF-003 | Cost Center | Human_Resources | Read | | Organizations |
| WD-WF-004 | Hire Date | Human_Resources | Read | | Worker Profile |
| WD-WF-005 | Employment Info | Human_Resources | Read | | Worker Profile |
| WD-WF-006 | Position Number | Human_Resources | Read | | Worker Profile |
| WD-WF-007 | Service Anniversary | Human_Resources | Read | | Worker Profile |
| WD-WF-008 | National IDs | Human_Resources | Read | ⚠️ | Personal Data |
| WD-WF-009 | Passports | Human_Resources | Read | ⚠️ | Personal Data |
| WD-WF-010 | Visas | Human_Resources | Read | ⚠️ | Personal Data |
| WD-WF-011 | Language Info | Human_Resources | Read | | Qualifications |
| WD-WF-012 | Certifications | Human_Resources | Read | | Qualifications |
| WD-WF-013 | Base Compensation | Compensation | Read | | Compensation |
| WD-WF-014 | Compensation Ratio | Compensation | Read | | Compensation |
| WD-WF-015 | Emergency Contact | Human_Resources | Read | ⚠️ | Personal Data |
| WD-WF-016 | Update Email | Human_Resources | Write | | Contact Information (see WD-SEC-003 for the precise Personal Data + Maintain Contact Information / Edit Worker Additional Data check) |
| WD-WF-017 | Update Phone | Human_Resources | Write | | Contact Information (see WD-SEC-003 for the precise Personal Data + Maintain Contact Information / Edit Worker Additional Data check) |

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

| ID | Check | Priority | Method | Doc Link |
|----|-------|----------|--------|----------|
| WD-WF-CAT-001 | Workday custom-workflow inventory checklist (MANUAL) | High | Local file walk + Dataverse managed-template-config diff (SKIP on no token, WARN on query error) | [workday-extensibility](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday-extensibility) |
| WD-WF-CAT-LINK | Cross-link trailer surfacing WD-WF-CAT-001 from inside the SOAP-test block | Medium | Computed from WD-WF-CAT-001 cache | [workday-extensibility](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/workday-extensibility) |

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

| ID | Check | Priority | Method |
|----|-------|----------|--------|
| CONFIG-007 | Agent instructions present and substantive | Critical | Parse `agent.mcs.yml` |
| CONFIG-005 | Starter prompts configured (recommend 6-12) | High | Parse `agent.mcs.yml` |
| CONFIG-012 | User Context variables exist | Critical | Scan `variables/` |
| TOPIC-001 | [Admin] User Context - Setup topic exists | Critical | Scan `topics/` |
| TOPIC-002 | [System] Response Preparation topic exists | Critical | Scan `topics/` |
| TOPIC-004 | [Example] Sensitive Topics exists | High | Scan `topics/` |
| TOPIC-005 | [System] On Error topic exists | High | Scan `topics/` |
| TOPIC-009 | Emotional Intelligence topic exists | High | Scan `topics/` |
| TOPIC-010 | Ambiguity Clarification topic exists | High | Scan `topics/` |
| TOPIC-011 | Topic inventory count | Medium | Count `topics/*.mcs.yml` |
| LOCAL-TC-001 | Template configuration inventory | Medium | Count `template-configs/` |

## 5b. ServiceNow Deep Validation (SN-xxx)

| ID | Check | Priority | Method | Doc Link |
|----|-------|----------|--------|----------|
| SN-CONN-001 | ServiceNow connections summary | High | PP Admin API | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-CONN-nnn | Individual connection status | High | PP Admin API | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-FLOW-000 | ServiceNow flow status summary | High | PP Admin API | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-FLOW-nnn | Individual flow enabled/disabled (HRSD/ITSM) | High | PP Admin API | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-CFG-001 | ServiceNow template configs exist in Dataverse | High | Dataverse REST | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-CFG-010 | HRSD expected template configs present | Medium | Dataverse REST | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-CFG-020 | ITSM expected template configs present | Medium | Dataverse REST | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-LOCAL-001 | ServiceNow topics present in local agent files | Medium | Scan `topics/` | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-LOCAL-002 | HRSD topics present | Medium | Scan `topics/` | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |
| SN-LOCAL-003 | ITSM topics present | Medium | Scan `topics/` | [servicenow](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/servicenow) |

## 6.5. Cloud Policies / Telemetry & Feedback (POL-FB-xxx)

These checkpoints validate the two Microsoft 365 Cloud Policies (Office Cloud
Policy Service, managed in the Microsoft 365 Apps admin center → Policy
Management → Cloud policies) that gate end-user Copilot feedback — the primary
closed-loop signal for product quality, IcM correlation, and the FlightCheck
Trend Miner. Cloud Policy is admin-controlled, so these are IT-admin scope.

| ID | Check | Priority | Method | Doc Link |
|----|-------|----------|--------|----------|
| POL-FB-001 | Cloud Policy "Allow users to send feedback to Microsoft about Microsoft 365 apps" Enabled for the ESS deployment group | High | Manual (no supported OCPS API) | [overview-cloud-policy](https://learn.microsoft.com/en-us/microsoft-365-apps/admin-center/overview-cloud-policy) |
| POL-FB-002 | Cloud Policy "Allow users to include screenshots and attachments when they submit feedback to Microsoft" Enabled for the ESS deployment group | High | Manual (no supported OCPS API) | [overview-cloud-policy](https://learn.microsoft.com/en-us/microsoft-365-apps/admin-center/overview-cloud-policy) |

**Why manual:** The Office Cloud Policy Service has no GA / publicly-documented
API for reading effective per-security-group feedback policy state, and its
admin-center backend rejects a service-acquired token. So these checkpoints are
`Manual` (they don't fail readiness): FlightCheck names the exact policies, deep
-links to the Microsoft 365 Apps admin center, emits the role-aware deployment
directive, and emits the **verbatim maker-facing data-sharing notice** (see the
[remediation guide](./remediation-guide.md#cloud-policies--telemetry--feedback)).
The operator confirms the effective per-group state in the portal.

## 7. Publishing & QA (Manual Checklist)

| ID | Check | Priority | Method |
|----|-------|----------|--------|
| QA-001 | Golden prompts library (50+ prompts) | Critical | Manual |
| QA-002 | Core functionality prompts tested | Critical | Manual |
| QA-012 | Accuracy validation completed | Critical | Manual |
| PUB-001 | Solution exported as managed | Critical | Manual |
| PUB-002 | Test environment deployment completed | Critical | Manual |
| PUB-003 | UAT testing completed with sign-off | Critical | Manual |
| PUB-006 | Microsoft 365 admin approval obtained | Critical | Manual |
| PUB-011 | Publishing delay expected (48 hrs) | Medium | Manual |

---

## 8. Infrastructure & Security

| ID | Check | Priority | Method | PASS | FAIL | WARN |
|----|-------|----------|--------|------|------|------|
| INFRA-001 | Inbound connectivity to Microsoft services | Critical | TCP probe (DNS → TCP → TLS) to required Microsoft endpoints (Entra ID, Power Platform, Dataverse, Copilot Studio, Graph) | All endpoints reachable with valid TLS | Any Microsoft endpoint unreachable (DNS failure, TCP timeout, connection refused) | TLS handshake failure (proxy interception, certificate issue) |
| INFRA-002 | HR system reachability from the maker's machine | High | Layer-by-layer DNS → TCP → TLS probe (`probe_endpoint()`) to each configured external system host, run locally. Accuracy MEDIUM: a FAIL is always meaningful, a PASS is necessary but not sufficient (the maker's network path differs from Power Platform's egress) | Host reachable with valid TLS | Host unreachable (DNS failure or connection refused) | TCP timeout, TLS handshake failure, or endpoint URL unverifiable |
| INFRA-003 | External endpoint reachability from Power Platform egress | Critical | Enumerate external endpoints (Workday / ServiceNow / SAP SuccessFactors / custom HTTP) from the agent's connection config. Default path: read-only local TCP/TLS probe (shares INFRA-002's `probe_endpoint()`), bucketed by status. Live path (opt-in `--runtime-reachability`, consent-gated): a transient cloud flow (Dataverse `workflow` row) probes from Power Platform's own egress, then is deleted — the kit's only mutating path, with guaranteed cleanup and orphan sweep. Read-only and idempotent by default | All enumerated endpoints reachable | Any endpoint unreachable (DNS failure or connection refused) — names the endpoint URL and the blocking hop | Timeout, TLS failure, or unverifiable endpoint; also emitted when the live egress probe is requested but unavailable and the local probe was used |
| INFRA-006 | DLP policies permit every agent connector (classic data policies; ACP / custom-connector URL patterns out of scope) | Critical | Power Platform Admin API (apiPolicies) + Dataverse connection references; reconciles each agent connector against effective DLP connector groups (most-restrictive policy wins) | All agent connectors allowed and in the same data-group, none Blocked | Any required connector Blocked | Connectors allowed but split across data-groups (cross-group) — all allowed, but can't be combined in one agent action; or some connectors not explicitly classified AND no default group is known (legacy `connectorGroups` policies; modern `definition.apiGroups` policies resolve unlisted connectors via `defaultApiGroup`), or classification could not be determined (permissions / Dataverse unreadable). No policy → SKIPPED (coverage owned by ENV-008) |

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
(`scripts/flightcheck/registry.py`). Integration-specific IDs (the Workday
families above, and the IDs minted by the per-skill setup plans and the
master checklist) are added there as each skill begins emitting them.

---

## Workday Simplified Setup Checkpoints (skills 1–6)

The Workday simplified-setup flow is decomposed into six atomic skills, each
verified by one or more checkpoints. This catalog is the **single declaration**
of those checkpoint IDs, owned by the master setup checklist
(`src/skills/setup/workday/tasks.md`) — the `Step` column below is its row ID.

> **Status of this section.** Each ID's actual `CheckResult` emitter and its
> `registry.py` entry land **with the owning skill** (skills 1–6), not here.
> Until a skill ships, its **minted** IDs are declared (and their prefixes are in
> the registry's `OWNED_PREFIXES` drift allow-list) but not yet runnable via
> `--checkpoint`. **Reuse** IDs already exist and are runnable today.

`Origin`: **reuse** = the checkpoint predates this flow and is simplified-aware;
**mint** = new, owned by the named skill. `Gate`: see
[`role-gating.md`](../setup/role-gating.md).

| Checkpoint | Origin | Skill | Step(s) | Gate | What it verifies |
|------------|--------|-------|---------|------|------------------|
| `ENV-001` | reuse | skill-1 | S1.1 | prog | Power Platform environment exists |
| `ENV-002` | reuse | skill-1 | S1.1 | prog | Dataverse database provisioned |
| `ENV-CAPACITY-001` | mint | skill-1 | S1.2 | prog, else attest | Copilot Studio capacity available |
| `ESS-SOLN-001` | mint | skill-2 | S2.1 | prog | ESS base solution (`msdyn_copilotforemployeeselfservice*`) installed |
| `WD-ENTRA-SCOPE-001` | mint | skill-3 | S3.2 | prog | `user_impersonation` exposed, `4e4707ca` pre-authorized, Graph perms granted |
| `WD-ENTRA-CONSENT-001` | mint | skill-3 | S3.3 | prog → manual if blocked | Admin consent on the Graph delegated perms |
| `WD-ASSIGN-001` | mint | skill-3 | S3.4 | prog | Enterprise-app user/group assignment (or confirmed not required) |
| `WD-CONN-102` | reuse | skill-3, skill-4 | S3.1, S4.4 | manual/attest | SAML signing-certificate health / certificate parity (returns `MANUAL`) |
| `WD-ENTRA-NAMEID-001` | mint | skill-3 | S3.5 | prog → manual if brittle | NameID claim mapping (`claimsMappingPolicy`) |
| `WD-ENTRA-SIGNOPT-001` | mint | skill-3 | S3.6 | manual | "Sign SAML response and assertion" signing option (portal-only) |
| `WD-CONN-010` | reuse | skill-3 | S3.7 | attest | Single-Entra-tenant federation alignment |
| `WD-API-CLIENT-001` | mint | skill-4 | S4.1 | attest | Workday API client registered (functional areas + Workday-owned scope) |
| `WD-TENANT-001` | mint | skill-4 | S4.2, S4.3 | attest | Connection fields captured; auth policies scoped to the OAuth client |
| `WD-PKG-001` | reuse | skill-5 | S5.1 | manual | Extension-pack flavor = `simplified` (exact `ff0df` match) |
| `WD-CONN-012` | reuse | skill-5 | S5.2 | prog | Workday connection ref (`ff0df`) bound, own account |
| `WD-CONN-AUTH-001` | mint | skill-5 | S5.3 | attest | Connection auth type = Entra ID Integrated (echoes `MANUAL`; see §3d reconciliation) |
| `DV-CONN-001` | mint | skill-5 | S5.4 | prog | Dataverse connection (`92b66`) bound — **non-`WD` family** |
| `WD-REST-001` | mint | skill-5 | S5.5 | prog | REST base URL present and trimmed to `/api` |
| `WD-FLOW-*` | reuse | skill-5 | S5.6 | prog | Cloud flows on (one row per discovered flow) |
| `WD-REST-002` | mint | skill-5 | S5.7 | prog w/ rollback | User-context redirect pushed → REST resolves `/workers/me` |
| `WD-NET-001` | mint | skill-5 | S5.8 | attest | Firewall allowlisting (REST + SOAP) — InfoSec attestation |
| `TOPIC-TRIGGER-*` | mint | skill-6 | S6.1 | prog | New-topic trigger phrases + definition (one row per topic) |
| `TOPIC-INTEGRATION-*` | mint | skill-6 | S6.2 | prog | New-topic integration wiring (one row per topic) |

**Notes**

- **`92b66` is the Dataverse connector, not a Workday ref.** The simplified
  Workday family fingerprints a single `ff0df` connection ref; the `92b66` binding
  is verified under the non-`WD` ID `DV-CONN-001`, never as a second `WD-CONN` ref.
- **Legacy `WD-ENV-*` / `WD-WF-*` are not reused for simplified.** They test
  ISU/RaaS artifacts that simplified setup removes (reusing them yields false
  failures / N/A noise); the families are registered only so the registry resolves
  them. The new simplified-only IDs above are used instead.
- **Reuse before minting.** New IDs are minted only for outputs no existing
  simplified-aware checkpoint covers.

