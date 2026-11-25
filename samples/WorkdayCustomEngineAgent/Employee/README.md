---
nav_exclude: true
search_exclude: false
---
# Workday Employee Scenarios — Custom Engine Agent (CEA)

**Register the XML configurations for the scenarios you need, then create their topics in your existing ESS Custom Engine Agent.** These samples let employees read their own Workday records and submit self-service changes.

These topics use ESS Template Configuration records and `msdyn_copilotforemployeeselfservicehr.topic.*` system topics. Use the configuration lookup names and system-topic bindings documented below.

## Contents

| Scenario | Description | Sample prompt |
|---|---|---|
| [Add dependents](./EmployeeAddDependents/) | View existing dependents and add a dependent | "Add a dependent" |
| [Vacation balance](./EmployeeGetVacationBalance/) | Check time-off balances as of a selected date | "What is my vacation balance?" |
| [Residential address](./EmployeeUpdateResidentialAddress/) | View, add, or update your home address | "Update my home address" |
| [Request time off](./WorkdayEmployeeRequestTimeOff/) | Submit a single-day or multi-day request | "Request vacation from January 5th to January 10th" |
| [Job information](./WorkdayEmployeesviewtheirjobtaxonomy/) | View your title, business title, job profile, and job family | "What is my job profile?" |
| [Contact information](./WorkdayGetContactInformation/) | View your work and home contact details | "What is my work phone?" |
| [Education](./WorkdayGetEducation/) | View your education history | "Show my education details" |
| [Government IDs](./WorkdayGetGovernmentIDs/) | View government-ID information in your profile | "What are my government IDs?" |
| [User profile](./WorkdayGetUserProfile/) | View your personal, employment, and contact information | "Show my employee profile" |
| [Peer feedback](./WorkdayGivePeerFeedback/) | Submit feedback about a colleague | "Give feedback" |
| [Emergency contacts](./WorkdayManageEmergencyContact/) | View, add, update, or remove emergency contacts | "Manage my emergency contacts" |

## Before you start

- Use an editable ESS **Custom Engine Agent** with the ESS HR Workday solution accelerator installed and configured. These samples extend that agent; they do not install an agent, connectors, or system topics.
- Complete the [simplified Workday integration setup](https://learn.microsoft.com/en-us/copilot/employee-self-service/workday-simplified-setup), including authenticated connections, employee-context initialization, and Workday permissions for each selected operation. The supplied XML requests use **User** authentication.
- Have maker access to the agent's Power Platform environment and permission to create or update its ESS Template Configuration records. Work with your Workday administrator on security domains and business-process permissions; do not broaden permissions merely to make a test pass.
- Confirm `Global.ESS_UserContext_Employee_Id` contains the signed-in employee's Workday Employee ID. Job information, contact information, education, and government IDs also use `Global.ESS_UserContext_Employee_Firstname` and `Global.ESS_UserContext_Employee_Lastname`.
- Keep `msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemGetCommonExecution` configured. Topics that resolve reference values also need `GetReferenceData` or `WorkdaySystemRefreshReferenceData`, as described in their individual READMEs.
- Configure and test in a non-production environment with approved employee records. Review the scenario's tenant URLs, picklists, and IDs before using it.

## Register the template configurations

The [Workday extensibility walkthrough](https://learn.microsoft.com/en-us/copilot/employee-self-service/workday-extensibility) describes the configuration form and topic code editor. For **these CEA samples**, use the exact lookup names below rather than names from an older walkthrough.

1. Open your ESS agent in Copilot Studio and select the environment containing its Workday integration.
2. Go to **Solutions > Default**. Select **All** if the solution is not visible.
3. Find **Employee Self-Service Template Configuration** and check whether each required configuration already exists. Back up its value before updating an existing record; a shared configuration change can affect OOB topics too.
4. To create a record, select **New > More > Other > Employee Self-Service Template Configuration**.
5. Set **Name** to a descriptive label. Set **Unique name** to the exact `scenarioName` from the selected topic's common-execution call, using the table below. Paste the **entire XML file** into **Value**, then select **Save and Close**.
6. Repeat for every configuration required by the selected scenario, including cross-folder dependencies. You do not need to create unused scenario topics.

{: .important }
> The configuration record's **Unique name** is the lookup key passed as `scenarioName`. It is not necessarily the XML filename, inner `<scenario name="...">`, or `<requestTemplate name="...">`. Preserve the supplied XML names and placeholders; do not add `msdyn_` to every inner XML name.

### CEA configuration lookup names

Each row maps a topic's lookup key to the complete XML to store in **Value**.

| Scenario | Unique name / topic `scenarioName` | XML file |
|---|---|---|
| Add dependents: read | `msdyn_HRWorkdayHCMEmployeeGetDependents` | [Get dependents](./EmployeeAddDependents/msdyn_HRWorkdayHCMEmployeeGetDependents.xml) |
| Add dependents: write | `msdyn_HRWorkdayHCMEmployeeAddDependent` | [Add dependent](./EmployeeAddDependents/msdyn_HRWorkdayHCMEmployeeAddDependent.xml) |
| Vacation balance; also required by request time off | `msdyn_HRWorkdayHCMEmployeeGetVacationBalance` | [Vacation balance](./EmployeeGetVacationBalance/msdyn_HRWorkdayHCMEmployeeGetVacationBalance.xml) |
| Residential address: read | `msdyn_HRWorkdayHCMEmployeeGetResidentialAddress` | [Get address](./EmployeeUpdateResidentialAddress/msdyn_GetResidentialAddress_Template.xml) |
| Residential address: add | `msdyn_HRWorkdayHCMEmployeeAddResidentialAddress` | [Add address](./EmployeeUpdateResidentialAddress/msdyn_AddResidentialAddress_Template.xml) |
| Residential address: update | `msdyn_HRWorkdayHCMEmployeeUpdateResidentialAddress` | [Update address](./EmployeeUpdateResidentialAddress/msdyn_UpdateResidentialAddress_Template.xml) |
| Request time off: write | `msdyn_HRWorkdayAbsenceEnterTimeOff_MultiDay` | [Enter time off](./WorkdayEmployeeRequestTimeOff/msdyn_HRWorkdayAbsenceEnterTimeOff_MultiDay.xml) |
| Job information | `msdyn_HRWorkdayHCMEmployeeGetJobTaxonomy` | [Job information](./WorkdayEmployeesviewtheirjobtaxonomy/msdyn_HRWorkdayHCMEmployeeGetJobTaxonomy.xml) |
| Contact information: home | `msdyn_HRWorkdayHCMEmployeeGetHomeContactInformation` | [Home contact information](./WorkdayGetContactInformation/msdyn_HRWorkdayHCMEmployeeGetHomeContactInformation.xml) |
| Education | `msdyn_HRWorkdayHCMEmployeeGetEducation` | [Education](./WorkdayGetEducation/msdyn_HRWorkdayHCMEmployeeGetEducation.xml) |
| Government IDs | `msdyn_HRWorkdayHCMEmployeeGetGovernmentIds` | [Government IDs](./WorkdayGetGovernmentIDs/msdyn_HRWorkdayHCMEmployeeGetGovernmentIds.xml) |
| User profile | `msdyn_HRWorkdayHCMEmployeeGetUserProfile` | [User profile](./WorkdayGetUserProfile/msdyn_HRWorkdayHCMEmployeeGetUserProfile.xml) |
| Peer feedback | `msdyn_HRWorkdayHCMEmployeeGiveFeedback` | [Peer feedback](./WorkdayGivePeerFeedback/msdyn_HRWorkdayHCMEmployeeGiveFeedback.xml) |
| Emergency contacts: read | `msdyn_HRWorkdayHCMEmployeeGetEmergencyContactInfo` | [Get emergency contacts](./WorkdayManageEmergencyContact/msdyn_HRWorkdayHCMEmployeeGetEmergencyContactInfo.xml) |
| Emergency contacts: add | `msdyn_HRWorkdayHCMEmployeeAddEmergencyContact` | [Add emergency contact](./WorkdayManageEmergencyContact/msdyn_HRWorkdayHCMEmployeeAddEmergencyContact.xml) |
| Emergency contacts: update | `msdyn_UpdateEmergencyContact` | [Update emergency contact](./WorkdayManageEmergencyContact/msdyn_HRWorkdayHCMEmployeeUpdateEmergencyContact.xml) |
| Emergency contacts: delete | `msdyn_DeleteEmergencyContact` | [Delete emergency contact](./WorkdayManageEmergencyContact/msdyn_HRWorkdayDeleteEmergencyContact.xml) |

Contact information also calls the existing OOB configurations `msdyn_HRWorkdayHCMEmployeeGetWorkContactInformation` and `msdyn_HRWorkdayHCMEmployeeGetWorkAddress`. Their XML is not supplied in this employee sample tree. Confirm those records are present in your installed Workday integration before adding the topic.

## Add a scenario

1. Open the scenario's README and review its dependencies and customization points.
2. Register its XML configurations using [Register the template configurations](#register-the-template-configurations). For request time off, include the vacation-balance XML even if you do not create the vacation-balance topic.
3. In Copilot Studio, select **Topics > Add a topic > From blank** and name the topic.
4. Select **More > Open code editor**. Replace the blank topic's contents with the scenario's **entire** `topic.yaml`; use the raw file contents when copying from GitHub.
5. Review tenant-specific values. Replace `<TENANT_NAME>` in user-facing Workday links, and review country/state choices, leave-plan/type/reason IDs, and reference-data mappings where applicable.
6. Resolve child-topic references to the installed CEA system topics. If your agent generates a different schema name, select the existing topic through the topic picker and retain its input/output bindings. Do not hard-code another employee's ID.
7. Return to the canvas, save, and enable the topic. Resolve topic-checker errors before testing.

The common-execution input contract includes `scenarioName` and the JSON `parameters` string. Its output bindings include `workdayResponse`, `isSuccess`, and `errorResponse`. Preserve those contracts, XML placeholder tokens, and node IDs when customizing.

## Check the setup before publishing

Start a **new test conversation** so employee context and reference-data initialization run for the current user. Exercise the scenario-specific tests in each README.

- For reads, compare returned data with the signed-in test employee's Workday record. Test both populated and empty records, and requests about someone else's data. A model description is not an authorization boundary; Workday permissions must still enforce access.
- For writes, first test cancellation and validation without submitting. Submit only approved test changes, verify the resulting record or business process in Workday, and check error/retry behavior. Peer feedback submits after collecting the text, without a separate confirmation card.
- Re-test OOB topics if you updated configurations they share. Saving YAML or XML alone does not validate authentication, permissions, response parsing, or channel rendering.

Publish only after your normal review and environment validation. Start a fresh conversation in the target channel and check the Adaptive Cards and responses there as well.

## Troubleshooting

| Symptom | Check |
|---|---|
| Configuration is missing or the common-execution call fails | In the same environment, verify the ESS Template Configuration record's **Unique name** exactly matches that call's `scenarioName`, and **Value** contains the complete XML. Do not rename inner XML elements to guess a fix. |
| A system topic or global variable is unresolved | Confirm the CEA HR Workday integration and employee-context initialization are installed and configured. Resolve the reference through the topic picker without changing its contract. |
| Authentication or access fails | Review user-authenticated connections and the employee's Workday security-domain/business-process permissions with your administrator. Do not bypass access checks. |
| Contact information fails although the home XML is registered | Check the two OOB work-contact/work-address configurations as well; this topic executes all three reads. |
| Reference labels are blank or show raw IDs | Check the topic's reference-data refresh dependency and tenant-specific mappings. Job information deliberately falls back to the raw job-family ID when no descriptor is found. |
| Workday rejects a request or parsing fails | Inspect `isSuccess`, `errorResponse`, and the failing call using approved diagnostic practices. Verify parameters, response shape, and API compatibility. Job-information and government-ID XML currently specify endpoint `v42.0` with SOAP body `v41.0`; validate this existing combination with your integration owner before rollout. |
| Time-off balances are empty but the request form appears | Register the vacation-balance configuration and check that `PlanConfig` IDs match plans returned for the employee. |

Do not paste tokens, employee data, or sensitive identifiers into public issues or comparison services.

## Handle repo updates

Back up your customized topics and configuration records. Compare incoming YAML and XML locally, then merge changes while preserving your tenant URLs, plan/type/reason IDs, reference mappings, approval settings, and API versions. Configuration updates are maker-managed; these samples do not automatically update your agent.

Save, re-test in a new conversation, and publish only after validation. If an update fails validation, restore the backed-up topic and configuration values before retrying.
