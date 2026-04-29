# ServiceNow HRSD — Create HR Case

## Overview

This scenario allows employees to create an HR case in ServiceNow HRSD. The topic collects a subject, description, and priority from the user, confirms the details via an Adaptive Card, then submits the case through the shared ESS orchestrator flow.

## Trigger Phrases

- "I need to create an HR case"
- "Open an HR service request"
- "I need help from HR"
- "Submit an HR case"
- "I have an HR issue I need to report"

## Files

| File | Description |
|------|-------------|
| `topic.yaml` | Topic definition with conversation flow and Adaptive Card confirmation |
| `msdyn_HRServiceNowHRSDCreateCase.json` | Template configuration JSON for the ServiceNow `sn_hr_core_case` CREATE operation |

## ServiceNow Table

| Table | Operation | Key Fields |
|-------|-----------|------------|
| `sn_hr_core_case` | CREATE | `short_description`, `description`, `priority`, `opened_for`, `assignment_group` |

## Setup Notes

- Replace `<YOUR_HR_ASSIGNMENT_GROUP_SYS_ID>` in the template config with your organization's HR assignment group sys_id.
- The `opened_for` field is populated from the user context alias (`Global.ESS_UserContext_Alias`).
