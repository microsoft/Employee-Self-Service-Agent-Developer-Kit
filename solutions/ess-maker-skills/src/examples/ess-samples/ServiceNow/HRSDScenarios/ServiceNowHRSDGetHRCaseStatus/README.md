# ServiceNow HRSD — Get HR Case Status

## Overview

This scenario lets an employee check the status of a specific open HR case in ServiceNow HRSD. The employee provides their case number; the topic calls the ServiceNow HRSD system topic with the case number and the employee's email, retrieves the matching case, and displays the case number, state, and short description in an Adaptive Card.

## Trigger Phrases

- "What is the status of my HR case?"
- "Check my HR case status"
- "What's happening with my open HR case?"
- "Give me an update on my HR case"
- "Track my HR case"
- "Check my HR case CS0012345"

## Files

| File | Description |
|------|-------------|
| `topic.yaml` | Topic definition with case number input and Adaptive Card result display |
| `msdyn_HRServiceNowHRSDGetHRCaseStatus.json` | Template configuration JSON for `sn_hr_core_case` READ by case number and employee email |

## ServiceNow Table

| Table | Operation | Filter | Limit |
|-------|-----------|--------|-------|
| `sn_hr_core_case` | READ (single) | `number` = case number AND `opened_for` = employee email | 1 |
