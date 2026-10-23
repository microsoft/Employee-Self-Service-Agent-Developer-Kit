---
nav_exclude: true
search_exclude: false
---
# Workday Manager Scenarios

Copilot Studio topics for manager self-service actions in Workday.

Configure the [shared template-config setup topic](../#set-up-the-shared-configuration-topic) once, then [create only the scenario topics you need](../#add-a-scenario) by pasting each selected `topic.yaml` into a blank Copilot Studio topic. Use the same configuration for employee and manager scenarios.

{: .warning }
> Your HR user-context initializer must populate `Global.ESS_UserContext_Is_Manager` and `Global.ESS_UserContext_ManagerOrganizationId` from the authenticated user's Workday context. Resolve missing context or unrecognized-variable errors before using these scenarios. Never hard-code manager context or infer manager privileges solely from a nonblank organization ID.

Preserve the existing Workday execution and access-check topics. Validate manager and non-manager behavior in fresh test conversations before publishing; running the shared template-config setup topic does not itself grant access or validate the manager integration.

| Folder | Description |
| --- | --- |
| [WorkdayGetManagerReporteesTimeInPosition/](./WorkdayGetManagerReporteesTimeInPosition/) | View reportees' time in position |
| [WorkdayManagerServiceAnniversary/](./WorkdayManagerServiceAnniversary/) | View reportees' upcoming service anniversaries |
| [WorkdayManagersdirect-CompanyCode/](./WorkdayManagersdirect-CompanyCode/) | View reportees' company code and company name |
| [WorkdayManagersdirect-CostCenter/](./WorkdayManagersdirect-CostCenter/) | View reportees' cost center details |
| [WorkdayManagersdirect-Jobtaxanomy/](./WorkdayManagersdirect-Jobtaxanomy/) | View reportees' job taxonomy |
