# ServiceNow HRSD — Get User HR Cases

## Overview

This scenario retrieves the requesting user's HR cases from ServiceNow HRSD, displaying case number, subject, status, priority, and dates.

## Trigger Phrases

- "Show me my HR cases"
- "What are my open HR cases?"
- "Do I have any HR cases?"
- "List my HR service requests"

## Files

| File | Description |
|------|-------------|
| `topic.yaml` | Topic definition with AI-formatted response |
| `msdyn_HRServiceNowHRSDGetUserCases.json` | Template configuration JSON for `sn_hr_core_case` READ operation |

## ServiceNow Table

| Table | Operation | Filter | Sort |
|-------|-----------|--------|------|
| `sn_hr_core_case` | READ (list) | `opened_for` = current user | `sys_created_on` DESC |
