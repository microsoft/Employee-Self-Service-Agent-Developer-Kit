---
nav_exclude: true
search_exclude: false
---
# Workday Manager Scenarios - Custom Engine Agent (CEA)

Add read-only Workday topics to your existing Employee Self-Service (ESS) **Custom Engine Agent (CEA)** so managers can view information about their direct reports. These samples cover company codes, cost centers, job information, service anniversaries, and time in position. They retrieve Workday data; they do not update employee records.

Each scenario folder contains a Copilot Studio `topic.yaml` and an ESS Template Configuration XML file. These samples extend an installed Workday integration; they do not install an agent, connections, or system topics. For the other sample areas, see the [Workday CA overview](../), [employee scenarios](../Employee/), and [REST-based extended scenarios](../Extended/).

## Contents

| Scenario | What the topic returns | Sample prompt |
|---|---|---|
| [Company code](./WorkdayManagersdirect-CompanyCode/) | Direct reports' names, company codes, and company names | "What are the company codes for my reports?" |
| [Cost center](./WorkdayManagersdirect-CostCenter/) | Direct reports' names, cost-center codes, and cost-center names | "What cost centers are assigned to my reports?" |
| [Job information](./WorkdayManagersdirect-Jobtaxanomy/) | Direct reports' job titles, business titles, job profiles, and job-family descriptions | "Show me my team's job title" |
| [Service anniversary](./WorkdayManagerServiceAnniversary/) | Names, hire dates, upcoming anniversary dates, and milestone years | "When are the service anniversaries of all my directs?" |
| [Time in position](./WorkdayGetManagerReporteesTimeInPosition/) | Team and position details with calculated years, months, and days in the current role | "How long have my direct reports been in their current positions?" |

The time-in-position prompt is a suggested test utterance, not a configured trigger phrase. That topic uses its model description for routing.

## Before you start

- Use an editable ESS Custom Engine Agent with its HR Workday integration installed and configured. Complete [Workday integration setup](https://learn.microsoft.com/en-us/copilot/employee-self-service/workday), including authenticated connections, employee-context initialization, and permissions for the data you plan to read.
- Have maker access to the agent's environment and permission to create or update **Employee Self-Service Template Configuration** records.
- Confirm `Global.ESS_UserContext_ManagerOrganizationId` is populated from the signed-in user's Workday manager context. It must identify the appropriate Workday organization, not an employee ID or a display name. Do not hard-code another manager's organization.
- Work with your Workday administrator to validate organization scope and security-domain access. All five supplied XML files use **User** authentication and the `Human_Resources` service's `Get_Workers` operation.
- Confirm the system-topic dependencies below are installed and configured. Resolve references to your installed topics without changing their input/output bindings.
- Configure and test in a non-production environment with approved manager and employee records. A model description or name filter is not an authorization boundary; Workday permissions must enforce access.

### Required system topics

The supplied YAML uses the `msdyn_copilotforemployeeselfservicehr.topic.` schema prefix.

| System topic | Used by | Purpose |
|---|---|---|
| `WorkdaySystemGetCommonExecution` | All five scenarios | Accepts `scenarioName` and the JSON `parameters` string; returns `workdayResponse`, `isSuccess`, and `errorResponse`. |
| `WorkdayManagerCheck` | Company code, cost center, job information, and service anniversary | Checks manager status before the common-execution call. |
| `WorkdaySystemRefreshReferenceData` | Job information | Refreshes the installed job-family reference data using `ReferenceDataKey: Job_Family_ID` and `Global.JobFamilyLookupTable`. |

The time-in-position topic does **not** call `WorkdayManagerCheck`. Confirm the manager-context and access controls in your agent before exposing that scenario; do not assume every manager sample has the same guard.

## Register the template configurations

The [Workday extensibility walkthrough](https://learn.microsoft.com/en-us/copilot/employee-self-service/workday-extensibility) describes the configuration form and topic code editor. Use the exact lookup names in the table below for these samples.

1. Select the Power Platform environment containing your ESS agent and Workday integration.
2. Go to **Solutions > Default**. Select **All** if the solution is not visible.
3. Find **Employee Self-Service Template Configuration**. Check for an existing record with the required **Unique name** before creating another one. Back up the current value before updating a shared configuration.
4. To create a record, select **New > More > Other > Employee Self-Service Template Configuration**.
5. Set **Name** to a descriptive label. Set **Unique name** to the selected topic's exact lookup key below. Paste the **entire linked XML file** into **Value**, then select **Save and Close**.
6. Repeat for each scenario you intend to use. The job-information topic also requires the installed job-family reference-data setup; its primary XML alone is not that reference-data setup.

### Configuration lookup names

| Scenario | Unique name / topic `scenarioName` | XML file |
|---|---|---|
| Company code | `msdyn_HRWorkdayHCMManagerDirectCompanyCode` | [Company-code XML](./WorkdayManagersdirect-CompanyCode/msdyn_HRWorkdayHCMManagerDirectCompanyCode.xml) |
| Cost center | `msdyn_HRWorkdayHCMManagerDirectCostCenter` | [Cost-center XML](./WorkdayManagersdirect-CostCenter/msdyn_HRWorkdayHCMManagerDirectCostCenter.xml) |
| Job information | `msdyn_HRWorkdayHCMManagerJobTaxonomy` | [Job-information XML](./WorkdayManagersdirect-Jobtaxanomy/msdyn_HRWorkdayHCMManagerJobTaxonomy.xml) |
| Service anniversary | `msdyn_HRWorkdayHCMManagerServiceAnniversary` | [Service-anniversary XML](./WorkdayManagerServiceAnniversary/msdyn_HRWorkdayHCMManagerServiceAnniversary.xml) |
| Time in position | `msdyn_GetManagerReportees` | [Time-in-position XML](./WorkdayGetManagerReporteesTimeInPosition/msdyn_GetManagerReportees.xml) |

{: .important }
> **Unique name** is the configuration-record lookup key passed as `scenarioName`; it does not have to match the inner XML `<scenario name="...">` or request-template name. Paste the supplied XML without renaming its inner elements. The XML belongs in the configuration record's **Value**, not in the Workday connector's connection settings.

### Parameter bindings

| Scenarios | XML placeholders supplied by the topic | Source |
|---|---|---|
| Company code, cost center, job information, service anniversary | `{ManagerOrgId}`, `{As_Of_Effective_Date}` | `Global.ESS_UserContext_ManagerOrganizationId` and `Text(Today(), "yyyy-MM-dd")` |
| Time in position | `{Manager_Org_ID}` | `Global.ESS_UserContext_ManagerOrganizationId` |

Keep the placeholder spellings, including underscores, unchanged in both the XML and JSON parameter bindings. The time-in-position request does not supply an as-of date.

## Add a topic to your agent

1. Open the scenario folder and copy the complete `topic.yaml`. Add only the scenarios you need.
2. In your ESS agent in Copilot Studio, select **Topics > Add a topic > From blank** and give the topic a descriptive name.
3. Select **More > Open code editor**. Replace the blank topic's contents with the full YAML and save.
4. Resolve `dialog:` references to the installed system topics through the topic picker if your agent uses a different schema name. Preserve the common-execution inputs and all output bindings.
5. Review the manager-context source, configuration lookup key, XML placeholders, and any reference-data dependencies. Do not populate context with a test manager's ID as a permanent workaround.
6. Save, enable the topic, and resolve topic-checker errors. The first four topics supply trigger queries and an optional `EmployeeName` input; time in position has `intent: {}` and no `EmployeeName` input, so validate its model-based routing separately.
7. Test using the checks below before publishing. After publishing, start a new conversation in the target channel and verify routing and response rendering there too.

## How the topics use the results

- **Company code and cost center** build `Topic.workdayResponseTable` and instruct the model to present a nested Markdown list.
- **Job information** builds `Topic.workdayResponseTable`, resolving job-family IDs through `Global.JobFamilyLookupTable`. Missing reference data can leave the job-family description blank; this topic does not supply a raw-ID fallback.
- **Service anniversary** calculates `Topic.response` from Workday hire dates and today's date. Its model description requests a Markdown table with employee name, hire date, upcoming service anniversary date, and upcoming milestone.
- **Time in position** calculates `Topic.workdayResponseTableWithTimeInPosition` from each returned `PositionStartDate`. Its model description requests a table for the team and a heading with position details for one report. See the [time-in-position guide](./WorkdayGetManagerReporteesTimeInPosition/) for its fields and calculation.

The first four topics filter returned rows when `EmployeeName` is supplied, using first name, last name, or the two full-name orders. They do not perform a unique employee-ID lookup. An unmatched name can produce the same "you don't have access" message as an out-of-scope request, and duplicate names can match multiple rows. Time in position has no equivalent name-filter action.

## Customize safely

- Adjust trigger phrases and model descriptions to match your organization's vocabulary without broadening the intended direct-report scope.
- Keep the manager organization tied to the signed-in user's initialized context. Validate any change to organization scope with your integration owner.
- If you change XML response-property keys or extraction paths, update the corresponding `ParseValue` schema and table-building expressions together. Those expressions combine returned arrays by position, so check that missing fields do not misalign employee data.
- For job information, keep the job-family IDs and `Job_Family_ID` reference data consistent with the returned Workday values.
- Review date calculations and display instructions against your business rules before changing them. Do not promise arbitrary milestone or date-range filtering without implementing and testing it.

### Current behavior to validate

These are properties of the supplied samples, not changes made by this documentation:

- The service-anniversary `duration` input is declared but is not used in the calculation. The topic calculates the next anniversary, not an arbitrary requested nth anniversary.
- The service-anniversary `isAnniversaryNextMonth` flag compares the anniversary month with `Month(Now()) + 1`; December does not wrap to January. The topic asks the model to use that flag rather than explicitly filtering the output table in Power Fx. Validate any "next month" requirement, including the year boundary.
- Time in position calculates years, months, and days using `DateDiff` and `Today()`. Test month ends, leap dates, missing or future position-start dates, and the intended distinction between position tenure and employment tenure.
- The time-in-position XML does not contain an `Exclude_Inactive_Workers` filter. Do not assume it returns only active workers; confirm which records Workday returns for your organization.
- The templates do not implement an explicit multi-page retrieval loop. Compare results with the expected team size, especially for large organizations, before assuming the returned list is complete.
- The cost-center XML specifies endpoint version `v42.0` and SOAP body version `v41.0`. Company code, job information, and service anniversary use `v41.0` for both; time in position uses `v42.0` for both. Validate compatibility with your Workday integration owner rather than changing versions independently.

## Validate before publishing

Start a new test conversation for each identity so manager context and reference-data initialization are refreshed.

| Check | What to verify |
|---|---|
| Team-level read | Run each selected scenario's sample prompt. Compare returned names and values with the approved manager's Workday records, including the expected number of reports. |
| Named report | For the first four topics, test one report by first name and full name. Check duplicate names, preferred versus legal names, and a name not in the returned team. |
| Access boundary | Test a non-manager, a different manager, and a request about someone outside the signed-in manager's scope. No out-of-scope records should be disclosed. Specifically verify the time-in-position path, which lacks the explicit manager-check call. |
| Empty or incomplete data | Test a manager with no returned reports and reports with missing company, cost-center, job-family, hire-date, or position-start values. Do not present fabricated values as facts. |
| Job-family lookup | Check that `Global.JobFamilyLookupTable` is initialized and returned family IDs resolve to the expected descriptions. |
| Anniversary dates | Compare calculations with known hire dates, including anniversaries today, December/January, and leap-day cases. Verify any requested month filtering against the known behavior above. |
| Position tenure | Compare calculations with actual position-start dates, including same-day and month-end cases. Confirm model routing works without explicit trigger queries. |
| Dependency failure | Test missing configuration, unavailable reference data, and an expired or unauthorized connection using approved procedures. Inspect `isSuccess` and `errorResponse`; do not treat a parsed or generated response alone as proof of success. |
| Published channel | Verify routing, Markdown tables/lists, and access scope in a fresh conversation after publishing. |

These are validation steps to perform in your environment, not a claim that runtime testing has been completed for every deployment.

## Troubleshooting

| Symptom | Check |
|---|---|
| Configuration cannot be found | Confirm the environment, record **Unique name**, and the matching `scenarioName` in the topic. Ensure **Value** contains the complete XML; do not rename inner XML elements to guess a fix. |
| A system topic or global is unresolved | Confirm the HR Workday solution and context initialization are installed. Resolve the reference using the topic picker while keeping its contract. |
| A non-manager gets results or the wrong team appears | Stop rollout. Check signed-in context, `Global.ESS_UserContext_ManagerOrganizationId`, manager checks, and Workday permissions with the integration owner. Do not bypass the checks. |
| "You don't have access" for a known report | Inspect the unfiltered returned team and the requested name using approved diagnostics. A missing row or a legal/preferred-name mismatch can cause the name filter to return no rows. |
| Job-family descriptions are blank | Check the reference-data system topic, `Job_Family_ID`, and `Global.JobFamilyLookupTable` against Workday's returned IDs. |
| Parsing fails, columns are misaligned, or counts are incomplete | Review `isSuccess`, `errorResponse`, response-property keys, array lengths, organization scope, and Workday response paging. Do not assume a missing field means no reports exist. |
| Anniversary or tenure values look wrong | Check source dates, date parsing, today's date in the agent, and the documented calculation limits. Changing the model's wording does not fix a date formula. |
| SOAP execution fails | Review user-authenticated connections, Workday permissions, XML parameters, and the endpoint/body version combination with your integration owner. |

## Handle updates

Back up the topic and any configuration values before applying a newer sample. Review changes to both YAML and XML, preserve your tenant-specific customizations, and repeat the validation checks. Re-test other topics that share a configuration or system topic before publishing. Keep tokens, manager/employee records, and internal environment details out of public issues.
