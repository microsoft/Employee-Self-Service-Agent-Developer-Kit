---
nav_exclude: true
search_exclude: false
---
# Workday Employee Scenarios

Copilot Studio topics for employee self-service actions in Workday.

Complete the [shared configuration setup](../#set-up-the-shared-configuration-topic) once, then [create only the scenario topics you need](../#add-a-scenario) by pasting each selected `topic.yaml` into a blank Copilot Studio topic. All 22 OSS templates are supplied by the shared setup, even if you use only one employee scenario. Do not create per-scenario XML configuration records in Power Apps or Dataverse for this DA GA folder.

Keep the existing HR Workday integration and employee-context initialization configured. Review tenant-specific values and test in a fresh conversation before publishing. The [DA Preview samples](../../WorkdayDeclarativeAgentPreview/) use a different configuration process.

| Folder | Description |
| --- | --- |
| [EmployeeAddDependents/](./EmployeeAddDependents/) | Add dependents to benefits |
| [EmployeeGetVacationBalance/](./EmployeeGetVacationBalance/) | Check vacation balance |
| [EmployeeUpdateResidentialAddress/](./EmployeeUpdateResidentialAddress/) | Update residential address |
| [WorkdayEmployeeRequestTimeOff/](./WorkdayEmployeeRequestTimeOff/) | Request time off |
| [WorkdayEmployeesviewtheirjobtaxonomy/](./WorkdayEmployeesviewtheirjobtaxonomy/) | View own job taxonomy (title, function, profile) |
| [WorkdayGetContactInformation/](./WorkdayGetContactInformation/) | View own contact information |
| [WorkdayGetEducation/](./WorkdayGetEducation/) | View own education history |
| [WorkdayGetGovernmentIDs/](./WorkdayGetGovernmentIDs/) | View own government IDs |
| [WorkdayGetUserProfile/](./WorkdayGetUserProfile/) | View user profile |
| [WorkdayGivePeerFeedback/](./WorkdayGivePeerFeedback/) | Give feedback to a coworker |
| [WorkdayManageEmergencyContact/](./WorkdayManageEmergencyContact/) | Manage emergency contacts |
