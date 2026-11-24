---
nav_exclude: true
search_exclude: false
---
# Workday Manage Emergency Contact

## Overview

This topic enables employees to manage their emergency contacts in Workday through a conversational interface. Employees can view existing contacts, add new emergency contacts, update existing ones, and delete contacts they no longer need.

## Features

- View existing emergency contacts with primary contact highlighted
- Add new emergency contacts with full details
- Update details of existing emergency contacts
- Delete non-primary emergency contacts
- Set or change the primary emergency contact
- Assign priority levels (2-10) to contacts

## Snapshots

![Manage Emergency Contact](update_emergency_contact.png)

![Emergency Contact Form](update_emergency_contact_2.png)

## Trigger Phrases

- "Manage my emergency contacts"
- "Update my emergency contact"
- "Add emergency contact"
- "Change my emergency contact information"
- "Delete my emergency contact"
- "Show my emergency contacts"

## Files

| File | Description |
|------|-------------|
| `topic.yaml` | Copilot Studio topic definition with conversation flow |
| `msdyn_HRWorkdayHCMEmployeeGetEmergencyContactInfo.xml` | XML template to fetch existing emergency contacts |
| `msdyn_HRWorkdayHCMEmployeeAddEmergencyContact.xml` | XML template to add a new emergency contact |
| `msdyn_HRWorkdayHCMEmployeeUpdateEmergencyContact.xml` | XML template to update an existing emergency contact |
| `msdyn_HRWorkdayDeleteEmergencyContact.xml` | XML template to delete an emergency contact |

## Setup

Follow the [CEA prerequisites](../#before-you-start) and [register all four template configurations](../#register-the-template-configurations). The update and delete lookup names differ from the filenames:

| XML file | Unique name / topic `scenarioName` |
|---|---|
| `msdyn_HRWorkdayHCMEmployeeGetEmergencyContactInfo.xml` | `msdyn_HRWorkdayHCMEmployeeGetEmergencyContactInfo` |
| `msdyn_HRWorkdayHCMEmployeeAddEmergencyContact.xml` | `msdyn_HRWorkdayHCMEmployeeAddEmergencyContact` |
| `msdyn_HRWorkdayHCMEmployeeUpdateEmergencyContact.xml` | `msdyn_UpdateEmergencyContact` |
| `msdyn_HRWorkdayDeleteEmergencyContact.xml` | `msdyn_DeleteEmergencyContact` |

Review the country/state choices and replace `<TENANT_NAME>` in both Workday-link assignments, `set_workday_url_2` and `set_workday_url`. Then [add this scenario](../#add-a-scenario) by pasting the complete `topic.yaml` into a blank topic's code editor, resolving the CEA system-topic references, saving, and enabling it.

Keep `msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemGetCommonExecution` and `msdyn_copilotforemployeeselfservicehr.topic.GetReferenceData` configured. Reference-data keys `Country_Phone_Code_ID` and `Related_Person_Relationship_ID` populate `Global.CountryCodeLookupTable` and `Global.RelatedPersonRelationshipLookupTable`; the topic also initializes sample `Global.StateProvinceChoices`.

## Workday APIs Used

| API | Purpose |
|-----|---------|
| `Get_Workers` | Retrieve employee's existing emergency contacts |
| `Change_Emergency_Contacts` | Add, update, or delete emergency contact information |

## Flow Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    User Triggers Topic                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│      Fetch Reference Data (Country Codes, Relationships)    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Fetch Existing Emergency Contacts               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│     Show Selection Card (or Go to Add if no contacts)        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│          Show Add/Update Form (Adaptive Card)                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Submit to Workday                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│           Show Success/Error Message                         │
└─────────────────────────────────────────────────────────────┘
```

## Configurations

Environment makers need to configure the following in the topic:

| Configuration | Description | Location in Topic |
|---------------|-------------|-------------------|
| **Relationship Types** | Available relationship options from Workday reference data | Dynamic from GetReferenceData |
| **Country Codes** | Phone country codes from Workday reference data | Dynamic from GetReferenceData |
| **States/Provinces** | Available state/province codes per country | Adaptive card dropdown |
| **Workday Icon** | Update the icon URL to match your organization's branding | `set_workday_icon_url_2` |
| **Workday URL** | Set the user-facing Workday links; this does not configure connector authentication | `set_workday_url_2` and `set_workday_url` |

## Dependencies

- **Employee Context**: Worker ID must be available in the conversation context

## Test and troubleshoot

In fresh conversations, test no contacts and multiple contacts, required fields, country/relationship choices, and **Cancel**. With approved test data, add and update a contact, verify primary-contact behavior, cancel a delete confirmation, and delete a non-primary test contact. The topic blocks deletion of the primary contact. Verify changes in Workday rather than relying solely on the result card.

The XML uses Human_Resources v45.0. Add uses `Auto_Complete` `true`, while update and delete use `false`; review these business-process settings with your Workday owner. If reads work but an update/delete fails, check the exact configuration lookup names above and `isSuccess`/`errorResponse`. Use the [shared CEA troubleshooting checks](../#troubleshooting) before publishing.
