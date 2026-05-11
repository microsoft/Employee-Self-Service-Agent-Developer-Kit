# FlightCheck ??? Developer Guide

This document provides guidance for agents and developers adding new checks
to the FlightCheck tool.

## Architecture Overview

FlightCheck validates customer deployments by querying multiple APIs. Each API
requires its own authentication and has different data available:

| API Layer | Client | Auth Resource / Scope | What's Available |
|-----------|--------|----------------------|------------------|
| Dataverse | `../auth.py` | `{env_url}/user_impersonation` | Bot components (topics, variables, knowledge source *config*), template configs, solution metadata, statecode (enabled/disabled) |
| Microsoft Graph | `graph_client.py` | `https://graph.microsoft.com/.default` | Licenses, user roles, Entra app registrations, CA policies |
| Power Platform Admin (BAP) | `pp_admin_client.py` | `https://service.powerapps.com//.default` | Environments, cloud flows, connections, DLP policies |
| Island Gateway (Copilot Studio) | `pva_client.py` | `96ff4394-9197-43aa-b393-6a41652e21f8/.default` | Live bot component status, model config, knowledge source *runtime state* |

> **Note:** `../auth.py` lives at `scripts/auth.py`, outside the flightcheck
> folder. It's importable as `from auth import authenticate, query_all` because
> `cli.py` adds `scripts/` to `sys.path` at startup.

**Critical distinction ??? three data layers:**

- **Local YAML** (`checks/local_files.py`) = what the developer authored. This
  is the kit's source of truth for agent configuration: topic descriptions,
  agent instructions, variable definitions. Check local files first.
- **Dataverse** = server-side state not available in local files: statecode
  (enabled/disabled), template configs, solution metadata, fields stamped
  after publish.
- **Island Gateway** = runtime state: whether a knowledge source is actively
  indexed, crawl progress, model assignments.

If the data exists in local YAML, check it there ??? don't query Dataverse for
something `local_files.py` already validates.

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
- `component.$kind`: common kinds include `DialogComponent`, `KnowledgeSourceComponent`,
  `GptComponent`, `GlobalVariableComponent`, `CustomEntityComponent` (the API may
  return other kinds not listed here)
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
  - `9` = Topic/Dialog
  - `12` = Global variable
  - `16` = Knowledge source
- **The `data` column is YAML** (the `.mcs.yml` file content), NOT JSON. Do
  not try to `json.loads()` it. Parse with a YAML library if needed.
- **`statecode`/`statuscode`** are standard Dataverse record status (Active=0/1),
  NOT the runtime crawl/index status.

## Design Principles

1. **No misleading results.** If a check cannot actually validate what it claims
   to validate (e.g., missing API access), never return `PASSED`. A check that
   always passes is worse than no check at all.

2. **Use the right status.** The runner has six statuses ??? pick the one that
   matches your situation:
   - `PASSED` ??? we ran the check and the result is good
   - `FAILED` ??? we ran the check and the result is bad
   - `WARNING` ??? we ran the check but something is concerning (e.g., short
     description, low count), or an API call errored and we want to surface it
   - `SKIPPED` ??? we couldn't run the check at all (API unavailable, missing
     creds, no relevant data on disk)
   - `NOT_CONFIGURED` ??? the feature isn't turned on, or the item requires
     manual verification in the portal
   - `ERROR` ??? the check itself crashed (the runner catches exceptions and
     sets this automatically)

3. **Fail loudly on API errors.** If an API call fails, let the exception
   propagate to the caller so it can be reported as a WARNING with the actual
   error message. Do not silently return empty results.

4. **One check, one concern.** Each check should validate exactly one thing.
   Don't bundle multiple validations under a single checkpoint ID.

5. **Follow existing client patterns.** New API integrations should follow the
   same structure as `graph_client.py` / `pp_admin_client.py` / `pva_client.py`:
   - Class with `authenticate()` method
   - Uses shared MSAL token cache at `.local/.token_cache.bin`
   - Initialized in `cli.py`, attached to `runner`
   - Gracefully skips if auth fails (print warning, set to None)

6. **No fabricated URLs.** Every URL in code must point to a page you have
   confirmed exists. If no doc page exists, leave the link empty with a
   `# TODO: create doc page at ...` comment.

## Adding a New Check

### Runner attributes

Check functions receive a `FlightCheckRunner` instance. API clients are
attached as ad-hoc attributes in `cli.py`. Available attributes:

| Attribute | Type | Description |
|-----------|------|-------------|
| `runner.env_url` | `str` | Dataverse environment URL |
| `runner.dv_token` | `str` | Dataverse bearer token |
| `runner.env_id` | `str` | Power Platform (BAP) environment ID |
| `runner.graph` | `GraphClient \| None` | Microsoft Graph client |
| `runner.pp_admin` | `PowerPlatformAdminClient \| None` | BAP admin client |
| `runner.pva` | `PVAClient \| None` | Island Gateway client |
| `runner.config` | `dict` | Parsed `.local/config.json` |

Any of the client attributes may be `None` if authentication failed.
Always check before using (e.g., `if not runner.graph: return skipped`).

### Minimal example

```python
from ..runner import CheckResult, Status, Priority

def run_my_checks(runner) -> list[CheckResult]:
    results = []
    # ... do the check, possibly using runner.graph / runner.pva / etc. ...
    results.append(CheckResult(
        checkpoint_id="CONFIG-099",
        category="Local Files",
        priority=Priority.HIGH.value,
        status=Status.PASSED.value,
        description="Thing is set up correctly",
        result="Found N things",
        remediation="",  # only needed for non-pass statuses
    ))
    return results
```

### Checklist

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
