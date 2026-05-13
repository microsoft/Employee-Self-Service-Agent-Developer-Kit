# Mock response builders

Hand-built response builders grounded in public schemas + the kit's own
assumptions, validated against captured cassettes where available.

> **If you are an AI agent: read [`../AGENTS.md`](../AGENTS.md) first.**
> The policy on which mocks may be used in which tests is defined there.

## The two states a mock module can be in

Every mock module in this directory declares one of these:

| `MOCK_STATUS` | Meaning | OK to use in… |
|---|---|---|
| `"validated"` | Backed by a real captured cassette (path in `MOCK_CASSETTE`). The mock's response shape has been verified against reality. | Any test, including FlightCheck integration tests under `tests/flightcheck/`. |
| `"placeholder"` | Schema-grounded best guess. No cassette captured. May or may not match what the real API returns. | **Only** unit tests that don't depend on shape correctness. **Not** FlightCheck integration tests. |

`tests/conftest.py` exports `require_validated_mock(module)` — call it
at the top of any FlightCheck integration test to fail fast if you've
accidentally pulled in a placeholder mock.

When a placeholder mock gets cassette validation, flip
`MOCK_STATUS = "validated"`, set `MOCK_CASSETTE` to the cassette path,
update each builder docstring with the cassette line range citation,
and add a row to `tests/fixtures/cassettes/INDEX.md`.

## Conventions

- **One module per API surface.** `dataverse.py`, `graph.py`, `pp_admin.py`,
  `workday.py`, `servicenow.py`.
- **Module header banner** declares `MOCK_STATUS` and (if validated)
  `MOCK_CASSETTE`.
- **Builders return canned response payloads, not full HTTP responses.**
  Tests register them with `responses` (or `respx` for httpx-based code).
  Keep builders dumb — they shouldn't know about request matching.
- **Builders take only the fields a caller might want to vary.** Defaults
  for everything else. Tests stay readable: `dataverse.who_am_i(user_id="...")`.
- **Pin every fixture value.** Stable GUIDs, stable timestamps, stable order.
  Tests should not depend on `time.time()` or `uuid.uuid4()`.
- **Cite the source.** Each builder docstring names the production line
  that consumes the field, plus (for validated modules) the cassette
  filename and line range it was derived from.

## Adding a new mock

1. Find the production code that makes the call (search for the URL).
2. Read what fields it consumes off the response (search for `.get(` /
   `["..."]` chains on the response object).
3. Build a minimal response with **exactly those fields populated**, plus
   any obvious sibling fields a future caller might need.
4. Cite the source: cassette path + line range, doc URL, or production
   source line in a comment above the builder.
5. If you're adding a new module, declare `MOCK_STATUS` and (if
   validated) `MOCK_CASSETTE` at the top.

## Adding a new check that needs an unconfirmed API

**Stop.** Do not invent a placeholder mock and write a test against
it. Read [`../AGENTS.md`](../AGENTS.md) for the full workflow. Short
version: tell the user to capture a cassette first, then come back.
