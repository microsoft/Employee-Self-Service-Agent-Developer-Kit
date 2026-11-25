---
title: Workday (Declarative Agent Preview)
parent: Samples
nav_order: 5
---
# ESS Workday Scenarios - Declarative Agent Preview

Extend your existing Employee Self-Service (ESS) **Declarative Agent Preview** with Workday topics for employees and managers. This folder contains 11 employee scenarios and five manager scenarios, each with a Copilot Studio `topic.yaml` and one or more template configuration XML files. Add only the scenarios your organization needs.

These are Preview sample assets, not an agent installer or a setup package for another agent version. They require a compatible Preview HR Workday integration and its existing execution, reference-data, and manager-check topics. The supplied topics retrieve Workday records or submit employee changes; importing YAML alone does not configure connections or grant access.

## Folder layout

| Folder | Description |
|---|---|
| [Employee/](./Employee/) | 11 self-service scenarios for the signed-in employee. The complete inventory is listed below. |
| [Manager/](./Manager/) | Five read-only scenarios for a manager's direct reports. |

## Before you start

- Use an editable ESS Declarative Agent Preview with a compatible HR Workday integration already installed. For connection and authentication guidance, use [Set up the simplified Workday integration for Employee Self-Service](https://learn.microsoft.com/en-us/copilot/employee-self-service/workday-simplified-setup). Confirm compatibility with your installed Preview solution; this sample does not install or upgrade it. Simplified connection setup does not replace the Preview-specific topic dependencies below.
- Have maker access to the agent's environment and permission to manage **Employee Self-Service Template Configuration** records. Work with your Workday administrator on OAuth scopes, security domains, and business-process permissions for the operations you select.
- Confirm authenticated employee-context initialization supplies `Global.ESS_UserContext_Employee_Id`. Some employee topics also use `Global.ESS_UserContext_Employee_Firstname` and `Global.ESS_UserContext_Employee_Lastname`. Manager scenarios require `Global.ESS_UserContext_ManagerOrganizationId` from the signed-in manager's context. Do not hard-code employee IDs, manager organizations, or manager status.
- Start in a non-production environment with approved identities and test data. Profile, contact, and government-ID reads expose sensitive information; dependent, address, time-off, feedback, and emergency-contact operations can submit changes.

### Required system topics

The supplied YAML references the **`msdyn_copilotforemployeeselfservicedahr.topic.`** schema prefix. Resolve each dependency against your installed Preview topics through the topic picker while preserving its input/output contract. Do not replace the prefix with a different agent version's namespace to hide a missing dependency.

| System topic | Used by |
|---|---|
| `WorkdaySystemGetCommonExecution` | All 16 scenarios. Accepts `scenarioName` and JSON `parameters`; returns `workdayResponse`, `isSuccess`, and `errorResponse`. |
| `GetReferenceData` | Dependents and emergency contacts, including relationship and location/phone reference data. |
| `WorkdaySystemRefreshReferenceData` | Employee job information, education, government IDs, and manager job information. |
| `WorkdayManagerCheck` | Manager company code, cost center, job information, and service anniversary. |

The time-in-position topic does **not** call `WorkdayManagerCheck`. Confirm the installed access controls and Workday permissions before exposing it. An organization ID, name filter, or model description is not proof of authorization.

Job information uses `Global.JobFamilyLookupTable`; education and government IDs use their respective country, degree, field-of-study, or government-ID reference tables. Keep the installed reference-data setup and the topic's exact `ReferenceDataKey` values aligned. A scenario's own XML is not a replacement for these shared dependencies.

## Register the template configurations

Register the configurations required by your selected topics in the same environment as the Preview agent:

1. Open **Solutions > Default** in Power Apps and locate **Employee Self-Service Template Configuration**. Select **All** if the solution is not visible.
2. Check for an existing record with the required **Unique name** before creating another. Back up the current value before updating a shared configuration.
3. Create an **Employee Self-Service Template Configuration** record using **New > More > Other**.
4. Set **Name** to a descriptive label, **Unique name** to the exact lookup key below, and **Value** to the entire linked XML file. Save and close the record.
5. Repeat for all configurations the selected topic calls, including cross-scenario dependencies. Verify that your installed Preview common-execution topic resolves these records before proceeding.

{: .important }
> The record's **Unique name** must match the topic's `scenarioName`. It does not have to match the XML filename or inner `<scenario name="...">`. Preserve the supplied XML names and placeholders. Do not upload these files to the connector's connection settings. This folder does not include a shared configuration-initializer topic; do not assume one is created when you paste a scenario.

### Employee configuration lookup names

| Unique name / topic `scenarioName` | XML file |
|---|---|
| `msdyn_HRWorkdayHCMEmployeeGetDependents` | [Get dependents](./Employee/EmployeeAddDependents/msdyn_HRWorkdayHCMEmployeeGetDependents.xml) |
| `msdyn_HRWorkdayHCMEmployeeAddDependent` | [Add dependent](./Employee/EmployeeAddDependents/msdyn_HRWorkdayHCMEmployeeAddDependent.xml) |
| `msdyn_HRWorkdayHCMEmployeeGetVacationBalance` | [Vacation balance](./Employee/EmployeeGetVacationBalance/msdyn_HRWorkdayHCMEmployeeGetVacationBalance.xml) |
| `msdyn_HRWorkdayHCMEmployeeGetResidentialAddress` | [Get residential address](./Employee/EmployeeUpdateResidentialAddress/msdyn_GetResidentialAddress_Template.xml) |
| `msdyn_HRWorkdayHCMEmployeeAddResidentialAddress` | [Add residential address](./Employee/EmployeeUpdateResidentialAddress/msdyn_AddResidentialAddress_Template.xml) |
| `msdyn_HRWorkdayHCMEmployeeUpdateResidentialAddress` | [Update residential address](./Employee/EmployeeUpdateResidentialAddress/msdyn_UpdateResidentialAddress_Template.xml) |
| `msdyn_HRWorkdayAbsenceEnterTimeOff_MultiDay` | [Request time off](./Employee/WorkdayEmployeeRequestTimeOff/msdyn_HRWorkdayAbsenceEnterTimeOff_MultiDay.xml) |
| `msdyn_HRWorkdayHCMEmployeeGetJobTaxonomy` | [Job information](./Employee/WorkdayEmployeesviewtheirjobtaxonomy/msdyn_HRWorkdayHCMEmployeeGetJobTaxonomy.xml) |
| `msdyn_HRWorkdayHCMEmployeeGetHomeContactInformation` | [Home contact information](./Employee/WorkdayGetContactInformation/msdyn_HRWorkdayHCMEmployeeGetHomeContactInformation.xml) |
| `msdyn_HRWorkdayHCMEmployeeGetEducation` | [Education](./Employee/WorkdayGetEducation/msdyn_HRWorkdayHCMEmployeeGetEducation.xml) |
| `msdyn_HRWorkdayHCMEmployeeGetGovernmentIds` | [Government IDs](./Employee/WorkdayGetGovernmentIDs/msdyn_HRWorkdayHCMEmployeeGetGovernmentIds.xml) |
| `msdyn_HRWorkdayHCMEmployeeGetUserProfile` | [User profile](./Employee/WorkdayGetUserProfile/msdyn_HRWorkdayHCMEmployeeGetUserProfile.xml) |
| `msdyn_HRWorkdayHCMEmployeeGiveFeedback` | [Peer feedback](./Employee/WorkdayGivePeerFeedback/msdyn_HRWorkdayHCMEmployeeGiveFeedback.xml) |
| `msdyn_HRWorkdayHCMEmployeeGetEmergencyContactInfo` | [Get emergency contacts](./Employee/WorkdayManageEmergencyContact/msdyn_HRWorkdayHCMEmployeeGetEmergencyContactInfo.xml) |
| `msdyn_HRWorkdayHCMEmployeeAddEmergencyContact` | [Add emergency contact](./Employee/WorkdayManageEmergencyContact/msdyn_HRWorkdayHCMEmployeeAddEmergencyContact.xml) |
| `msdyn_UpdateEmergencyContact` | [Update emergency contact](./Employee/WorkdayManageEmergencyContact/msdyn_HRWorkdayHCMEmployeeUpdateEmergencyContact.xml) |
| `msdyn_DeleteEmergencyContact` | [Delete emergency contact](./Employee/WorkdayManageEmergencyContact/msdyn_HRWorkdayDeleteEmergencyContact.xml) |

Time-off requests also call the vacation-balance configuration. Contact Information additionally calls **`msdyn_HRWorkdayHCMEmployeeGetWorkAddress`** and **`msdyn_HRWorkdayHCMEmployeeGetWorkContactInformation`** from the installed Preview integration. Those two XML files are not included here; verify the existing configurations and their response contracts rather than substituting a similarly named configuration from another agent version.

### Manager configuration lookup names

| Unique name / topic `scenarioName` | XML file |
|---|---|
| `msdyn_HRWorkdayHCMManagerDirectCompanyCode` | [Company code](./Manager/WorkdayManagersdirect-CompanyCode/msdyn_HRWorkdayHCMManagerDirectCompanyCode.xml) |
| `msdyn_HRWorkdayHCMManagerDirectCostCenter` | [Cost center](./Manager/WorkdayManagersdirect-CostCenter/msdyn_HRWorkdayHCMManagerDirectCostCenter.xml) |
| `msdyn_HRWorkdayHCMManagerJobTaxonomy` | [Job information](./Manager/WorkdayManagersdirect-Jobtaxanomy/msdyn_HRWorkdayHCMManagerJobTaxonomy.xml) |
| `msdyn_HRWorkdayHCMManagerServiceAnniversary` | [Service anniversary](./Manager/WorkdayManagerServiceAnniversary/msdyn_HRWorkdayHCMManagerServiceAnniversary.xml) |
| `msdyn_GetManagerReportees` | [Time in position](./Manager/WorkdayGetManagerReporteesTimeInPosition/msdyn_GetManagerReportees.xml) |

## Add a scenario

1. Choose a topic from the scenario tables below. Copy its complete YAML, not the surrounding GitHub page.
2. In your Preview agent in Copilot Studio, select **Topics > Add a topic > From blank** and give it a descriptive name.
3. Select **More > Open code editor**, replace the blank topic's contents with the full YAML, and save.
4. Resolve the required Preview system topics using the topic picker. Preserve `scenarioName`, JSON `parameters`, and all response/error bindings.
5. Review tenant URLs, plan/reason IDs, picklists, employee and manager bindings, effective dates, and reference-data dependencies. Replace tenant placeholders such as `<TENANT_NAME>` with approved values before testing. Keep XML placeholder spellings synchronized with the topic's JSON keys.
6. Save and enable the topic, resolve topic-checker errors, and test in a new conversation before publishing. Use the same process for each additional scenario.

Some supplied topics have `intent: {}` rather than explicit trigger queries. The prompts below are suggested validation utterances, not a claim that every phrase is already configured. Test model-based routing as well as conversation behavior.

## Scenarios

Links below open the actual Preview YAML files, including scenarios that do not yet have individual READMEs. Read any accompanying guide as additional context, but use the Preview YAML for exact dependency namespaces and lookup keys.

### Employee scenarios

| Topic | What it does | Suggested test prompt |
|---|---|---|
| [Add dependents](./Employee/EmployeeAddDependents/topic.yaml) | View existing dependents and add a dependent. | "Add a dependent" |
| [Vacation balance](./Employee/EmployeeGetVacationBalance/topic.yaml) | View time-off balances as of a selected date. | "What is my vacation balance?" |
| [Residential address](./Employee/EmployeeUpdateResidentialAddress/topic.yaml) | View, add, or update your home address. | "Update my home address" |
| [Request time off](./Employee/WorkdayEmployeeRequestTimeOff/topic.yaml) | Submit a time-off request using the configured plans and dates. | "I want to request time off" |
| [Job information](./Employee/WorkdayEmployeesviewtheirjobtaxonomy/topic.yaml) | View job title, business title, job profile, and job-family information. | "What is my job title?" |
| [Contact information](./Employee/WorkdayGetContactInformation/topic.yaml) | View your home and work contact information. | "Show my contact details" |
| [Education](./Employee/WorkdayGetEducation/topic.yaml) | View education history and reference-data descriptions. | "Show my education details" |
| [Government IDs](./Employee/WorkdayGetGovernmentIDs/topic.yaml) | View government-ID information in your profile. | "What are my government IDs?" |
| [User profile](./Employee/WorkdayGetUserProfile/topic.yaml) | View your personal, employment, and contact information. | "Show my profile" |
| [Peer feedback](./Employee/WorkdayGivePeerFeedback/topic.yaml) | Submit feedback about a coworker. | "Give feedback on Workday" |
| [Emergency contacts](./Employee/WorkdayManageEmergencyContact/topic.yaml) | View, add, update, or remove emergency contacts. | "Manage my emergency contacts" |

### Manager scenarios

| Topic | What it returns | Suggested test prompt |
|---|---|---|
| [Company code](./Manager/WorkdayManagersdirect-CompanyCode/topic.yaml) | Direct reports' names, company codes, and company names. | "What are the company codes for my reports?" |
| [Cost center](./Manager/WorkdayManagersdirect-CostCenter/topic.yaml) | Direct reports' names and cost-center details. | "What cost centers are assigned to my reports?" |
| [Job information](./Manager/WorkdayManagersdirect-Jobtaxanomy/topic.yaml) | Direct reports' job titles, business titles, profiles, and job-family descriptions. | "Show me my team's job title" |
| [Service anniversary](./Manager/WorkdayManagerServiceAnniversary/topic.yaml) | Hire dates, upcoming anniversaries, and milestone years. | "When are the service anniversaries of all my directs?" |
| [Time in position](./Manager/WorkdayGetManagerReporteesTimeInPosition/topic.yaml) | Team and position details with calculated time in the current role. | "How long have my direct reports been in their current positions?" |

## Validate before publishing

Start a fresh conversation for each identity so employee context and reference-data initialization are refreshed. Saving a topic without errors does not prove that the integration works.

| Check | What to verify |
|---|---|
| Configuration and routing | The selected lookup keys resolve in the installed Preview execution path, all child topics are available, and suggested prompts route to the intended scenario. |
| Employee reads | Compare results with approved Workday records for the signed-in employee. Check empty and missing fields, reference-data descriptions, date selection, and sensitive-data handling. |
| Writes | Use approved test records for dependents, addresses, time off, feedback, and emergency contacts. Verify required fields, confirmation and cancellation where present, and the actual Workday result. Review business-process state; a submission message is not proof of final approval. |
| Manager scope | Test an authorized manager, a non-manager, a different manager, and a request about someone outside the signed-in manager's team. No out-of-scope records should be disclosed. Explicitly test time in position because it lacks the manager-check call. |
| Completeness and calculations | Compare team counts, name matches, anniversary dates, and position tenure with known data. Check duplicate names, missing dates, month/year boundaries, and large result sets rather than assuming every response is complete. |
| Dependency failures | Test missing configuration, unavailable reference data, and expired or unauthorized connections using approved procedures. Inspect `isSuccess` and `errorResponse` rather than treating generated text as proof of success. |
| Published channel | After publishing, start a new conversation and check routing, card rendering, validation, cancellation, and access scope in that channel. |

These are validation steps for your environment, not a claim that every Preview deployment has been runtime-tested. If a submission has an uncertain outcome, check Workday before repeating it.

## Troubleshooting

| Symptom | Check |
|---|---|
| A Preview child topic or global is unresolved | Confirm the compatible Preview HR Workday solution and context initializer are installed. Resolve the actual dependency; do not copy another agent version's namespace or invent globals. |
| A configuration is missing | Check the environment, record Unique name, topic `scenarioName`, and complete XML value. Register every required configuration, including vacation balance for time-off requests and installed work-contact configurations. |
| Contact or reference-data results are missing | Verify the two installed work-contact configurations and the required reference-data topics/tables. The home-contact XML alone does not supply all contact data. |
| Another employee's data or the wrong team appears | Stop rollout and review signed-in context, manager checks, organization scope, and Workday permissions with the integration owner. Do not bypass checks to make a prompt succeed. |
| The topic saves but Workday fails | Check user-authenticated connections, permissions, tenant-specific IDs/URLs, XML placeholders, and the execution error output. |
| An older child README disagrees with this overview | Use the linked Preview YAML and configuration tables for exact runtime bindings. Do not follow stale file-upload or non-Preview namespace instructions. |

## Customize and handle updates

Adjust trigger wording, card labels, and model descriptions to match your organization while preserving user scope and runtime contracts. For example, add "Check my PTO balance" to the vacation-balance trigger queries without broadening access to other employees' balances.

Back up topics and configuration records before applying updates. Review incoming YAML and XML together, preserve your tenant-specific customizations, and re-test shared configurations and dependencies before publishing. Changes are maker-managed; these samples do not automatically update your agent. Restoring a topic does not undo a change already submitted to Workday.