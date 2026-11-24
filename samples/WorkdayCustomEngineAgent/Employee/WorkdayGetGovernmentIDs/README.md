---
nav_exclude: true
search_exclude: false
---
# View your government IDs — Custom Engine Agent

This topic reads government-ID information from your own Workday profile, including ID value, ID type, issuing country, issue date, and expiration date. Try "Show my government IDs." It is not guidance about applications, renewals, or immigration policy.

The topic calls the CEA common-execution system topic, parses the returned records, resolves country and ID-type reference values, and returns `finalizedResponseTableData`.

## Files

| File | Description |
|---|---|
| [topic.yaml](./topic.yaml) | Government-ID read, reference lookups, and output table |
| [msdyn_HRWorkdayHCMEmployeeGetGovernmentIds.xml](./msdyn_HRWorkdayHCMEmployeeGetGovernmentIds.xml) | Workday `Get_Workers` request and response mapping |

## Setup

Follow the [CEA prerequisites](../#before-you-start) and [register the template configuration](../#register-the-template-configurations) with **Unique name** `msdyn_HRWorkdayHCMEmployeeGetGovernmentIds` and the complete XML in **Value**. Preserve the supplied inner XML names.

Then [add this scenario](../#add-a-scenario) by pasting the complete `topic.yaml` into a blank topic's code editor, resolving the CEA system-topic references, saving, and enabling it.

{: .important }
> The supplied XML sets the Human_Resources endpoint to `v42.0` and the SOAP request body to `v41.0`. Validate this existing combination with your Workday integration owner before rollout; importing the sample does not prove API compatibility.

## Dependencies and customization

Keep `msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemGetCommonExecution` and `msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemRefreshReferenceData` configured. The topic requests `ISO_3166-1_Alpha-2_Code` and `Government_ID_Type_ID` reference data through `Global.CountryNameLookupTable` and `Global.GovernmentIdTypeLookupTable`.

Employee context must populate `Global.ESS_UserContext_Employee_Id`, `Global.ESS_UserContext_Employee_Firstname`, and `Global.ESS_UserContext_Employee_Lastname`.

You can customize trigger wording and displayed labels while retaining scenario keys and parsed response bindings. Review your organization's rules before exposing ID values in a channel: this sample returns the `ID` field and does not mask it. An `EmployeeName` input or model instruction is not an authorization control.

## Test and troubleshoot

Use only approved test identifiers. In new conversations, verify populated and empty records, country/type labels, date fields, and a request about another employee. Confirm the authenticated user's Workday permissions and target-channel handling prevent inappropriate disclosure.

For blank labels, inspect the reference-data mappings. For failed calls or parsing errors, inspect `isSuccess`/`errorResponse`, configuration registration, and the API-version combination before changing parser bindings. Do not include real IDs in screenshots, public issues, or logs used for sharing. Follow the [shared CEA troubleshooting checks](../#troubleshooting) before publishing.
