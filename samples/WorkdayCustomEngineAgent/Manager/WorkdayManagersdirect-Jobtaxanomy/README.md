---
nav_exclude: true
search_exclude: false
---
# View direct reports' job taxonomy

Use this read-only topic in your Employee Self-Service Custom Engine Agent to view job titles, business titles, job profiles, and job-family descriptions for your direct reports. Try "Show me my team's job title" or "What job profile is mapped to my team members?" You can also ask about a named direct report, but not an unrelated employee.

The [topic](./topic.yaml) calls `WorkdayManagerCheck`, then `WorkdaySystemGetCommonExecution` to run the supplied Workday `Human_Resources` / `Get_Workers` request. It calls `WorkdaySystemRefreshReferenceData` with `ReferenceDataKey: Job_Family_ID` and resolves returned job-family IDs through `Global.JobFamilyLookupTable`. It builds `Topic.workdayResponseTable` and instructs the model to present a nested Markdown list. The optional `EmployeeName` input filters the returned team by first name, last name, or full name; it is not a unique employee-ID lookup.

## Set up the topic

Complete the [manager prerequisites](../#before-you-start), including the installed HR Workday integration, authenticated connections, and all three [required system topics](../#required-system-topics). Keep `Global.ESS_UserContext_ManagerOrganizationId` tied to the signed-in manager's initialized Workday context. Workday permissions must enforce access; prompt wording and name filtering are not authorization controls.

1. Follow [Register the template configurations](../#register-the-template-configurations). Create or verify an **Employee Self-Service Template Configuration** record with **Unique name** `msdyn_HRWorkdayHCMManagerJobTaxonomy`. Paste the entire [job-taxonomy XML](./msdyn_HRWorkdayHCMManagerJobTaxonomy.xml) into **Value**. Preserve its inner scenario and request-template names.
2. Follow [Add a topic to your agent](../#add-a-topic-to-your-agent): create a blank topic in Copilot Studio, open **More > Open code editor**, and replace its contents with the complete [topic.yaml](./topic.yaml). Resolve the installed manager-check, common-execution, and reference-data references without changing their contracts.
3. Keep `{ManagerOrgId}` bound to `Global.ESS_UserContext_ManagerOrganizationId` and `{As_Of_Effective_Date}` bound to `Text(Today(), "yyyy-MM-dd")`. Preserve the `scenarioName`, JSON `parameters`, and `workdayResponse`, `isSuccess`, and `errorResponse` bindings. Confirm the installed `Job_Family_ID` reference-data setup can populate `Global.JobFamilyLookupTable`; the scenario XML alone does not provide it. Save, enable, and resolve topic-checker errors before testing.

## Customize

Adjust trigger phrases and field labels; for example, add "Show job families for my direct reports." Preserve the direct-report scope, `workdayResponseTable` binding, and job-family lookup. If you change XML response-property keys or extraction paths, update the parsing and table-building expressions together. A missing job-family lookup can leave the description blank; this topic does not fall back to displaying the raw ID.

## Validate before publishing

Start a fresh conversation as an approved manager. Test team and named-report prompts, comparing titles, profiles, family descriptions, and report count with Workday. Verify reference-data initialization and that returned family IDs resolve to the expected descriptions. Include missing or unknown family IDs, duplicate names, legal/preferred-name differences, and a manager with no returned reports. The sample combines response arrays by position and has no explicit multi-page retrieval loop, so check both row alignment and completeness.

Test a non-manager, another manager, and a request about someone outside the signed-in manager's scope; do not publish if out-of-scope data is disclosed. A name with no matching row can produce the same no-access message as an out-of-scope request. For failures, inspect `isSuccess`, `errorResponse`, and the reference-data dependency, then use the [shared validation checklist](../#validate-before-publishing) and [troubleshooting guide](../#troubleshooting). Recheck routing and rendering in a fresh conversation after publishing.
