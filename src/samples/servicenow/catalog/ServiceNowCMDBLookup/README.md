# ServiceNow — CMDB Asset Lookup

## Overview

This scenario searches the ServiceNow CMDB (`cmdb_ci`) for configuration items (CIs) such as laptops, servers, applications, and other IT assets.

## Trigger Phrases

- "Look up my laptop in the CMDB"
- "Find asset LAPTOP-12345"
- "What's the status of server PROD-WEB-01?"
- "Show me CI details"

## Files

| File | Description |
|------|-------------|
| `topic.yaml` | Topic definition with automatic asset name extraction |
| `msdyn_ITServiceNowCMDBLookup.json` | Template configuration JSON for `cmdb_ci` READ operation |

## ServiceNow Table

| Table | Operation | Filter | Sort |
|-------|-----------|--------|------|
| `cmdb_ci` | READ (search) | `name LIKE {AssetName}` | `name` ASC |
