---
nav_exclude: true
search_exclude: false
---
# Workday Get Manager Reportees Time In Position

## Overview
This scenario enables managers to view their direct reports along with how long each employee has been in their current position. It retrieves team member information from Workday HCM and calculates the time in position for each reportee.

## Files

| File | Description |
|------|-------------|
| [topic.yaml](./topic.yaml) | Copilot Studio topic definition with model-routing instructions and Power Fx logic |
| [msdyn_GetManagerReportees.xml](./msdyn_GetManagerReportees.xml) | XML template for the Workday Get_Workers API call |

## Prerequisites

### Global Variables Required
- `Global.ESS_UserContext_ManagerOrganizationId` - The manager's organization ID in Workday (used to filter direct reports)

Use initialized context for the signed-in manager, not a hard-coded organization ID. This topic does not call `WorkdayManagerCheck`; validate manager access and Workday permissions before enabling it. Follow the [manager setup guide](../#before-you-start) for the installed integration and common-execution prerequisites.

### Workday API
- **Service**: Human_Resources
- **Operation**: Get_Workers
- **Version**: v42.0

## Scenario Details

### What It Does
1. Retrieves the workers Workday returns for the manager's organization
2. Extracts key employee information (Name, Title, Position Start Date, etc.)
3. Calculates Time in Position for each employee using Power Fx DateDiff functions
4. Presents results with tenure information formatted as "X years Y months Z days"

### Data Retrieved
| Field | Description |
|-------|-------------|
| EmployeeID | Workday Employee ID |
| Name | Worker's descriptor returned by Workday |
| BusinessTitle | Current job title |
| WorkerType | Employee or Contingent Worker |
| JobProfile | Job profile name |
| Location | Business site/location name |
| PositionStartDate | Date employee started current position |
| HireDate | Original hire date |
| Status | Active/Inactive status |
| TimeInPositionYears | Calculated years in current position |
| TimeInPositionMonths | Calculated remaining months |
| TimeInPositionDays | Calculated remaining days |
| TimeInPosition | Formatted string (e.g., "2 years 3 months 15 days") |

### Suggested Test Prompts

The supplied topic has `intent: {}` and no explicit trigger-query list. These are suggested utterances for testing its model-description-based routing, not trigger phrases already configured in the YAML. It also has no `EmployeeName` input or deterministic per-name filter.

- "Show me my team's time in position"
- "How long have my direct reports been in their roles"
- "Get reportees time in current position"
- "List my team members with their position tenure"
- "Who on my team has been in their role the longest"
- "Show tenure for my direct reports"
- "My reportees job tenure"
- "Time in position for my team"

## Time In Position Calculation

The topic parses each `PositionStartDate`, calculates elapsed months through `Today()`, splits those into years and remaining months, and calculates days from the month-adjusted position-start date. `TimeInPosition` formats the nonzero year/month components and the day component into a readable string.

Validate month-end, leap-date, missing-date, and future-date cases against your business rules. Position tenure is based on `PositionStartDate`, not `HireDate`. The display does not insert commas between components.

## Response Group Configuration

The XML template is optimized for performance by:
- **Including**: Reference and Employment Information
- **Excluding personal information**: `Include_Personal_Information` and `Show_All_Personal_Information` are `false`; the name comes from the worker descriptor.
- **Excluding**: Compensation, Benefits, Documents, Photos, and other unnecessary data
- **Scope**: Organization reference `{Manager_Org_ID}`. The template does not specify `Exclude_Inactive_Workers` or implement a multi-page retrieval loop; verify returned worker status and completeness in your environment.

## Setup Instructions

1. Follow [Register the template configurations](../#register-the-template-configurations). Create or verify an ESS Template Configuration record with **Unique name** `msdyn_GetManagerReportees` and the complete `msdyn_GetManagerReportees.xml` in **Value**. Do not upload the XML to the connector's connection settings.
2. In Copilot Studio, select **Topics > Add a topic > From blank**, name the topic, and open **More > Open code editor**. Replace the blank topic with the complete `topic.yaml` and save.
3. Resolve the installed `msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemGetCommonExecution` reference. Preserve its `scenarioName` and JSON `parameters` inputs and `workdayResponse`, `isSuccess`, and `errorResponse` outputs.
4. Confirm `Global.ESS_UserContext_ManagerOrganizationId` is initialized for the signed-in manager and is passed as `{Manager_Org_ID}`. This request does not supply an as-of date.
5. Resolve topic-checker errors, enable the topic, and follow the [manager validation checklist](../#validate-before-publishing) before publishing.

## Model Instructions

The topic includes model instructions for the AI to:
- Display a team response as a Markdown table with Name, Title, and Time in Position
- Use a heading and position-detail sections for a single report
- Format Time in Position clearly
- Base the response on the returned `workdayResponseTableWithTimeInPosition`

These are model instructions, not a deterministic name-filter or authorization check.

## Example Output

For a team-level prompt, the model is instructed to produce a table. An illustrative response is shown below; actual names, titles, and durations must come from the approved test data.

```
Team roles and time in position

Here's a list of your team members and how long they've been in their positions.
I pulled this from Workday, an HR platform your company uses.

| Name | Title | Time in Position |
|---|---|---|
| Example report A | Senior Developer | 2 years 5 months 12 days |
| Example report B | Product Manager | 1 year 2 months 3 days |
```

## Validation and Troubleshooting

- Start a new conversation as an approved manager. Compare the returned names, position-start dates, and team count with Workday.
- Test a non-manager and a request outside the signed-in manager's scope. Do not publish if those requests expose out-of-scope data.
- Verify model routing for the suggested prompts and review single-person requests carefully because the YAML does not filter rows by name.
- If retrieval fails, inspect `isSuccess` and `errorResponse`, the configuration lookup key, manager organization, user-authenticated connection, and Workday permissions before investigating date calculations.
- If tenure looks wrong, compare the raw position-start date with the calculated year/month/day values. Do not substitute hire date to hide a missing position date.
- See the [manager troubleshooting table](../#troubleshooting) for shared configuration, parsing, and access checks.
