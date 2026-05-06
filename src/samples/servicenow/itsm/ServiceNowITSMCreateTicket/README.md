# ServiceNow ITSM — Create IT Incident

## Overview

This scenario allows employees to create an IT support incident in ServiceNow ITSM. The topic collects a summary, description, category, and urgency, confirms via an Adaptive Card, and submits through the shared ESS orchestrator flow.

## Trigger Phrases

- "I need to create an IT ticket"
- "Open an IT support request"
- "I have a technical issue"
- "My laptop is broken"
- "Submit an IT incident"

## Files

| File | Description |
|------|-------------|
| `topic.yaml` | Topic definition with category/urgency selection and Adaptive Card confirmation |
| `msdyn_ITServiceNowITSMCreateTicket.json` | Template configuration JSON for the ServiceNow `incident` CREATE operation |

## ServiceNow Table

| Table | Operation | Key Fields |
|-------|-----------|------------|
| `incident` | CREATE | `short_description`, `description`, `category`, `urgency`, `caller_id`, `assignment_group` |

## Setup Notes

- Replace `<YOUR_IT_ASSIGNMENT_GROUP_SYS_ID>` in the template config with your organization's IT helpdesk assignment group sys_id.
- Customize the category options in the topic to match your ServiceNow incident categories.
- The `caller_id` field is populated from the user context alias.
