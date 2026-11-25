---
nav_exclude: true
search_exclude: false
---
# View direct reports' company codes

Use this read-only topic in your Employee Self-Service Custom Engine Agent to view company codes and company names for your direct reports. Try "What are the company codes for my reports?" or ask for the company code of a named direct report. It is not a lookup for your own company code or an unrelated employee.

The [topic](./topic.yaml) calls `WorkdayManagerCheck`, then `WorkdaySystemGetCommonExecution` to run the supplied Workday `Human_Resources` / `Get_Workers` request. It builds `Topic.workdayResponseTable` with first name, last name, company code, and company name, and instructs the model to present a nested Markdown list. The optional `EmployeeName` input filters the returned team by first name, last name, or full name; it is not a unique employee-ID lookup.

## Set up the topic

Complete the [manager prerequisites](../#before-you-start), including the installed HR Workday integration, authenticated connections, and required system topics. Keep `Global.ESS_UserContext_ManagerOrganizationId` tied to the signed-in manager's initialized Workday context. Workday permissions must enforce access; prompt wording and name filtering are not authorization controls.

1. Follow [Register the template configurations](../#register-the-template-configurations). Create or verify an **Employee Self-Service Template Configuration** record with **Unique name** `msdyn_HRWorkdayHCMManagerDirectCompanyCode`. Paste the entire [company-code XML](./msdyn_HRWorkdayHCMManagerDirectCompanyCode.xml) into **Value**. Preserve its inner scenario and request-template names.
2. Follow [Add a topic to your agent](../#add-a-topic-to-your-agent): create a blank topic in Copilot Studio, open **More > Open code editor**, and replace its contents with the complete [topic.yaml](./topic.yaml). Resolve the installed manager-check and common-execution references without changing their contracts.
3. Keep `{ManagerOrgId}` bound to `Global.ESS_UserContext_ManagerOrganizationId` and `{As_Of_Effective_Date}` bound to `Text(Today(), "yyyy-MM-dd")`. Preserve the `scenarioName`, JSON `parameters`, and `workdayResponse`, `isSuccess`, and `errorResponse` bindings. Save, enable, and resolve topic-checker errors before testing.

## Customize

Adjust trigger phrases and display labels to match your vocabulary; for example, add "Show company names for my direct reports." Keep the direct-report scope and `workdayResponseTable` output binding. If you change XML extraction keys, update the topic's parsing and table-building expressions together. The supplied XML selects organizations with subtype `Company`; confirm that this matches your Workday setup.

## Validate before publishing

Start a fresh conversation as an approved manager. Test the team prompt and a named report, comparing names, codes, company names, and report count with Workday. Include duplicate names, legal/preferred-name differences, missing company data, and a manager with no returned reports. The sample combines response arrays by position and has no explicit multi-page retrieval loop, so check both row alignment and completeness.

Test a non-manager, another manager, and a request about someone outside the signed-in manager's scope; do not publish if out-of-scope data is disclosed. A name with no matching row can produce the same no-access message as an out-of-scope request. For retrieval failures, inspect `isSuccess` and `errorResponse`, then use the [shared validation checklist](../#validate-before-publishing) and [troubleshooting guide](../#troubleshooting). Recheck routing and rendering in a fresh conversation after publishing.
