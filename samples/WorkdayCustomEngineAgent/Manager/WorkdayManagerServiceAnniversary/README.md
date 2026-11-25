---
nav_exclude: true
search_exclude: false
---
# View direct reports' service anniversaries

Use this read-only topic in your Employee Self-Service Custom Engine Agent to view upcoming service anniversaries for your direct reports. Try "When are the service anniversaries of all my directs?" or ask for a named direct report's next service anniversary. It is not a lookup for unrelated employees.

The [topic](./topic.yaml) calls `WorkdayManagerCheck`, then `WorkdaySystemGetCommonExecution` to run the supplied Workday `Human_Resources` / `Get_Workers` request. It uses hire dates to calculate `Topic.response` and instructs the model to present a Markdown table with employee name, hire date, upcoming service anniversary date, and upcoming milestone in years. The optional `EmployeeName` input filters the returned team by first name, last name, or full name; it is not a unique employee-ID lookup.

## Set up the topic

Complete the [manager prerequisites](../#before-you-start), including the installed HR Workday integration, authenticated connections, and required system topics. Keep `Global.ESS_UserContext_ManagerOrganizationId` tied to the signed-in manager's initialized Workday context. Workday permissions must enforce access; prompt wording and name filtering are not authorization controls.

1. Follow [Register the template configurations](../#register-the-template-configurations). Create or verify an **Employee Self-Service Template Configuration** record with **Unique name** `msdyn_HRWorkdayHCMManagerServiceAnniversary`. Paste the entire [service-anniversary XML](./msdyn_HRWorkdayHCMManagerServiceAnniversary.xml) into **Value**. Preserve its inner scenario and request-template names.
2. Follow [Add a topic to your agent](../#add-a-topic-to-your-agent): create a blank topic in Copilot Studio, open **More > Open code editor**, and replace its contents with the complete [topic.yaml](./topic.yaml). Resolve the installed manager-check and common-execution references without changing their contracts.
3. Keep `{ManagerOrgId}` bound to `Global.ESS_UserContext_ManagerOrganizationId` and `{As_Of_Effective_Date}` bound to `Text(Today(), "yyyy-MM-dd")`. Preserve the `scenarioName`, JSON `parameters`, and `workdayResponse`, `isSuccess`, and `errorResponse` bindings. Save, enable, and resolve topic-checker errors before testing.

## Customize

Adjust trigger phrases and table labels; for example, add "Show upcoming service milestones for my direct reports." Preserve the direct-report scope and `response` output binding. If you change the hire-date extraction, keep the parsed `HireDate` field and date calculations consistent.

The declared `duration` input is not used by the calculation: the topic calculates the next anniversary, not an arbitrary nth anniversary. For "next month" requests, the model is instructed to use `isAnniversaryNextMonth`; the topic does not explicitly filter those rows in Power Fx. That flag compares the anniversary month with `Month(Now()) + 1`, which does not wrap December to January. Changing the prompt wording alone does not correct these calculation limits.

## Validate before publishing

Start a fresh conversation as an approved manager. Test team and named-report prompts, comparing hire dates, upcoming dates, milestone years, and report count with Workday. Include anniversaries today, December/January boundaries, leap-day hires, missing dates, duplicate names, and a manager with no returned reports. Verify any requested month filtering against the known behavior above before offering it to users. The sample combines response arrays by position and has no explicit multi-page retrieval loop, so check both row alignment and completeness.

Test a non-manager, another manager, and a request about someone outside the signed-in manager's scope; do not publish if out-of-scope data is disclosed. A name with no matching row can produce the same no-access message as an out-of-scope request. For retrieval failures, inspect `isSuccess` and `errorResponse`, then use the [shared validation checklist](../#validate-before-publishing) and [troubleshooting guide](../#troubleshooting). Recheck routing and table rendering in a fresh conversation after publishing.
