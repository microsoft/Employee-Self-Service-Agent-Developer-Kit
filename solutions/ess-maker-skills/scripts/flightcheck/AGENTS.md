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
| Power Platform API (Licensing/Billing) | `powerplatform_client.py` | `https://api.powerplatform.com/.default` | Billing policies, PayG environment linkage (PRE-005) |
| Azure Resource Manager | `azure_arm_client.py` | `https://management.azure.com/.default` | Azure subscription health/`state` for the PayG-linked subscription, and Consumption budgets (spending guardrails) for PRE-005 |
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

## Power Platform identity gotchas

These bit us in PR #87's post-mortem. Read before adding any check
that handles Power Platform identifiers, hosts, or audience tokens.

**Dataverse Organization ID ≠ BAP environment ID.** Most tenants
have different GUIDs for the two. Never derive the BAP env id from
Dataverse `WhoAmI()` / `OrganizationId`. Always list BAP environments
and match on `linkedEnvironmentMetadata.instanceUrl` against the
Dataverse env URL. See `pva_client._discover_gateway()` and
`pp_admin_client.find_environment_id_by_dataverse_url()` for the
pattern. `runner.env_id` is **always** the BAP id and never the
Dataverse OrgId — do not pass it where a Dataverse identifier is
expected, and do not derive one from the other.

**BAP returns 404 (not 403) when handed an unknown env id.** If a
BAP admin call returns 404 for an env you know exists, your env id
is wrong, not the env. Permission failures surface as 401/403.

**Host ↔ audience pairing for Power Platform APIs.** Each host
requires its own audience token; mixing produces 401 even when the
account has the right roles.

| Host | Audience scope | Used for |
|---|---|---|
| `api.bap.microsoft.com` | `service.powerapps.com//.default` | BAP environments, DLP, capacity |
| `api.powerapps.com` | `service.powerapps.com//.default` | PowerApps Admin (connections, etc.) |
| `api.flow.microsoft.com` | `service.flow.microsoft.com//.default` | Power Automate Admin (flow listing) — **separate audience** |
| `graph.microsoft.com` | `graph.microsoft.com/.default` | Microsoft Graph |
| `<dataverse-url>` (`https://orgX.crm.dynamics.com`) | `{env_url}/user_impersonation` | Dataverse Web API |
| `<island-gateway-url>` (region-specific) | `96ff4394-9197-43aa-b393-6a41652e21f8/.default` | Copilot Studio runtime |

A 401 against `api.flow.microsoft.com` with a `service.powerapps.com`
token is the classic symptom. When adding a client, document the
host+audience+example-endpoint triple in `tests/fixtures/cassettes/INDEX.md`.

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

### Sanity-checking a capture before pinning it

The cassette infrastructure trusts what the recorder captures. If the
captured response itself is wrong (wrong URL, wrong audience, wrong
auth context), pinning it as `validated` ground truth codifies the
bug with full ceremony. PR #87's post-mortem found exactly this: a
404 from the wrong host (`api.powerapps.com` instead of
`api.flow.microsoft.com`) had been pinned as "expected behavior for
Dataverse-only environments" — a plausible-sounding rationale for an
incorrect capture.

Before adding a cassette row, especially for an unexpected status
(4xx/5xx) or an unexpectedly empty body:

1. **Cite the vendor doc URL** that documents the operation. The
   status you captured must match a status the doc page describes —
   or your explanation in `INDEX.md` must reference the specific text
   that justifies the discrepancy. "Plausible-sounding folklore" is
   not justification.
2. **Re-capture against a second tenant** known to have the resource.
   If both tenants produce the same anomalous status, your explanation
   is more likely correct. If they diverge, your capture is
   environmental and the cassette is not ground truth.
3. **A 4xx from a happy-path call is a red flag, not a feature.**
   Pinning a 4xx as "expected for this configuration" requires citing
   both (a) the vendor doc for that status and (b) at least two
   tenant captures.
4. **A regression test that pins a 404 needs justification.** Do not
   write a test whose only job is to assert that the production code
   crashes on an empty/error response, unless you have first verified
   you are calling the right endpoint with the right auth. If the
   endpoint is wrong, fix the endpoint; don't pin the wrong-URL 404.

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

**`validatable` validates shape, not values.** The CSDL tells you
the field type, not the value vocabulary. For any field whose
meaningful values come from a documented enum, a vendor-published
list, or a runtime convention (e.g., licence SKU part numbers, role
template IDs, principal-type strings), you must additionally:

1. Cite the **vendor-published reference list** for the values. For
   licence SKUs:
   `https://learn.microsoft.com/entra/identity/users/licensing-service-plan-reference`
   (table of `String ID` ↔ `GUID` ↔ included service plans).
2. Match values **case-insensitively unless the reference explicitly
   says case is significant.** Graph regularly returns the same SKU
   in different casings across tenants (`Microsoft_365_Copilot` vs
   `MICROSOFT_365_COPILOT`).
3. For SKUs and other bundles: list the bundles that *include* the
   service you care about, not just the singleton SKU. The
   licensing-service-plan-reference table tells you which service-plan
   GUIDs are contained in each SKU. PRE-003 (Teams entitlement)
   previously only matched `"TEAMS"` substrings and missed Teams
   delivered via O365_BUSINESS_PREMIUM, ENTERPRISEPACK, SPE_E3, etc.
4. Add a unit test that loads the published reference table (or a
   representative subset captured into the test) and asserts the
   check matches every SKU that contains the target service plan.

This rule applies whenever the check's pass/fail branches on a
specific string value, not just on whether a field exists.

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
  `description`, `result`, `roles`, optional `remediation` and `doc_link`.
- Maps cleanly to good-state / bad-state / partial-state branches.

Runner attributes available to checks (set up by `cli.py`):

| Attribute | Type | Description |
|-----------|------|-------------|
| `runner.env_url` | `str` | Dataverse environment URL |
| `runner.dv_token` | `str` | Dataverse bearer token |
| `runner.env_id` | `str` | Power Platform (BAP) environment ID. **NOT** the Dataverse OrgId — these are different GUIDs on most tenants. Derived via `pp_admin_client.find_environment_id_by_dataverse_url()` (instance-URL match against the BAP env list). See "Power Platform identity gotchas." |
| `runner.graph` | `GraphClient \| None` | Microsoft Graph client |
| `runner.pp_admin` | `PowerPlatformAdminClient \| None` | BAP admin client |
| `runner.powerplatform` | `PowerPlatformClient \| None` | Power Platform API client (billing policies; PRE-005) |
| `runner.azure_arm` | `AzureArmClient \| None` | Azure Resource Manager client (subscription health; PRE-005) |
| `runner.pva` | `PVAClient \| None` | Island Gateway client |
| `runner.config` | `dict` | Parsed `.local/config.json` |

Minimal example:

```python
from ..runner import CheckResult, Status, Priority, Role

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
        roles=[Role.ESS_MAKER.value],  # who owns the fix if this can fail
    ))
    return results
```

### Assigning `roles` (the next-step owner)

`roles` is a `list[str]` of `Role` enum values naming **every admin
persona who must take the next action** to FIX a failing/errored check
OR PERFORM the manual validation of a MANUAL / NOT_CONFIGURED result.
It surfaces as a "Role" column in the HTML report and `results.json`,
and on the terminal action/manual rows.

**Set `roles` on any check that can produce a Failed, Error, Warning,
Manual, or NotConfigured result.** A row that only ever Passes or is
Skipped has no next step, so it needs no role — the report blanks the
Role cell for Passed/Skipped rows regardless of what the field holds.
When a single constructor's status is conditional (e.g.
`Status.PASSED.value if connected else Status.FAILED.value`), still set
`roles`: the report shows it only when the row actually lands on an
actionable status.

For uniformity (and because a regression test enforces it — see
`tests/flightcheck/test_check_roles.py`), set `roles` on **every**
`CheckResult` constructor, including pure-SKIPPED branches, even though
the renderer blanks the Role cell on Passed/Skipped rows. Use the role
that would own the fix if the check were actionable.

The seven roles (`Role.<NAME>.value`):

| Role | Owns checks whose fix happens in… |
|------|-----------------------------------|
| `Role.ENTRA_ADMIN` | Entra ID: app registrations, enterprise apps, SAML, conditional access, directory-role assignment |
| `Role.M365_ADMIN` | Microsoft 365 admin center: license/SKU assignment, Office Cloud Policies, Graph connectors, Integrated-apps approval |
| `Role.POWER_PLATFORM_ADMIN` | Power Platform: environments, DLP, connections, solution import, cloud-flow state, Dataverse env vars |
| `Role.WORKDAY_ADMIN` | The Workday tenant: ISU accounts, security groups, domain permissions, RaaS, auth policies |
| `Role.SERVICENOW_ADMIN` | The ServiceNow instance: service accounts, roles, ACLs |
| `Role.SAP_ADMIN` | The SAP SuccessFactors tenant |
| `Role.ESS_MAKER` | Local agent files the maker authors: topics, variables, template configs, evaluations, publishing/QA gates |

A check may need more than one role (e.g. a Workday SAML signing cert
lives on the Entra app but is compared in the Workday tenant ->
`[Role.ENTRA_ADMIN.value, Role.WORKDAY_ADMIN.value]`). Pick the role(s)
from WHO performs the fix described in `remediation`, not from the
category alone.

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
   `authentication`, `external`, `workday`, `servicenow`, `local`, `publishing`.
3. Verify the check produces useful output in both pass AND fail states.

### 5a. End-to-end smoke against a real tenant — required for new endpoints

Mocks validate logic; live runs validate that the endpoint exists,
the host+audience pair is right, and the gate chain that feeds your
check actually populates. Unit tests passing while the production
endpoint returns 404 is exactly how PR #87's three latent bugs
survived. **If your PR adds a check that calls an API host or
audience not already covered by an existing `runner.<client>`
method, the PR description must include:**

* The exact `python scripts/flightcheck/cli.py --scope <scope>`
  command you ran.
* The output line showing the new checkpoint ID firing with a
  terminal status (PASSED, WARNING, FAILED, or NOT_CONFIGURED) —
  NOT SKIPPED. A SKIPPED result means the check did not actually
  execute and the live run did not exercise the new endpoint.
* A note confirming the run was against a real tenant, not a mock.

If your check is gated by an upstream check (e.g. a Workday check
that only runs when `_workday_flows` is non-empty), use a tenant
where the upstream gate opens. Otherwise the smoke proves nothing.

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
   - Uses shared MSAL token cache at `.local/.token_cache.bin`
   - Initialized in `cli.py`, attached to `runner`
   - Gracefully skips if auth fails (print warning, set to None)

6. **No fabricated URLs.** Every URL in code must point to a page you have
   confirmed exists. If no doc page exists, leave the link empty with a
   `# TODO: create doc page at ...` comment.

7. **Bucket multi-resource checks by status.** When a check iterates
   over N resources of the same kind (service principals, cloud flows,
   environment variables, environments, etc.), group results by status
   and emit at most one `CheckResult` per distinct status — never one
   per resource. Per-resource rows make the readiness summary
   unreadable as soon as a tenant has more than one of the resource
   (e.g. a customer with both a Workday SSO app and a Workday OAuth
   app produces two rows instead of one Warning + one Passed). The
   `result` field of each bucket lists every affected resource (one
   line per resource when there are multiple); the `remediation` is
   the de-duplicated set of fix actions. See AUTH-005 in
   `checks/authentication.py` for the canonical implementation,
   including the `_format_sp_state()` / `_format_sp_remediations()`
   helpers that handle the single-resource vs. multi-resource
   rendering.

8. **`result` vs. `remediation` contract.** Every `CheckResult` must
   obey this split, regardless of status:
   - `result` = what the kit observed (current state). No fix steps,
     no "should be X" prose, no impact speculation. Read it and you
     know what's true in the tenant right now.
   - `remediation` = what the operator should do. No restating of the
     current state. Read it and you know which buttons to click.
   - The WHY of acting (impact, hardening justification, urgency
     framing) belongs once at the start of `remediation`, NOT in
     `result`. The status + priority already convey severity; the
     `remediation` is where you explain why the operator should care.
   - Fix actions in `remediation` should NOT embed per-resource names
     when emitted from a status-bucketed check (principle 7). Factor
     the name out — say "the app(s) above" or "the resources listed"
     — so identical fixes across multiple resources collapse to a
     single de-duplicated line instead of repeating verbatim per
     resource. Resource names live in `result`.
   - `PASSED` results have no `remediation`. There is nothing to fix.
   - This is the general form of the rule MANUAL spelled out in
     principle 2 — apply it everywhere.

9. **Calibrate WARNING text by kind.** Before shipping a WARNING,
   classify it explicitly. Each kind has a different `remediation`
   shape so the operator triaging the report doesn't waste cycles
   chasing the wrong urgency:
   - **Functional risk** ("X will fail / is partially broken /
     misconfigured in a way that causes runtime errors"): describe
     the breakage tersely in `result`, give the fix and the runtime
     impact in `remediation`.
   - **Hardening recommendation** (the system works, but the
     configuration is below the supported best practice for
     security, scale, or audit): the `remediation` MUST open with
     `"Hardening recommendation (not a functional blocker)"` and
     MUST give at least one concrete reason the recommended state
     is better (smaller impersonation surface, group-based access
     control, audit trail, etc.) BEFORE the click-path. Otherwise
     operators read it as a broken-thing alert and waste triage time.
   - **Data-quality concern** (low sample size, short description,
     missing optional metadata): say so in `result`; the `remediation`
     names the missing data.
   If you can't categorize the WARNING into one of these three, it's
   probably either misframed or it should be a different status
   (`NOT_CONFIGURED` for items that need manual portal verification,
   `SKIPPED` for items the check couldn't actually evaluate).

10. **Verify framing claims.** Any urgency phrase in check text
    ("X will fail", "Y is required for runtime", "Z breaks for all
    users") must trace to either (a) a tested code path the check
    actually exercises, or (b) a cited doc/issue link in the source
    comments. Vague hedges like "a deploy-time check cannot guarantee
    runtime behavior" are forbidden — if you don't know whether the
    misconfiguration actually breaks anything, find out before
    shipping the check. Untested urgency claims erode trust the
    moment a reviewer asks "wait, does this actually break ESS?"
    and the answer is "no, but it could in theory."

11. **Gate flavor-specific checks on an install-fingerprint verdict.**
    Some products ship under multiple install flavors that share the
    same connector / connector keyword but have different runtime
    semantics. The canonical example is Workday: the simplified
    install (1 connection reference, OBO with the signed-in user's
    identity) and the full / legacy install (3 refs: OBO + 2 ISU
    service-account refs that drive RaaS reports) both bind to the
    same `shared_workdaysoap` connector, but the ISU/RaaS code path
    only exists on the full install. Running an ISU-specific check on
    a simplified-install tenant emits FAILs whose remediations point
    at the wrong setup path and waste operator triage time.

    Convention for handling this:

    a. **One fingerprint check per product** runs first within its
       category and stores its verdict on a
       `runner._<product>_package_flavor` attribute — e.g.
       `runner._workday_package_flavor`. Use canonical string values
       (e.g. `"simplified"`, `"full"`, `"partial"`, `"unknown"`,
       `"none"`, `"skipped"`) so consumers can use `==` checks rather
       than substring matches. WD-PKG-001 in `checks/workday.py` is
       the canonical implementation.

    b. **Consumer checks read the verdict** via
       `getattr(runner, "_<product>_package_flavor", None)` and SKIP
       only on a positive match for an INCOMPATIBLE flavor. Any other
       value — `None`, `"partial"`, `"unknown"`, `"none"`, `"skipped"`,
       or anything ambiguous — runs the existing logic. Operators
       debugging a broken install need maximum signal, not silence.
       This is the single safety rule that distinguishes "gating that
       helps" from "gating that hides real bugs."

    c. **The `None`-defaults-to-run rule** exists for backwards-compat
       with direct unit-test callers that build minimal runners without
       the attribute. In production the fingerprint check must execute
       before any consumer reads its verdict — enforce this by ordering
       at the call site (e.g. WD-PKG-001 runs at the top of
       `run_workday_checks`). Pin both the "simplified → skip" and
       "attribute absent → run" branches in tests so a future runner
       refactor that forgets to populate the attribute is loud, not
       silently masked by every consumer skipping.

    d. **SKIP message split** follows principle 8: `result` reports
       the fingerprint observation (e.g. `"WD-PKG-001 detected
       simplified Workday install shape (1 connection ref,
       OBO/OAuthUser). This check is ISU/RaaS-specific and does not
       apply on the simplified install."`); `remediation` carries the
       actionable contingency for an operator who intended the OTHER
       flavor (e.g. `"If you intended to install the full / legacy
       SOAP+custom integration, the same 1-ref shape ALSO matches a
       broken full install where the 2 ISU connection references
       (Generic User, Context Generic User) failed to deploy. See
       WD-PKG-001's diagnostic before treating this SKIP as benign."`).
       When the fingerprint observation is consistent with multiple
       install intents, the remediation MUST surface that ambiguity —
       a benign-looking SKIP that hides a broken install is the
       failure mode this principle exists to prevent.

    e. **SKIP `doc_link`** points to the documentation for the
       DETECTED install flavor (e.g. on simplified, link to the
       simplified-setup page), so operators can confirm the gating
       decision in context.

    f. **Place the gate before any API reads.** The whole point of
       gating is to avoid the misleading downstream side effects; if
       the gate runs after `runner.env_url` / `runner.graph` reads,
       simplified-install tenants might still hit Dataverse/Graph
       unnecessarily or produce token-related SKIPs that mask the
       flavor-not-applicable SKIP.

    See `_check_env_vars`, `_check_isu_username_format`, and
    `_check_workflows` in `checks/workday.py` for the canonical
    consumer pattern, and the `TestSimplifiedInstallGate` classes in
    `tests/flightcheck/checks/test_workday_*.py` for the test
    contract this principle requires.

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
environment ID. See "Power Platform identity gotchas" near the top of
this file for the cross-cutting rule that applies to every client that
needs a BAP env id, including the implementation pattern.

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
