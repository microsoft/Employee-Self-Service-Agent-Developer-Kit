---
nav_exclude: true
search_exclude: false
---
# View your contact information — Custom Engine Agent

This topic retrieves your own work and home phone numbers, email addresses, and addresses from Workday. Try "What is my work phone?" or "Show my home email." It is a personal-record lookup, not a way to retrieve a colleague's contact information.

The topic calls the CEA common-execution system topic for work contacts, home contacts, and work address, parses each response, and returns `finalizedContactInformation`. All three reads run even when you ask for only one field.

## Files

| File | Description |
|---|---|
| [topic.yaml](./topic.yaml) | Contact reads, response parsing, and final record |
| [msdyn_HRWorkdayHCMEmployeeGetHomeContactInformation.xml](./msdyn_HRWorkdayHCMEmployeeGetHomeContactInformation.xml) | Home-contact request and response mapping |

## Setup

Follow the [CEA prerequisites](../#before-you-start) and [register the template configurations](../#register-the-template-configurations). Store this folder's complete XML in a record whose **Unique name** is `msdyn_HRWorkdayHCMEmployeeGetHomeContactInformation`.

The installed Workday integration must also supply `msdyn_HRWorkdayHCMEmployeeGetWorkContactInformation` and `msdyn_HRWorkdayHCMEmployeeGetWorkAddress`. Those XML files are not included here. Do not replace them with the home-contact XML.

Then [add this scenario](../#add-a-scenario) by pasting the complete `topic.yaml` into a blank topic's code editor, resolving the CEA system-topic reference, saving, and enabling it.

## Dependencies and customization

Keep `msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemGetCommonExecution` configured. The requests use `Global.ESS_UserContext_Employee_Id` and today's effective date; the final response uses `Global.ESS_UserContext_Employee_Firstname` and `Global.ESS_UserContext_Employee_Lastname`.

You can customize `modelDescription`, trigger wording, and displayed labels, for example to use "personal email" instead of "home email." Preserve the scenario lookup keys, JSON parameter names, and parsed response bindings. The optional `EmployeeName` input must not replace the authenticated employee ID.

## Test and troubleshoot

Start a new test conversation and compare a work-phone request and a home-email request with the signed-in test employee's Workday data. Check primary indicators, multiple contact entries, and absent optional home-contact fields. Also test a request for another employee and verify that no other employee's data is disclosed.

If a single-field request fails, inspect which of the three calls failed, its `isSuccess`/`errorResponse` outputs, and its configuration record. A registered home-contact template alone is not sufficient. Use the [shared CEA troubleshooting checks](../#troubleshooting) before publishing.
