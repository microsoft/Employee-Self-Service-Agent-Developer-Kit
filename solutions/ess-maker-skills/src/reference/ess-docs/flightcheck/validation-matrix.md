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

---

## 1. Prerequisites (PRE-xxx)

| ID | Check | Priority | Method | Doc Link |
|----|-------|----------|--------|----------|
| PRE-001 | Microsoft 365 Copilot licenses assigned | Critical | Graph API `/subscribedSkus` | [prerequisites#licensing](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#licensing) |
| PRE-002 | Copilot Studio licenses for admins/makers | Critical | Graph API `/subscribedSkus` | [prerequisites#licensing](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#licensing) |
| PRE-003 | Microsoft Teams licenses for users | Critical | Graph API `/subscribedSkus` | [prerequisites#licensing](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#licensing) |
| PRE-008 | Global Admin role assigned | Critical | Graph API `/directoryRoles` | [prerequisites#required-roles](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#required-roles) |
| PRE-009 | Power Platform Admin role assigned | Critical | Graph API `/directoryRoles` | [prerequisites#required-roles](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#required-roles) |

## 2. Environment Configuration (ENV-xxx)

| ID | Check | Priority | Method | Doc Link |
|----|-------|----------|--------|----------|
| ENV-001 | Power Platform environment exists | Critical | BAP Admin API | [prepare#set-up-your-power-platform-environment](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prepare#set-up-your-power-platform-environment) |
| ENV-002 | Dataverse database provisioned | Critical | BAP Admin API | [prepare#set-up-your-power-platform-environment](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prepare#set-up-your-power-platform-environment) |
| ENV-003 | Environment type | High | BAP Admin API | [prepare#set-up-your-power-platform-environment](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prepare#set-up-your-power-platform-environment) |
| ENV-004 | Connections & connection references (binding + orphan detection) | High | BAP Admin API + Dataverse REST | [prepare#set-up-your-power-platform-environment](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prepare#set-up-your-power-platform-environment) |
| ENV-004-OR-nnn | Orphan reference (points to missing connection) | High | — | — |
| ENV-004-UR-nnn | Unbound reference (no connection bound) | High | — | — |
| ENV-004-UC-nnn | Unbound connection (no reference uses it) | Medium | — | — |
| ENV-008 | DLP policies configured | High | BAP Admin API | [prepare#allow-the-external-systems-connector](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prepare#allow-the-external-systems-connector) |

## 3. Authentication & Identity (AUTH-xxx)

| ID | Check | Priority | Method | Doc Link |
|----|-------|----------|--------|----------|
| AUTH-001 | Microsoft Entra ID configured | Critical | Graph API `/organization` | [prerequisites#identity-authentication-and-single-sign-on-sso](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#identity-authentication-and-single-sign-on-sso) |
| AUTH-002 | Conditional Access policies | High | Graph API `/identity/conditionalAccess/policies` | [prerequisites#identity-authentication-and-single-sign-on-sso](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#identity-authentication-and-single-sign-on-sso) |
| AUTH-004 | User identity synchronization | High | Graph API `/users` | [prerequisites#identity-authentication-and-single-sign-on-sso](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/prerequisites#identity-authentication-and-single-sign-on-sso) |

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
| WD-WF-016 | Update Email | Human_Resources | Write | | Contact Information |
| WD-WF-017 | Update Phone | Human_Resources | Write | | Contact Information |

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
