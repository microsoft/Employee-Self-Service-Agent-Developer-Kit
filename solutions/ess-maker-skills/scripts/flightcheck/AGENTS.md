# Instructions for AI agents adding or modifying FlightCheck checks

If you are an AI coding agent (Copilot CLI, Claude, or any other) working
in this directory tree, **read this file first and follow it strictly.**

This document covers the rules for the **production checks themselves**
(the code customers run via `/flightcheck`). Test-authoring rules are
in `tests/AGENTS.md`. They complement each other; you need both.

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
+ response shape** — NOT the exact query string. Server-side queryparameters that only narrow,
project, sort, or paginate over the same resource collection do not
require a new cassette. The same item shape comes back regardless of
how you filter for it.

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
  `runner.workday`) — don't instantiate HTTP clients yourself.
- Returns `list[CheckResult]`.
- Each result has `checkpoint_id`, `category`, `priority`, `status`,
  `description`, `result`, optional `remediation` and `doc_link`.
- Maps cleanly to good-state / bad-state / partial-state branches.

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
