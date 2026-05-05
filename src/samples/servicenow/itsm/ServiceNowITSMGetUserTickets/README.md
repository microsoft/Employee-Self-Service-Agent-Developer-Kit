# ServiceNow ITSM — Get User IT Tickets

## Overview

This scenario retrieves the requesting user's IT incident tickets from ServiceNow ITSM, displaying ticket number, summary, status, priority, and last updated date.

## Trigger Phrases

- "Show me my IT tickets"
- "What are my open incidents?"
- "Do I have any IT support tickets?"
- "List my helpdesk tickets"

## Files

| File | Description |
|------|-------------|
| `topic.yaml` | Topic definition with AI-formatted response |
| `msdyn_ITServiceNowITSMGetUserTickets.json` | Template configuration JSON for `incident` READ operation |

## ServiceNow Table

| Table | Operation | Filter | Sort |
|-------|-----------|--------|------|
| `incident` | READ (list) | `caller_id` = current user | `sys_updated_on` DESC |
