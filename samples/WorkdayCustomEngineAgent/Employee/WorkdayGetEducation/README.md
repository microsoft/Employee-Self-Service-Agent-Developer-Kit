---
nav_exclude: true
search_exclude: false
---
# View your education — Custom Engine Agent

This topic reads your own education history from Workday, including school, degree, field of study, country, and years attended. Try "Show my education details" or "What was my field of study?" It does not answer tuition-reimbursement or training-policy questions.

The topic calls the CEA common-execution system topic, parses education records, refreshes country/degree/field-of-study reference data, and returns `FinalizedEducationData` for the agent's response.

## Files

| File | Description |
|---|---|
| [topic.yaml](./topic.yaml) | Education read, reference lookups, and response mapping |
| [msdyn_HRWorkdayHCMEmployeeGetEducation.xml](./msdyn_HRWorkdayHCMEmployeeGetEducation.xml) | Workday `Get_Workers`, Human_Resources v41.0 request and response mapping |

## Setup

Follow the [CEA prerequisites](../#before-you-start) and [register the template configuration](../#register-the-template-configurations) with **Unique name** `msdyn_HRWorkdayHCMEmployeeGetEducation` and the complete XML in **Value**. Preserve its inner XML names; they are not the configuration record's lookup key.

Then [add this scenario](../#add-a-scenario) by pasting the complete `topic.yaml` into a blank topic's code editor, resolving the CEA system-topic references, saving, and enabling it.

## Dependencies and customization

The topic uses these installed CEA dialogs:

- `msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemGetCommonExecution`
- `msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemRefreshReferenceData`

Confirm reference data is available for `ISO_3166-1_Alpha-2_Code`, `Degree_ID`, and `Field_Of_Study_ID`. The corresponding globals are `Global.CountryNameLookupTable`, `Global.DegreeTypeLookupTable`, and `Global.FieldOfStudyLookupTable`.

The employee-context initializer must populate `Global.ESS_UserContext_Employee_Id`, `Global.ESS_UserContext_Employee_Firstname`, and `Global.ESS_UserContext_Employee_Lastname`.

You can customize trigger wording and response labels, for example "qualification" instead of "degree," without changing the lookup keys, XML placeholders, or parser schema. Keep the optional `EmployeeName` input separate from the authenticated ID used in the request.

## Test and troubleshoot

Use fresh conversations to test an employee with multiple education entries, an employee with no education history, and an out-of-scope question about tuition policy or another person's records. Compare returned schools, dates, and reference labels with approved Workday test data.

If schools appear but country, degree, or field-of-study labels are blank, inspect the matching reference table and its ID/type mapping. If the read fails, inspect the common-execution outputs and configuration lookup before the parser. Follow the [shared CEA troubleshooting checks](../#troubleshooting) before publishing.
