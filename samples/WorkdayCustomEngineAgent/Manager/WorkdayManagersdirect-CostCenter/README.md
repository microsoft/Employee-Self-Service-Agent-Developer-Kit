---
nav_exclude: true
search_exclude: false
---
# View direct reports' cost centers

Use this read-only topic in your Employee Self-Service Custom Engine Agent to view cost-center codes and names for your direct reports. Try "What cost centers are assigned to my reports?" or ask for a named direct report's cost center. It does not retrieve cost-center information for unrelated employees.

The [topic](./topic.yaml) calls `WorkdayManagerCheck`, then `WorkdaySystemGetCommonExecution` to run the supplied Workday `Human_Resources` / `Get_Workers` request. It combines legal names and cost-center values into `Topic.workdayResponseTable` and instructs the model to present a nested Markdown list. The optional `EmployeeName` input filters the returned team by first name, last name, or full name; it is not a unique employee-ID lookup.

## Set up the topic

Complete the [manager prerequisites](../#before-you-start), including the installed HR Workday integration, authenticated connections, and required system topics. Keep `Global.ESS_UserContext_ManagerOrganizationId` tied to the signed-in manager's initialized Workday context. Workday permissions must enforce access; prompt wording and name filtering are not authorization controls.

1. Follow [Register the template configurations](../#register-the-template-configurations). Create or verify an **Employee Self-Service Template Configuration** record with **Unique name** `msdyn_HRWorkdayHCMManagerDirectCostCenter`. Paste the entire [cost-center XML](./msdyn_HRWorkdayHCMManagerDirectCostCenter.xml) into **Value**. Preserve its inner scenario and request-template names.
2. Follow [Add a topic to your agent](../#add-a-topic-to-your-agent): create a blank topic in Copilot Studio, open **More > Open code editor**, and replace its contents with the complete [topic.yaml](./topic.yaml). Resolve the installed manager-check and common-execution references without changing their contracts.
3. Keep `{ManagerOrgId}` bound to `Global.ESS_UserContext_ManagerOrganizationId` and `{As_Of_Effective_Date}` bound to `Text(Today(), "yyyy-MM-dd")`. Preserve the `scenarioName`, JSON `parameters`, and `workdayResponse`, `isSuccess`, and `errorResponse` bindings. Save, enable, and resolve topic-checker errors before testing.

The supplied XML uses endpoint version `v42.0` and SOAP body version `v41.0`. Validate that combination with your Workday integration owner; do not change either version independently to resolve an unrelated setup error.

## Customize

Adjust trigger phrases and output labels; for example, add "Show cost-center codes for my direct reports." Preserve the direct-report scope and `workdayResponseTable` binding. The XML matches the case-sensitive organization type `Cost_Center` and extracts `LegalNameData`, `CostCenterCode`, and `CostCenterName`. If your tenant requires different extraction paths, update the corresponding parsing and table-building expressions together.

## Validate before publishing

Start a fresh conversation as an approved manager. Test the team prompt and a named report, comparing legal names, cost-center codes, cost-center names, and report count with Workday. Include duplicate names, legal/preferred-name differences, missing cost centers, and a manager with no returned reports. The sample combines response arrays by position and has no explicit multi-page retrieval loop, so check both row alignment and completeness.

Test a non-manager, another manager, and a request about someone outside the signed-in manager's scope; do not publish if out-of-scope data is disclosed. A name with no matching row can produce the same no-access message as an out-of-scope request. For retrieval failures, inspect `isSuccess` and `errorResponse`, then use the [shared validation checklist](../#validate-before-publishing) and [troubleshooting guide](../#troubleshooting). Recheck routing and rendering in a fresh conversation after publishing.
