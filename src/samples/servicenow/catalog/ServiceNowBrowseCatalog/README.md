# ServiceNow — Browse Service Catalog

## Overview

This scenario searches the ServiceNow service catalog (`sc_cat_item`) for available items employees can request — hardware, software, access, etc.

## Trigger Phrases

- "What can I request from the IT catalog?"
- "Show me available services"
- "Browse the service catalog"
- "What hardware can I request?"

## Files

| File | Description |
|------|-------------|
| `topic.yaml` | Topic definition with search term collection and AI-formatted results |
| `msdyn_ITServiceNowCatalogBrowse.json` | Template configuration JSON for `sc_cat_item` READ operation |

## ServiceNow Table

| Table | Operation | Filter | Sort |
|-------|-----------|--------|------|
| `sc_cat_item` | READ (search) | `active=true`, `short_description LIKE {SearchTerm}` | `order` ASC |
