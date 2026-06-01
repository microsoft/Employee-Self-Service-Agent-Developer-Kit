# Instructions for AI agents adding or modifying FlightCheck checks

If you are an AI coding agent (Copilot CLI, Claude, or any other) working
in this directory tree, **read this file first and follow it strictly.**

This document covers the rules for the **production checks themselves**
(the code customers run via `/flightcheck`). Test-authoring rules are
in `tests/AGENTS.md`. They complement each other; you need both.

---

## Architecture overview

FlightCheck validates customer deployments by querying multiple APIs.
Each API requires its own authentication and has different data
available:

| API Layer | Client | Auth Resource / Scope | What's Available |
|-----------|--------|----------------------|------------------|
| Dataverse | `../auth.py` | `{env_url}/user_impersonation` | Bot components (topics, variables, knowledge source *config*), template configs, solution metadata, statecode (enabled/disabled) |
| Microsoft Graph | `graph_client.py` | `https://graph.microsoft.com/.default` | Licenses, user roles, Entra app registrations, CA policies |
| Power Platform Admin (BAP) | `pp_admin_client.py` | `https://service.powerapps.com//.default` | Environments, cloud flows, connections, DLP policies |
| Island Gateway (Copilot Studio) | `pva_client.py` | `96ff4394-9197-43aa-b393-6a41652e21f8/.default` | Live bot component status, model config, knowledge source *runtime state* |

> **Note:** `../auth.py` lives at `scripts/auth.py`, outside the flightcheck
> folder. It's importable as `from auth import authenticate, query_all` because
> `cli.py` adds `scripts/` to `sys.path` at startup.

**Critical distinction — three data layers:**

- **Local YAML** (`checks/local_files.py`) = what the developer authored. This
  is the kit's source of truth for agent configuration: topic descriptions,
  agent instructions, variable definitions. Check local files first.
- **Dataverse** = server-side state not available in local files: statecode
  (enabled/disabled), template configs, solution metadata, fields stamped
  after publish.
- **Island Gateway** = runtime state: whether a knowledge source is actively
  indexed, crawl progress, model assignments.

If the data exists in local YAML, check it there — don't query Dataverse for
something `local_files.py` already validates.

This table is not exhaustive. New checks may require APIs not listed here. If
the data you need isn't available from any existing client, research the correct
API, document it, add a row to this table, and create a new client following
existing patterns.

---

## The cardinal rule

> **Every FlightCheck check that calls an external API must verify the
> API contract it depends on before shipping, using one of three
> permitted tiers (`validated`, `validatable`, `documented`). The
> `placeholder` tier is NEVER permitted for FlightCheck.**

A check that calls an endpoint nobody has confirmed is worse than no
check at all — it produces a confidently wrong result and erodes the
trust customers place in FlightCheck. Different APIs warrant different
verification methods; what's not negotiable is that some real
verification happens for every check.

### The four mock tiers

| Tier | Verification method | When it applies | Cassette? |
|---|---|---|---|
| `validated` | Captured cassette in `tests/fixtures/cassettes/` from a real tenant. The cassette IS the ground truth for response shape. | APIs without public schemas, or where per-tenant variance matters (custom fields, tenant-specific config, undocumented internal APIs). | **Required** |
| `validatable` | Public machine-readable schema (CSDL / OpenAPI / well-known config) fetched by the check author + cited MS Learn doc URL with example response. The author MUST verify, while writing the check, that every property the check consumes appears in the schema with the expected type. | Microsoft 1st-party APIs that publish schemas at stable, no-auth URLs. | Not required (cassettes still welcome as supplementary evidence) |
| `documented` | Vendor prose docs + a verbatim copy of the documented example response pasted into the mock builder docstring, with the doc URL (anchored) cited. Weaker tier — only use when neither validatable nor validated is feasible. | APIs with good prose docs but no public machine-readable schema and no interactive test path. | Not required |
| `placeholder` | Schema-grounded best guess. **NOT permitted in any FlightCheck check.** | Test infrastructure scratch only. | N/A |

The per-API tier assignment is fixed in `tests/fixtures/cassettes/INDEX.md`
under "API tier registry." Use the tier the registry mandates for each
API — don't silently pick a weaker one. If you need a different tier
for an API, change the registry first (with rationale in your PR).

### What counts as the "same endpoint" (validated tier)

For the `validated` tier, the unit of confirmation is **method + path
+ response shape** — NOT the exact query string. Server-side query
parameters that only narrow, project, sort, or paginate over the same
resource collection do not require a new cassette. The same item shape
comes back regardless of how you filter for it.

Concretely:

- `GET /users?$top=10` and
  `GET /users?$filter=mail eq '...'` and
  `GET /users?$select=id,displayName` and
  `GET /users` (no params) are all the **same endpoint** for
  cassette purposes. One captured cassette covers all four.
- Same for ServiceNow `sysparm_query` / `sysparm_fields` / `sysparm_limit`,
  Dataverse `$filter` / `$select`, Workday WQL `WHERE` / `LIMIT` clauses,
  and Power Platform Admin API `$filter`. These are server-side narrowing
  on a captured collection — no new cassette needed.

What DOES require a new cassette:

- A different **path** — `/users/{id}` and
  `/users/{id}/manager` are distinct from
  `/users` and each need their own capture.
- A different **method** — `POST /users` vs `GET`.
- Query parameters that **change the response shape**, not just narrow it:
  - `$expand=` (adds nested objects that wouldn't be there otherwise)
  - `$count=true` (adds an `@odata.count` field at the top level)
  - `$apply=` (aggregations — completely different shape)
  - Any param that switches between page-of-items and single-item shapes.
- A different **response branch** the check must handle (e.g. a 404 or
  401 you intend to assert against — capture the negative path too).

If you're not sure whether a query param changes the shape, capture it.
The cost of an unnecessary cassette is a few KB; the cost of a check
built against a guessed shape is a false-confidence FlightCheck pass.

---

## Workflow when adding a new check that calls an external API

Do these steps in order. Don't skip any.

### 1. Look up the API tier

Open `tests/fixtures/cassettes/INDEX.md` → "API tier registry." Find
the API surface you're calling; the tier (`validated` / `validatable`
/ `documented`) tells you which verification path is required.

If the API is not in the registry, STOP. Tell the user:

> I need to write a FlightCheck check that calls `<API surface>` for
> `<checkpoint id>`. This API isn't in the API tier registry in
> `tests/fixtures/cassettes/INDEX.md`. Please decide which tier it
> belongs in (validated / validatable / documented) and add the row;
> then I'll resume.

### 2. Do the per-tier verification

**If the tier is `validated`:** read the "Confirmed endpoints" table
in `INDEX.md`. Match by method + path (query-string variants of the
same path are covered — see "What counts as the same endpoint"
above). If your method + path is missing, STOP and tell the user:

> I need to write a FlightCheck check for `<checkpoint id>` that calls
> `<HTTP method> <path>` on `<service name>`. This API is in the
> `validated` tier but no cassette covers this path + method. Please
> capture one per `tests/AGENTS.md` "How to add a new mock builder
> (validated path)." Then I'll resume.

If the row exists, the cassette is your ground truth. Proceed to step 3.

**If the tier is `validatable`:** fetch the API's public schema and
verify the specific properties your check will consume against it.
Schema sources currently approved:

| API | Schema URL (no auth) | Operation docs |
|---|---|---|
| Microsoft Graph v1.0 | `https://graph.microsoft.com/v1.0/$metadata` (CSDL XML, ~2.7 MB) | `https://learn.microsoft.com/graph/api/{operation}` |
| Microsoft Entra OAuth2 | `https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration` (OpenID discovery) | `https://learn.microsoft.com/entra/identity-platform/v2-oauth2-*` |

Walk through the schema for each entity you'll consume. For every
field the check reads, confirm:
- The field exists on the entity.
- The type matches what the check expects (`Edm.Boolean`, `Edm.String`,
  collection type, etc.).
- For enum-typed fields (e.g. `principalType` = `User`/`Group`/...),
  the enum members include every value your check branches on.

Quote the schema fragment + the MS Learn example response in the
mock builder docstring. The author's schema walk-through IS the
validation — you're attesting that the contract you coded against
came from the schema, not memory or guesswork. Proceed to step 3.

**If the tier is `documented`:** fetch the MS Learn (or vendor) doc
page for the operation. Locate the "Response" section; copy the
example JSON verbatim into the mock builder docstring. Cite the doc
URL with anchor (e.g. `https://learn.microsoft.com/.../create#response-1`).
Proceed to step 3.

### 3. Write the check

Place the check in the appropriate `checks/{category}.py` module. The
check function:
- Uses `runner.<client>` (e.g. `runner.pp_admin`, `runner.graph`,
  `runner.workday`, `runner.pva`) — don't instantiate HTTP clients
  yourself. Any of these may be `None` if authentication failed; always
  guard before use (e.g. `if not runner.graph: return skipped`).
- Returns `list[CheckResult]`.
- Each result has `checkpoint_id`, `category`, `priority`, `status`,
  `description`, `result`, optional `remediation` and `doc_link`.
- Maps cleanly to good-state / bad-state / partial-state branches.

Runner attributes available to checks (set up by `cli.py`):

| Attribute | Type | Description |
|-----------|------|-------------|
| `runner.env_url` | `str` | Dataverse environment URL |
| `runner.dv_token` | `str` | Dataverse bearer token |
| `runner.env_id` | `str` | Power Platform (BAP) environment ID |
| `runner.graph` | `GraphClient \| None` | Microsoft Graph client |
| `runner.pp_admin` | `PowerPlatformAdminClient \| None` | BAP admin client |
| `runner.pva` | `PVAClient \| None` | Island Gateway client |
| `runner.config` | `dict` | Parsed `my/config.json` |

Minimal example:

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

### 4. Write the test BEFORE you ship

In `tests/flightcheck/checks/test_{category}.py`:
- One test for the GOOD state (mock returns valid data → check returns
  PASSED).
- One test for the BAD state (mock returns missing/invalid data →
  check returns FAILED with a remediation that points at a real fix
  path).
- Edge tests for any branches in the check logic.

Use the mock builder for that API. Its `MOCK_STATUS` (in the module
header) MUST be `validated`, `validatable`, or `documented` — never
`placeholder`. The conftest enforcement helper rejects placeholder
mocks at collection time.

If you'd need a `placeholder` mock for any of the above, the API
tier you picked is wrong — go back to step 1, pick the correct tier,
and do the per-tier verification.

### 5. Wire and run

1. Wire the new check into `_check_single_agent()` (for per-agent
   checks) or the appropriate scope runner.
2. Run from the **repository root** (not from `scripts/flightcheck/`):
   ```bash
   python scripts/flightcheck/cli.py --scope <scope>
   ```
   Available scopes: `full`, `prerequisites`, `environment`,
   `authentication`, `external`, `workday`, `local`, `publishing`.
3. Verify the check produces useful output in both pass AND fail states.

---

## Design principles

1. **No misleading results.** If a check cannot actually validate what it
   claims to validate (e.g., missing API access), never return `PASSED`. A
   check that always passes is worse than no check at all.

2. **Use the right status.** The runner has seven statuses — pick the one that
   matches your situation:
   - `PASSED` — we ran the check and the result is good
   - `FAILED` — we ran the check and the result is bad
   - `WARNING` — we ran the check but something is concerning (e.g., short
     description, low count), or an API call errored and we want to surface it
   - `SKIPPED` — we couldn't run the check at all (API unavailable, missing
     creds, no relevant data on disk)
   - `NOT_CONFIGURED` — the feature isn't turned on, or the item requires
     manual verification in the portal
   - `MANUAL` — the check gathered everything programmatically observable but
     the final comparison must be performed by the operator against an
     external system the kit can't (or shouldn't) read directly. Use this
     when you can fetch one side of a comparison (e.g. the Entra-side SAML
     claim mapping via Microsoft Graph) but the other side lives in a vendor
     system the kit has no admin API for (e.g. Workday Tenant Setup -
     Security). The `result` field MUST carry the value the kit observed
     verbatim; the `remediation` field MUST tell the operator exactly which
     external screen to open and which value to compare against. MANUAL is
     the canonical pattern for Workday / ServiceNow / SAP tenant-config
     validation that has no programmatic admin surface (see issue #84 for
     the original SAML-NameID example). MANUAL does NOT fail readiness.
   - `ERROR` — the check itself crashed (the runner catches exceptions and
     sets this automatically)

3. **Fail loudly on API errors.** If an API call fails, let the exception
   propagate to the caller so it can be reported as a WARNING with the actual
   error message. Do not silently return empty results.

4. **One check, one concern.** Each check should validate exactly one thing.
   Don't bundle multiple validations under a single checkpoint ID.

5. **Follow existing client patterns.** New API integrations should follow the
   same structure as `graph_client.py` / `pp_admin_client.py` / `pva_client.py`:
   - Class with `authenticate()` method
   - Uses shared MSAL token cache at `my/.token_cache.bin`
   - Initialized in `cli.py`, attached to `runner`
   - Gracefully skips if auth fails (print warning, set to None)

6. **No fabricated URLs.** Every URL in code must point to a page you have
   confirmed exists. If no doc page exists, leave the link empty with a
   `# TODO: create doc page at ...` comment.

---

## Things you must NOT do

- **Don't invent endpoint URLs, methods, or response shapes.** Pick
  the right tier (validated / validatable / documented) per step 1,
  do the per-tier verification, and only then code against the result.
- **Don't import `responses`, `respx`, or VCR from a check file.** Those
  are test-only libraries. Check files use real HTTP clients
  (`requests`, `httpx`, or the kit's `*_client.py` wrappers).
- **Don't use a `placeholder` mock in a FlightCheck integration test.**
  The conftest enforcement helper rejects this at collection time. If
  the only mock available is placeholder, the API needs to be promoted
  to validated / validatable / documented first.
- **Don't pick a weaker tier than the API tier registry mandates.**
  If `INDEX.md` says an API is `validated` and you'd rather treat it
  as `documented` to skip the cassette work, change the registry (with
  rationale) — don't bypass it silently.
- **Don't bypass `runner.<client>` and create your own session.** The
  runner clients carry auth, retry, and pagination logic the check
  depends on, plus they're the layer the tests mock.
- **Don't add a check that depends on an API for which a documented
  blocker exists.** Example: WQL bearer-only auth requires Workday
  API Client registration — `tests/fixtures/cassettes/INDEX.md` and
  the WQL recorder explicitly say "do NOT build a runtime check on
  this cassette without resolving the chicken-and-egg first." Read
  those notes before writing a Workday WQL check.

---

## What gets pinned (regression tests for known bugs)

If your check exposes a bug in production code (a 404 that crashes a
client, a regex that over-captures, etc.), pin it with a test that
asserts the **current buggy behaviour** until the bug is fixed. Include
in the test docstring:

1. Clear description of the bug.
2. Recommended fix (file, line, proposed change).
3. `TODO: when fixed, flip this assertion to ...`.

See `tests/flightcheck/test_pp_admin_client.py` for an example
(`test_get_all_returns_error_on_404`).

---

## Common categories and where they go

| Category | Module |
|---|---|
| Microsoft tenant prerequisites (licenses, roles, Entra) | `checks/prerequisites.py`, `checks/authentication.py` |
| Power Platform environment + DLP | `checks/environment.py` |
| External-system detection (Workday/ServiceNow/SAP solutions installed) | `checks/external_systems.py` |
| Workday deep validation (env vars, connections, SOAP workflows) | `checks/workday.py` |
| Local agent file structure (topics, variables, template configs) | `checks/local_files.py` |
| Manual / publishing checklist (NotConfigured by default) | `checks/publishing.py` |

If you need a new category (e.g. `checks/servicenow.py` for ServiceNow
deep validation), wire it into `runner.py` alongside the existing ones.

---

## Island Gateway API reference

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

---

## Dataverse `botcomponents` entity

The `botcomponents` entity set stores agent components. Key facts:

- **No `msdyn_` prefix** — the entity set is just `botcomponents` (not
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

---

## See also

- `tests/AGENTS.md` — the test-authoring companion to this file. Read
  it BEFORE writing the test for your check.
- `tests/fixtures/cassettes/INDEX.md` — the **API tier registry**
  (which API is in which tier) plus the **confirmed cassette
  endpoints** table (cassettes for the `validated` tier). The first
  thing to check when planning a new check.
- `tests/mocks/<system>.py` — mock builders. Each declares
  `MOCK_STATUS = "validated" | "validatable" | "documented" |
  "placeholder"`. Only the first three are usable by FlightCheck
  checks.
