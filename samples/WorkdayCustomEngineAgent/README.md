---
title: Workday (Custom Engine Agent)
parent: Samples
nav_order: 4
---
# ESS Workday Scenarios — Custom Engine Agent (CEA)

This folder contains sample **Custom Engine Agent (CEA)** topic definitions and ESS Template Configuration XMLs that customers can use to extend the functionality of their ESS Agent. Use the topic definitions (`topic.yaml`) and the accompanying Template Configuration XML file to create new topics in your environment or to customize the behavior of existing topics for the scenarios listed below.

> Looking for the Declarative Agent variant? See [../WorkdayDeclarativeAgent/](../WorkdayDeclarativeAgent/).

## Folder layout

| Folder | Description |
|---|---|
| [Employee/](./Employee/) | Self-service topics for the requesting employee (vacation balance, time-off requests, profile, contact info, education, government IDs, dependents, emergency contacts, peer feedback, etc.). |
| [Manager/](./Manager/) | Topics for managers acting on their direct reports (company code, cost center, job taxonomy, service anniversary, time in position). |
| [Extended/](./Extended/) | Additional standalone topic YAMLs (inbox tasks, pay slips, request feedback, transfer employee). |

## Usage notes

- Each scenario folder contains a `topic.yaml` (the Copilot Studio topic) and a Template Configuration XML used by the topic.
- Copy `topic.yaml` into your Copilot topic catalog and ensure the Template Configuration is added to the Employee Self Service Template Configuration.
- Update parameter bindings (for example employee id, manager org id, effective date) to match your runtime context.
- The `topic.yaml` files include trigger queries (sample prompts). Use those as seeds for testing.

## Scenarios

Below is a consolidated table that lists each scenario, a short description, and sample prompt(s) you can use to test the topic.

| Scenario | Description | Sample prompt(s) |
|---|---|---|
| `EmployeeGetVacationBalance` | Returns the requesting user's vacation balance information from Workday. Displays available time off that can be taken. | "What is my vacation balance?"<br>"How much time off can I take?"<br>"What is my workday vacation balance?" |
| `WorkdayEmployeeRequestTimeOff` | Allows employees to submit time off requests for themselves through Workday. Prompts for necessary details like dates and hours. | "Request 8 hours vacation on 2025-09-15"<br>"I want to request time off"<br>"Submit vacation request" |
| `WorkdayEmployeesviewtheirjobtaxonomy` | Responds to requests about the requesting user's job taxonomy (job title, job function, job profile). | "What is my job title?"<br>"What is my external title?" |
| `WorkdayGetContactInformation` | Returns the requesting user's contact information (work/home phones, emails, addresses). | "What is my Work Phone?"<br>"Show my Home Email" |
| `WorkdayGetEducation` | Returns the requesting user's education history (school, degree, field of study, years attended). | "Show my Education Details"<br>"What was my field of study?" |
| `WorkdayGetGovernmentIDs` | Returns government ID information associated with the requesting user's profile (ID types, issued/expiration dates, country). | "What are my Government Ids?" |
| `WorkdayManagersdirect-CompanyCode` | Returns company code and company name for employees who directly report to the requesting user (manager view). Output is produced as a nested markdown list. | "What are the company codes for my reports?" |
| `WorkdayManagersdirect-CostCenter` | Returns cost center details for direct reports of the requesting user. Output is produced as a nested markdown list. | "What is the cost center of my direct reports?" |
| `WorkdayManagersdirect-Jobtaxanomy` | Returns job taxonomy (job title, business title, job profile, job family) for the manager's direct reports. Output is produced as a nested markdown list. | "Show me my team's job title"<br>"What is the job title of [EmployeeName]?" |
| `WorkdayManagerServiceAnniversary` | Returns upcoming service anniversaries for a manager's direct reports. The topic returns a markdown table with Employee Name, Hire Date, Upcoming Service Anniversary Date, Upcoming Milestone. | "When are the service anniversaries of all my directs?"<br>"What is [EmployeeName]'s next service anniversary?" |