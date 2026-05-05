# FlightCheck ??? Developer Guide

This document provides guidance for agents and developers adding new checks
to the FlightCheck tool.

## Architecture Overview

FlightCheck validates customer deployments by querying multiple APIs. Each API
requires its own authentication and has different data available:

| API Layer | Client | Auth Resource / Scope | What's Available |
|-----------|--------|----------------------|------------------|
| Dataverse | `auth.py` | `{env_url}/user_impersonation` | Bot components (topics, variables, knowledge source *config*), template configs, solution metadata |
| Microsoft Graph | `graph_client.py` | `https://graph.microsoft.com/.default` | Licenses, user roles, Entra app registrations, CA policies |
| Power Platform Admin (BAP) | `pp_admin_client.py` | `https://service.powerapps.com//.default` | Environments, cloud flows, connections, DLP policies |
| Island Gateway (Copilot Studio) | `pva_client.py` | `96ff4394-9197-43aa-b393-6a41652e21f8/.default` | Live bot component status, model config, knowledge source *runtime state* |

**Critical distinction:** Dataverse stores *configuration* (YAML source files,
component metadata). The Island Gateway stores *runtime state* (active/inactive
status, crawl progress, model assignments). If you need to check whether
something is *configured*, query Dataverse. If you need to check whether it's
*working*, query the Island Gateway.

This table is not exhaustive. New checks may require APIs not listed here. If
the data you need isn't available from any existing client, research the correct
API, document it, add a row to this table, and create a new client following
existing patterns.

## Island Gateway API Reference

The Island Gateway is how Copilot Studio's UI reads/writes bot state. It lives
at a region-specific URL discovered via BAP:

```
Gateway URL:  properties.runtimeEndpoints["microsoft.PowerVirtualAgents"]
              (from BAP environment record)
Example:      https://powervamg.us-il102.gateway.prod.island.powerapps.com
```

**Required headers** (all requests):
```
Authorization: Bearer {pva_token}
x-ms-client-tenant-id: {tenant_id}
x-cci-tenantid: {tenant_id}
x-cci-bapenvironmentid: {bap_env_id}
x-cci-cdsbotid: {bot_id}            (optional, for bot-scoped requests)
```

**Key gotcha:** The BAP environment ID is NOT the same as the Dataverse
environment ID. The BAP env ID is discovered by listing environments from the
BAP API and matching on the Dataverse instance URL. See `pva_client.py`
`_discover_gateway()` for the implementation pattern.

**Read all bot components:**
```
POST /api/botmanagement/v1/environments/{bapEnvId}/bots/{botId}/content/botcomponents
Body: {}
```

Response contains `botComponentChanges[]`, each with a `component` object:
- `component.$kind`: `DialogComponent`, `KnowledgeSourceComponent`, `GptComponent`,
  `GlobalVariableComponent`, `CustomEntityComponent`
- `component.state` / `component.status`: runtime status (e.g., "Active", "Inactive")
- `component.displayName`, `component.id`, `component.schemaName`

**External reference:** The `microsoft/MCS-Agent-Builder` repo has detailed
API documentation in `knowledge/cache/island-gateway-api.md` and a working
Node.js client in `tools/island-client.js`.

## Dataverse `botcomponents` Entity

The `botcomponents` entity set stores agent components. Key facts:

- **No `msdyn_` prefix** ??? the entity set is just `botcomponents` (not
  `msdyn_botcomponents`)
- **Filter by bot:** `_parentbotid_value eq '{botId}'`
- **Filter by type:** `componenttype eq {N}` where common types are:
  - `16` = Knowledge source
  - `1` = Dialog/Topic
  - `68` = Global variable
- **The `data` column is YAML** (the `.mcs.yml` file content), NOT JSON. Do
  not try to `json.loads()` it. Parse with a YAML library if needed.
- **`statecode`/`statuscode`** are standard Dataverse record status (Active=0/1),
  NOT the runtime crawl/index status.

## Design Principles

1. **No misleading results.** If a check cannot actually validate what it claims
   to validate (e.g., missing API access), report `SKIPPED` ??? never `PASSED`.
   A check that always passes is worse than no check at all.

2. **Fail loudly on API errors.** If an API call fails, let the exception
   propagate to the caller so it can be reported as a WARNING with the actual
   error message. Do not silently return empty results.

3. **One check, one concern.** Each check should validate exactly one thing.
   Don't bundle multiple validations under a single checkpoint ID.

4. **Follow existing client patterns.** New API integrations should follow the
   same structure as `graph_client.py` / `pp_admin_client.py` / `pva_client.py`:
   - Class with `authenticate()` method
   - Uses shared MSAL token cache at `my/.token_cache.bin`
   - Initialized in `cli.py`, attached to `runner`
   - Gracefully skips if auth fails (print warning, set to None)

5. **No fabricated URLs.** Every URL in code must point to a page you have
   confirmed exists. If no doc page exists, leave the link empty with a
   `# TODO: create doc page at ...` comment.

## Adding a New Check

1. Identify which API has the data you need. Check existing clients first (see
   table above). If the data isn't available from any existing client, research
   the correct API ??? check the `microsoft/MCS-Agent-Builder` repo's
   `knowledge/cache/` folder for API documentation, or inspect network traffic
   in the relevant admin UI (Copilot Studio, Power Platform Admin Center, etc.)
2. If a new client is needed, create it following existing patterns and add it
   to the table above
3. Add the check function to the appropriate module in `checks/`
4. Wire it into `_check_single_agent()` (for per-agent checks) or the
   appropriate scope runner
5. Pass `runner` through so the check can access API clients
6. Test with `python scripts/flightcheck/cli.py --scope local` from repo root
7. Verify the check produces useful output in both pass AND fail states

## Running FlightCheck

From the **repository root** (not from `scripts/flightcheck/`):

```bash
python scripts/flightcheck/cli.py --scope full
python scripts/flightcheck/cli.py --scope local
```

Available scopes: `full`, `prerequisites`, `environment`, `authentication`,
`external`, `workday`, `local`, `publishing`.
