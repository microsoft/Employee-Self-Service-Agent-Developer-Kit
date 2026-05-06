# ServiceNow ITSM — Get Ticket Details

## Overview

This scenario retrieves the details of a specific IT incident by ticket number. The topic auto-extracts the ticket number from the user's request or prompts for it.

## Trigger Phrases

- "What's the status of my IT ticket?"
- "Check on my IT ticket"
- "Give me an update on my incident"
- "What happened with ticket INC0012345?"

## Files

| File | Description |
|------|-------------|
| `topic.yaml` | Topic definition with automatic ticket number extraction |
| `msdyn_ITServiceNowITSMGetTicketDetails.json` | Template configuration JSON for `incident` READ by number |

## ServiceNow Table

| Table | Operation | Filter |
|-------|-----------|--------|
| `incident` | READ (single) | `number` = user-provided ticket number |
