# Mock response builders

Hand-built response builders grounded in public schemas + the kit's own
assumptions, validated against captured cassettes where available.

> **If you are an AI agent: read [`../AGENTS.md`](../AGENTS.md) first.**
> The policy on which mocks may be used in which tests is defined there.

## The four states a mock module can be in

Every mock module in this directory declares one of these:

| `MOCK_STATUS` | Meaning | Module-header companions | OK to use in… |
|---|---|---|---|
| `"validated"` | Backed by a real captured cassette. Highest fidelity — the response shape has been verified against a live tenant. | `MOCK_CASSETTE = "tests/fixtures/cassettes/<file>.yaml"` | Any test, including FlightCheck integration tests under `tests/flightcheck/`. |
| `"validatable"` | Backed by a publicly-fetchable machine-readable schema (CSDL / OpenAPI / well-known config) that the builder author verified at authoring time, plus a cited MS Learn doc URL with example response. No tenant required to verify. | `MOCK_SCHEMA_SOURCE = "<schema URL>"` | FlightCheck integration tests. |
| `"documented"` | Backed by vendor prose docs + a verbatim copy of the documented example response in the builder docstring. Weaker than the two above; only use when neither validatable nor validated is feasible. | (Each builder docstring cites the doc URL with anchor.) | FlightCheck integration tests. |
| `"placeholder"` | Schema-grounded best guess. Not verified against anything real. | (none) | **Never** in FlightCheck integration tests. The `require_validated_mock()` helper rejects this at collection time. Test-infrastructure / pure-logic unit tests only. |

`tests/conftest.py` exports `require_validated_mock(module)` — call it
at the top of any FlightCheck integration test to fail fast if you've
accidentally pulled in a placeholder mock. (Despite the name, the
helper accepts `validated`, `validatable`, AND `documented` — only
`placeholder` is rejected.)

The per-API tier assignment lives in
`tests/fixtures/cassettes/INDEX.md` → "API tier registry." A module's
`MOCK_STATUS` should match (or strengthen) the registry's tier for
that API. If they disagree, the registry wins.

When promoting a placeholder module to validated, validatable, or
documented: flip `MOCK_STATUS`, set the appropriate companion
constant (`MOCK_CASSETTE` / `MOCK_SCHEMA_SOURCE` / doc URL in
docstrings), update each builder docstring with the proper citation,
and (for validated only) add a row to
`tests/fixtures/cassettes/INDEX.md` "Confirmed endpoints."

## Conventions

- **One module per API surface.** `dataverse.py`, `graph.py`, `pp_admin.py`,
  `workday.py`, `servicenow.py`.
- **Module header banner** declares `MOCK_STATUS` and (if applicable)
  the companion citation constant: `MOCK_CASSETTE` for `"validated"`,
  `MOCK_SCHEMA_SOURCE` for `"validatable"`. `"documented"` modules cite
  the doc URL inside each builder docstring.
- **Builders return canned response payloads, not full HTTP responses.**
  Tests register them with `responses` (or `respx` for httpx-based code).
  Keep builders dumb — they shouldn't know about request matching.
- **Builders take only the fields a caller might want to vary.** Defaults
  for everything else. Tests stay readable: `dataverse.who_am_i(user_id="...")`.
- **Pin every fixture value.** Stable GUIDs, stable timestamps, stable order.
  Tests should not depend on `time.time()` or `uuid.uuid4()`.
- **Cite the source.** Each builder docstring names the production line
  that consumes the field, plus the appropriate per-tier source citation:
  - `validated` → cassette filename + line range
  - `validatable` → schema URL + entity/property fragment + MS Learn doc URL
  - `documented` → MS Learn (or vendor) doc URL with anchor + verbatim example block

## Adding a new mock

1. Find the production code that makes the call (search for the URL).
2. Read what fields it consumes off the response (search for `.get(` /
   `["..."]` chains on the response object).
3. Look up the API tier in `tests/fixtures/cassettes/INDEX.md` →
   "API tier registry."
4. Build a minimal response with **exactly the fields production consumes**
   populated, plus any obvious sibling fields a future caller might need.
5. Cite the source per the tier (cassette / schema URL / doc URL).
6. If you're adding a new module, declare `MOCK_STATUS` and the matching
   citation companion at the top.

## Adding a new check that needs an unconfirmed API

**Stop.** Do not invent a placeholder mock and write a test against
it. Read [`../AGENTS.md`](../AGENTS.md) for the full workflow. Short
version: identify the API tier, do the per-tier verification (capture
a cassette / fetch the schema / cite the doc), promote the builder,
then write the test.
