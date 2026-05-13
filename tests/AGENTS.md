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

> **You may not write FlightCheck integration tests against APIs that have
> not been confirmed real with a captured cassette.**

"Confirmed real" means: a cassette in `tests/fixtures/cassettes/` captured
a real response from that exact endpoint against a live tenant. The
cassette acts as evidence the endpoint exists, accepts the request shape
the kit builds, and returns the response shape the kit consumes.

If you think an endpoint exists but no cassette covers it, **stop, do not
guess, do not invent a mock, do not write the test.** Tell the user to
capture a cassette first. A made-up mock that passes a test you wrote is
worse than no test at all — it gives false confidence that the production
code works when it may be calling an endpoint that doesn't exist or has
a different shape than you assumed.

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

## How to check whether an API is "confirmed real"

Three places to look, in this order:

1. **`tests/fixtures/cassettes/INDEX.md`** — the registry. Lists every
   confirmed endpoint with the cassette filename. If your endpoint is
   not in the index, it is not confirmed.

2. **`tests/mocks/<api>.py` module header.** Every mock module declares
   `MOCK_STATUS = "validated"` (cassette-backed) or
   `MOCK_STATUS = "placeholder"` (schema-grounded best guess). Validated
   modules are safe to use in integration tests; placeholder modules
   are not.

3. **Each mock builder's docstring.** A validated builder cites the
   cassette + line range it was derived from. A placeholder builder
   cites the missing cassette path that needs to be captured.

If any of these three signals say "not confirmed", treat it as not
confirmed and stop.

---

## What to do when you need a new API

When a new FlightCheck check needs an endpoint that is not in the index,
stop and tell the user. **Do not proceed with implementation.** Use this
template for the message:

> I need to write a test for FlightCheck check `<checkpoint id>`, which
> calls `<HTTP method> <full URL pattern>` on `<service name>`. This
> endpoint is not in `tests/fixtures/cassettes/INDEX.md` and not covered
> by any existing cassette, so I cannot verify the response shape my mock
> would produce matches reality.
>
> Before I continue, please capture a cassette for this endpoint:
>
> 1. If a recording wrapper for this endpoint already exists in
>    `tests/captures/`, set the required env vars and run it. Otherwise:
> 2. Create a new recording wrapper modelled on
>    `tests/captures/record_dataverse_whoami.py`. Set
>    `ESS_DATAVERSE_URL` (or the equivalent for the service) and any
>    other required env vars, then run it.
> 3. Review the captured cassette in `tests/fixtures/cassettes/.raw/`
>    by eyeball for any leftover real names / emails / instance IDs the
>    redactor missed.
> 4. Commit the redacted cassette to `tests/fixtures/cassettes/`.
> 5. Add a row to `tests/fixtures/cassettes/INDEX.md` describing what
>    endpoints the cassette covers.
> 6. Tell me when done and I'll resume.

Do not invent a wrapper, mock, or cassette on your own. The whole point
of the cassette is that it came from a real API — synthetic data
defeats the purpose.

---

## How to add a new mock builder (validated path)

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

       Reference: tests/fixtures/cassettes/my_capture.yaml line 1234-1280
       """
   ```
4. If the module was previously a placeholder, flip
   `MOCK_STATUS = "validated"` and remove the placeholder banner.
5. Update `tests/fixtures/cassettes/INDEX.md` to record the new
   endpoint coverage.

---

## How to write a FlightCheck integration test (validated path)

Pattern (mirrors `tests/flightcheck/checks/test_workday_env_vars.py`):

```python
import pytest, responses
from tests.mocks import dataverse as dv  # only validated modules

@responses.activate
def test_my_check_passes_when_state_is_good(...):
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

If a placeholder mock would be needed for any of the above, **stop and
request the cassette per the template above.**

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

- Don't invent endpoint URLs, method names, or response shapes.
- Don't assume a placeholder mock is "close enough" to write an
  integration test against. Either get a cassette or skip the test.
- Don't disable `require_validated_mock()` enforcement in `conftest.py`
  to make a test pass.
- Don't redact a cassette by hand without running it through
  `tests/captures/_redact.py` — the script enforces the canonical
  substitution table.
- Don't commit cassettes that contain real names, real tenant friendly
  names, real instance identifiers, or real third-party URLs (real
  ServiceNow dev tenant URL, real SuccessFactors company id, etc.).
  The redactor handles known patterns; eyeball each cassette before
  commit for anything it missed.
