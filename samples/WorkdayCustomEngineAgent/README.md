---
title: Workday (Custom Engine Agent)
parent: Samples
nav_order: 4
---
# ESS Workday Scenarios — Custom Engine Agent (CEA)

Extend your existing Employee Self-Service (ESS) **Custom Engine Agent (CEA)** with Workday topics for employees and managers. These samples include topic definitions, template configuration XML files, and setup guidance for reading Workday records and submitting self-service changes. Add only the scenarios your organization needs.

The samples do not install an agent or configure its Workday integration. Employee and manager scenarios use XML templates through the installed common-execution system topic; extended scenarios use a separate REST execution flow.

## Folder layout

| Folder | Description |
|---|---|
| [Employee/](./Employee/) | 11 employee scenarios, with detailed setup instructions, XML configuration lookup names, and individual scenario guides. |
| [Manager/](./Manager/) | Five scenarios for managers viewing their direct reports' company codes, cost centers, job information, service anniversaries, and time in position. |
| [Extended/](./Extended/) | Four REST-based topics for inbox tasks, pay slips, requesting feedback, and transferring employees, with separate setup instructions. |

## Before you start

- Use an editable ESS Custom Engine Agent with its Workday integration installed and configured. Complete the [Workday integration setup](https://learn.microsoft.com/en-us/copilot/employee-self-service/workday), including authenticated connections, employee-context initialization, and permissions for the operations you plan to use.
- Have maker access to the agent's environment and permission to manage ESS Template Configuration records. Work with your Workday administrator on security-domain and business-process permissions.
- Confirm the system topics referenced by your selected YAML are available. Employee and manager XML scenarios call `msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemGetCommonExecution`; individual topics may also require manager checks or reference-data initialization.
- Start in a non-production environment with approved test records. Read scenarios can expose employee information, and write scenarios can change Workday records or start business processes.

## Add employee or manager scenarios

1. Choose a scenario below and review its `topic.yaml`, accompanying XML files, and README where provided. The [employee setup guide](./Employee/) explains the configuration form, topic editor, and common troubleshooting steps.
2. Register every required XML file in **Employee Self-Service Template Configuration**. Set the record's **Unique name** to the exact `scenarioName` used by the topic's common-execution call, and paste the complete XML into **Value**. Check for an existing record and back it up before updating a configuration shared with other topics.
3. In Copilot Studio, select **Topics > Add a topic > From blank**. Open **More > Open code editor**, replace the blank topic's contents with the complete `topic.yaml`, and save.
4. Review tenant-specific Workday URLs, parameter bindings, IDs, picklists, and reference-data mappings. Resolve child-topic references to your installed system topics without changing their input/output contracts.
5. Test in a fresh conversation with the correct employee or manager context. Compare reads with Workday, check empty and unauthorized cases, and verify approved writes in Workday. Follow each scenario's validation guidance before publishing.

{: .important }
> The configuration record's **Unique name** is the lookup key supplied as `scenarioName`. It does not have to match the XML filename or inner `<scenario name="...">`. Preserve the supplied XML names and placeholders, and register cross-scenario dependencies as well as the selected topic's own configurations. The [employee configuration table](./Employee/#cea-configuration-lookup-names) lists the employee lookup mappings.

For inbox tasks, pay slips, requesting feedback, or transfers, follow the [Extended setup guide](./Extended/) instead. Those topics require the installed `WorkdaySystemGetRESTExecution` system topic and its REST execution flow; do not apply the XML registration steps to them.

## Employee scenarios

All 11 employee topics are listed below. Each link opens its scenario guide with dependencies, customization points, and testing instructions.

| Scenario | Description | Sample prompt(s) |
|---|---|---|
| [Add dependents](./Employee/EmployeeAddDependents/) | View existing dependents and add a dependent. | "Add a dependent" |
| [Vacation balance](./Employee/EmployeeGetVacationBalance/) | Check time-off balances as of a selected date. | "What is my vacation balance?" |
| [Residential address](./Employee/EmployeeUpdateResidentialAddress/) | View, add, or update your home address. | "Update my home address" |
| [Request time off](./Employee/WorkdayEmployeeRequestTimeOff/) | Submit a single-day or multi-day time-off request. | "I want to request time off" |
| [Job information](./Employee/WorkdayEmployeesviewtheirjobtaxonomy/) | View your title, business title, job profile, and job family. | "What is my job title?" |
| [Contact information](./Employee/WorkdayGetContactInformation/) | View your work and home contact details. | "What is my work phone?" |
| [Education](./Employee/WorkdayGetEducation/) | View your schools, degrees, and other education details. | "Show my education details" |
| [Government IDs](./Employee/WorkdayGetGovernmentIDs/) | View government-ID information in your profile. | "What are my government IDs?" |
| [User profile](./Employee/WorkdayGetUserProfile/) | View your personal, employment, and contact information. | "Show my employee profile" |
| [Peer feedback](./Employee/WorkdayGivePeerFeedback/) | Submit feedback about a colleague. | "Give feedback" |
| [Emergency contacts](./Employee/WorkdayManageEmergencyContact/) | View, add, update, or remove emergency contacts. | "Manage my emergency contacts" |

## Manager scenarios

These scenarios retrieve information about the requesting manager's direct reports. Confirm manager context and Workday permissions before testing.

| Scenario | Description | Sample prompt |
|---|---|---|
| [Company code](./Manager/WorkdayManagersdirect-CompanyCode/) | View company codes and names for direct reports. | "What are the company codes for my reports?" |
| [Cost center](./Manager/WorkdayManagersdirect-CostCenter/) | View cost-center details for direct reports. | "What cost centers are assigned to my reports?" |
| [Job information](./Manager/WorkdayManagersdirect-Jobtaxanomy/) | View job titles, business titles, job profiles, and job families for direct reports. | "Show me my team's job title" |
| [Service anniversary](./Manager/WorkdayManagerServiceAnniversary/) | View upcoming service anniversaries for direct reports. | "When are the service anniversaries of all my directs?" |
| [Time in position](./Manager/WorkdayGetManagerReporteesTimeInPosition/) | View how long direct reports have been in their current roles. | "How long have my direct reports been in their current positions?" |

## Extended scenarios

See the [Extended guide](./Extended/) for REST prerequisites, topic installation, namespace checks, and configuration.

| Topic | Description |
|---|---|
| [GetInboxTasks.yaml](./Extended/GetInboxTasks.yaml) | View open Workday inbox tasks. |
| [GetPaySlips.yaml](./Extended/GetPaySlips.yaml) | View recent pay slips. |
| [RequestFeedback.yaml](./Extended/RequestFeedback.yaml) | Request feedback from a coworker. |
| [TransferEmployee.yaml](./Extended/TransferEmployee.yaml) | Transfer a direct report to a new manager. |