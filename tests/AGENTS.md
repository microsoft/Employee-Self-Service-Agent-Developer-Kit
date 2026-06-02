# Instructions for AI agents writing FlightCheck tests under `tests/`

If you are an AI coding agent (Copilot CLI, Claude, or any other) working
on the test suite under this directory, **read this file first and follow
it strictly.**

**This file is the test-authoring companion to
`solutions/ess-maker-skills/scripts/flightcheck/AGENTS.md`.** That
sibling file covers the rules for the production checks themselves
(the code customers run via `/flightcheck`). The cardinal rule applies
in both places:

> Every FlightCheck check that calls an external API must be backed
> by a captured cassette of real responses AND a test that exercises
> the check against the cassette.

The check-author file (`flightcheck/AGENTS.md`) tells you what to do
when *adding a new check*. This file tells you what to do when *adding
or modifying tests* — primarily, how to use the existing cassettes and
mock builders, how to enforce the rule that no integration test runs
against an unconfirmed API, and how to handle the "the cassette I need
doesn't exist yet" situation.

If you're here because you're about to add a new check, **stop, read
`solutions/ess-maker-skills/scripts/flightcheck/AGENTS.md` first**, then
come back here to write the corresponding test. The two documents
deliberately cross-reference each other.

---

## Two layers of FlightCheck checks (and corresponding API categories)

When you add a new FlightCheck check, identify which of these you're
building. The wrong API category will give you a passing test that
validates nothing useful.

### Layer 1 — Runtime data path

The check exercises the same APIs the agent's *topics* call to fetch
data at runtime. Example: WD-WF-001 calls `Get_Workers` (Workday
Human_Resources SOAP) to verify the kit can retrieve worker data.

Mock + cassette home: `tests/mocks/{system}.py` runtime builders +
`tests/fixtures/cassettes/flightcheck_{system}.yaml`.

### Layer 2 — Configuration validation path

The check exercises *admin* APIs to verify the customer set up the
integration correctly per the [Microsoft Learn integration docs](https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/).
Example: a future WD-CFG-001 might call `Get_API_Clients` (Workday
Identity_Management SOAP) to verify the API client registration step
in the docs was performed.

Mock + cassette home: `tests/mocks/{system}.py` config builders +
`tests/fixtures/cassettes/{system}_config.yaml`.

These two paths use *different* APIs entirely. For Workday the
runtime path is SOAP with WS-Security UsernameToken (basic auth via
ISU credentials); the configuration validation path is REST with OAuth
2.0 bearer auth against admin endpoints (`/ccx/api/{module}/v{n}/{tenant}/...`).
For ServiceNow the runtime path is the Table API; the configuration
validation path is the OAuth Entity / System Definition API. They are
NOT interchangeable. A cassette of `Get_Workers` does not validate
that ISU users exist — different request, different response, often
different protocol entirely. Same goes the other way.

A 2026-05 capture attempt confirmed that the Workday admin SOAP
operations the kit's docs reference (`Get_API_Clients`,
`Get_Authentication_Policies`, `Get_Domain_Security_Policies`) are
NOT exposed via the publicly-available SOAP services on a typical
Workday tenant — `Security` service isn't in the published service
list. The path forward for Workday config validation is the REST
admin API surface, which requires a separately registered API Client
with the Application Credentials grant (different credentials from
the ISU service account used for runtime SOAP).

A subsequent 2026-05 WQL exploration captured the Workday WQL admin
surface in `workday_wql_admin.yaml` (6 useful data sources, including
`oAuth20RefreshTokenDataSource`, `allSecurityGroups`, `allCustomReports`,
`allIntegrationSystemsAudited`, `publicWebServices`, `allWorkers`).
**However, building a runtime FlightCheck check on this cassette is
currently BLOCKED by a chicken-and-egg auth problem**: WQL requires
OAuth, OAuth requires registering a FlightCheck-specific API Client in
Workday, and that registration is nearly the same workflow as the ESS
Workday integration setup the check would validate. See the WQL
section of `tests/fixtures/cassettes/INDEX.md` for the full discussion
and the four workarounds considered (none are currently viable
without either Microsoft-side changes to the ESS Workday extension
pack OR re-validating that admin SOAP operations are reachable via
WS-Security UsernameToken on this tenant). The cassette stays
committed as discovery evidence; do NOT write a check that depends on
WQL bearer auth without first solving this.

If the docs prescribe a config step you don't have a cassette for,
treat it the same as any unconfirmed API: stop and request a cassette
per the workflow above.

---

## The cardinal rule

> **You may not write FlightCheck integration tests against APIs whose
> contracts you have not verified using one of the three permitted
> tiers (`validated`, `validatable`, `documented`). The `placeholder`
> tier is NEVER permitted in a FlightCheck test.**

The full tier definitions live in
`solutions/ess-maker-skills/scripts/flightcheck/AGENTS.md` →
"The cardinal rule" / "The four mock tiers." The per-API tier
assignment lives in `tests/fixtures/cassettes/INDEX.md` →
"API tier registry." Read both before writing your test.

Quick summary for test authors:

| Tier | What backs the mock | Cassette? |
|---|---|---|
| `validated` | Real captured cassette in `tests/fixtures/cassettes/`. Test replays the cassette via `responses` / `respx`. | Required |
| `validatable` | Public schema (CSDL / OpenAPI / well-known config) + MS Learn doc with example response, both cited in the mock builder docstring. The check author already verified the property names and types against the schema. Your test uses the hand-built mock derived from the schema. | Not required (welcome as supplementary) |
| `documented` | Verbatim copy of the vendor's documented example response, with the doc URL (anchored) cited in the mock builder docstring. Your test uses the hand-built mock derived from the doc example. | Not required |
| `placeholder` | Schema-grounded best guess. **Refused by the conftest enforcement helper.** | N/A |

For the `validated` tier, the unit of confirmation is **method + path
+ response shape**, not the exact query string. Server-side query
parameters that narrow, project, sort, or paginate the same resource
(`$filter`, `$select`, `$top`, `$orderby`, `$skip`, ServiceNow
`sysparm_query` / `sysparm_fields`, Workday WQL `WHERE` / `LIMIT`,
etc.) do NOT require a new cassette — the existing capture for the
same path + method covers all narrowing variants. See the "What
counts as the same endpoint" section in
`solutions/ess-maker-skills/scripts/flightcheck/AGENTS.md` for the
full rule, including the exceptions (`$expand`, `$count=true`,
`$apply`, and anything that switches list-shape vs single-item-shape).

If you'd need a `placeholder` mock for any test, **stop, do not
guess, do not invent a mock.** Either pick a stronger tier and do
the per-tier verification, or tell the user to capture / promote
the API surface first.

This rule does not apply to:
- Tests of the kit's pure-logic helpers (no network).
- Tests of the test infrastructure itself (the redactor, the conftest fixtures).
- Regression tests pinning known bugs (those are explicitly testing
  what the broken code does, not what reality returns).

It does apply to:
- Any new check under `solutions/ess-maker-skills/scripts/flightcheck/checks/`
  that calls an external API.
- Any test under `tests/flightcheck/` that exercises a check end-to-end.
- Any new mock builder you'd add to `tests/mocks/`.

---

## How to identify which tier an API is in

Two places to look, in this order:

1. **`tests/fixtures/cassettes/INDEX.md` → "API tier registry"** —
   the canonical per-API tier list (validated / validatable /
   documented). If the API isn't in the registry, STOP and tell the
   user; the tier must be decided before you can pick a verification
   path.

2. **`tests/mocks/<api>.py` module header.** Every mock module
   declares `MOCK_STATUS = "validated" | "validatable" | "documented"
   | "placeholder"`. The first three are usable in FlightCheck tests;
   the last one is rejected by `require_validated_mock()` at test
   collection time.

3. **Each mock builder's docstring.** A `validated` builder cites the
   cassette + line range. A `validatable` builder cites the schema URL
   (e.g. `https://graph.microsoft.com/v1.0/$metadata`) + the MS Learn
   operation doc. A `documented` builder cites the MS Learn doc URL
   with anchor + has the example response copied verbatim.

If the registry tier and the mock module's `MOCK_STATUS` disagree,
the registry wins — the mock module needs to be updated (or the
registry corrected with rationale).

---

## What to do when you need a new endpoint

The action depends on which tier the API is in:

**For `validated` APIs:** when a new FlightCheck check needs an
endpoint that is not in the "Confirmed endpoints" table of `INDEX.md`,
stop and tell the user. Use this template:

> I need to write a test for FlightCheck check `<checkpoint id>`, which
> calls `<HTTP method> <full URL pattern>` on `<service name>`. This
> API is in the `validated` tier and no existing cassette covers this
> path + method. I cannot verify the response shape my mock would
> produce matches reality.
>
> Before I continue, please capture a cassette for this endpoint:
>
> 1. If a recording wrapper for this endpoint already exists in
>    `tests/captures/`, set the required env vars and run it. Otherwise:
> 2. Create a new recording wrapper modelled on
>    `tests/captures/record_flightcheck_pp_admin.py`. Set the required
>    env vars (e.g. `ESS_DATAVERSE_URL` for tenant resolution, plus any
>    service-specific creds) and run it.
> 3. Review the captured cassette in `tests/fixtures/cassettes/.raw/`
>    by eyeball for any leftover real names / emails / instance IDs the
>    redactor missed.
> 4. Commit the redacted cassette to `tests/fixtures/cassettes/`.
> 5. Add a row to `tests/fixtures/cassettes/INDEX.md` describing what
>    endpoints the cassette covers.
> 6. Tell me when done and I'll resume.

**For `validatable` APIs:** fetch the published schema yourself and
verify each property the check consumes — see `flightcheck/AGENTS.md`
"Workflow" step 2 for the per-API schema URLs. Add a builder to
`tests/mocks/<api>.py` derived from the schema; cite the schema URL
and the MS Learn operation doc in the docstring. No need to ask the
user for anything if the schema covers what you need.

**For `documented` APIs:** fetch the MS Learn (or vendor) operation
doc, copy the example response verbatim into the new builder
docstring, cite the doc URL with anchor. Note documented is the
weakest tier — use it only when validatable and validated aren't
feasible for that API.

Do not invent a wrapper, mock, or schema fragment. The whole point of
the tier system is that everything in a builder traces back to a real
captured response, a published schema, or a vendor-documented example.

---

## How to add a new mock builder

The procedure depends on the API's tier. Look it up in
`tests/fixtures/cassettes/INDEX.md` → "API tier registry" first.

### Validated tier (cassette-backed)

Once a cassette is captured:

1. Open the cassette and locate the response shape for the endpoint.
2. Add a builder to the appropriate `tests/mocks/<api>.py` module.
3. In the builder's docstring, cite the cassette path and approximate
   line range. Example:
   ```python
   def my_new_response(*, ...) -> dict[str, Any]:
       """...

       Cited consumers:
         - solutions/ess-maker-skills/scripts/flightcheck/checks/my_check.py:42

       Source (validated):
         tests/fixtures/cassettes/my_capture.yaml line 1234-1280
       """
   ```
4. Ensure the module declares `MOCK_STATUS = "validated"` and
   `MOCK_CASSETTE = "tests/fixtures/cassettes/<file>.yaml"`.
5. Update `tests/fixtures/cassettes/INDEX.md` "Confirmed endpoints"
   table to record the new endpoint coverage.

### Validatable tier (schema-backed, no cassette)

1. Fetch the API's published schema (see `flightcheck/AGENTS.md`
   "Workflow" step 2 for per-API schema URLs).
2. Locate the entity type your builder represents. Read off the field
   names and types you'll populate.
3. Add a builder to the appropriate `tests/mocks/<api>.py` module.
4. In the builder's docstring, cite the schema URL + the MS Learn
   operation doc. Example:
   ```python
   def my_user(*, ...) -> dict[str, Any]:
       """User response shape used by FOO-NNN.

       Cited consumers:
         - solutions/ess-maker-skills/scripts/flightcheck/checks/<category>.py:NN

       Source (validatable):
         Schema: https://graph.microsoft.com/v1.0/$metadata
                 EntityType Name="user" — fields used:
                   id (Edm.String)
                   displayName (Edm.String)
                   userPrincipalName (Edm.String)
         Docs: https://learn.microsoft.com/graph/api/user-get
       """
   ```
5. Ensure the module declares `MOCK_STATUS = "validatable"` and
   `MOCK_SCHEMA_SOURCE = "<schema URL>"`. (The conftest enforcement
   helper accepts validatable as usable for FlightCheck tests.)

### Documented tier (vendor docs, no schema)

1. Open the vendor's API reference page for the operation.
2. Locate the example response section. Copy the example JSON
   verbatim into the builder docstring.
3. Add a builder that returns a payload with the same shape; allow
   keyword overrides for the fields a test will want to vary.
4. Cite the doc URL with anchor in the docstring. Example:
   ```python
   def my_env_var(*, name: str = "X", value: str = "v") -> dict:
       """Dataverse environment variable definition record.

       Cited consumers:
         - solutions/ess-maker-skills/scripts/flightcheck/checks/workday.py:NN

       Source (documented):
         https://learn.microsoft.com/power-apps/developer/data-platform/webapi/reference/environmentvariabledefinition#response
         Example response copied verbatim 2026-XX-XX.
       """
   ```
5. Ensure the module declares `MOCK_STATUS = "documented"`.

### Promoting a builder to a higher tier

If a `documented` builder later gets cassette coverage, promote it to
`validated` (and update the docstring + module header). If a
`placeholder` builder is encountered, it must be promoted before any
FlightCheck test can use it — pick whichever of the three permitted
tiers fits the API.

---

## How to write a FlightCheck integration test

Pattern (mirrors `tests/flightcheck/checks/test_workday_env_vars.py`):

```python
import pytest, responses
from tests.mocks import dataverse as dv  # validated, validatable, or documented — never placeholder
from tests.conftest import require_validated_mock

@responses.activate
def test_my_check_passes_when_state_is_good(...):
    require_validated_mock(dv)  # fails fast if dv.MOCK_STATUS == "placeholder"

    # Arrange: register mocks for the desired tenant state.
    responses.add(**dv.query(...))

    # Act: run the actual production check.
    from flightcheck.checks.my_check import my_check
    results = my_check(runner)

    # Assert: checkpoint id, status, priority, result, remediation.
    assert results[0].status == "Passed"
    assert "expected text" in results[0].result
```

Each new check needs at minimum:
- One GOOD-state test (mock returns valid data → check returns PASSED).
- One BAD-state test (mock returns invalid/missing data → check returns
  FAILED with the expected remediation pointing at a real fix path).
- Edge tests for any branches in the check logic (no token, partial data,
  unexpected error response).

**Every GOOD / BAD / WARNING test MUST assert on specific phrases from
both `result` and `remediation`, not just on `status`.** A test that
checks only `status == "Warning"` lets misleading text regress
silently — including production incidents where the warning text
implied a runtime break that doesn't actually exist (see the AUTH-005
`Assignment required = No` rewrite for an example caught only in PR
review). At minimum, pin:

1. A phrase from `result` that names the current state the test set
   up (e.g. `"0 users/groups assigned"`, `"set to No"`,
   `"3 individual user(s) assigned but no security groups"`).
2. A phrase from `remediation` that captures both WHY the operator
   should act (impact for FAILED / hardening framing for WARNING)
   and HOW (a concrete click-path or command). For WARNING tests,
   also pin the WARNING-kind framing required by principle 9 of
   `flightcheck/AGENTS.md` — e.g. `"Hardening recommendation"`,
   `"not a functional blocker"`.
3. For status-bucketed checks (principle 7 of `flightcheck/AGENTS.md`),
   add a multi-resource test that verifies N resources in the same
   status collapse to ONE row that lists all of them — not N rows.

If a `placeholder` mock would be needed for any of the above, **stop
and follow "What to do when you need a new endpoint" above** to
promote the builder (or capture a cassette) per the API's tier.

---

## Pinning latent bugs

If you discover the kit's production code has a bug while writing tests
(see the four bugs already pinned in `tests/scripts/test_auth.py`,
`tests/flightcheck/checks/test_workday_connections.py`, and
`tests/flightcheck/test_pp_admin_client.py`), pin it with a regression
test that asserts the current buggy behavior. Include in the test docstring:

1. A clear description of the bug.
2. The recommended fix (file, line, and the proposed change).
3. A "TODO: when fixed, flip this assertion to ..." note so a future
   reader knows to update the test alongside the fix.

This prevents silent regressions while making the bug visible.

---

## Things you should not do

- Don't invent endpoint URLs, method names, or response shapes —
  every field in a mock must trace to a captured cassette, a public
  schema, or a vendor-documented example.
- Don't use a `placeholder` mock in a FlightCheck test. The
  `require_validated_mock()` enforcement helper rejects placeholder
  at collection time. Promote the builder to validated / validatable /
  documented first.
- Don't pick a weaker tier than the API tier registry mandates. If
  `INDEX.md` says an API is `validated`, treating it as `documented`
  to avoid capturing a cassette is a violation. Change the registry
  (with rationale) if you genuinely need a different tier.
- Don't disable `require_validated_mock()` enforcement in
  `conftest.py` to make a test pass.
- Don't redact a cassette by hand without running it through
  `tests/captures/_redact.py` — the script enforces the canonical
  substitution table.
- Don't commit cassettes that contain real names, real tenant friendly
  names, real instance identifiers, or real third-party URLs (real
  ServiceNow dev tenant URL, real SuccessFactors company id, etc.).
  The redactor handles known patterns; eyeball each cassette before
  commit for anything it missed.
