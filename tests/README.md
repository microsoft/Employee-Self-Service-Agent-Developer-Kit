# ESS Maker Kit — FlightCheck Test Suite

Pytest-based test suite covering the FlightCheck readiness checks under
`solutions/ess-maker-skills/scripts/flightcheck/` and the parts of the
kit's shared `auth.py` that FlightCheck depends on.

**Audience: kit maintainers and contributors.** Customers don't need to
run this — the kit ships and runs without it. But every change to
FlightCheck or to the parts of `auth.py` it consumes should keep these
tests green and add coverage for new behavior.

**Out of scope** (deliberately): the kit's setup/sync scripts
(`fetch_and_setup.py`, `push.py`, `extract.py`, `setup.py`,
`checkpoint.py`, `discover.py`, `sync_*.py`) and the bundled MCP servers
under `src/mcp/`. Those are separate concerns; if they need test
coverage in the future, that's a separate suite.

## Why these tests matter

FlightCheck talks to four external systems (Dataverse, Microsoft Graph,
Power Platform Admin BAP, Workday SOAP). Each one has authentication,
retry, and response-shape quirks that are easy to break and hard to
spot in code review. The test suite gives contributors (and AI coding
agents) a fast feedback loop that catches those breakages before they
reach a customer environment.

## Running the tests

From the repo root:

```powershell
pip install -r requirements-dev.txt
pytest
```

With coverage:

```powershell
pytest --cov --cov-report=term-missing --cov-report=html
```

## Layout

| Folder | Purpose |
|---|---|
| `mocks/` | Reusable response builders for each external API (Dataverse, BAP, …). Importable from any test. |
| `captures/` | One-off recording wrappers that hit real tenants and write VCR cassettes. Run manually by maintainers, not as part of the suite. |
| `fixtures/cassettes/` | Committed VCR.py cassettes (redacted). Replayed by `@pytest.mark.vcr` tests. |
| `flightcheck/` | Test modules mirroring `solutions/ess-maker-skills/scripts/flightcheck/`. |
| `scripts/` | Tests for the FlightCheck-relevant slice of `solutions/ess-maker-skills/scripts/auth.py`. |
| `conftest.py` | Shared fixtures (MSAL token stub, base URLs, sample config dict, tmp workspace). |

## Two layers of mocks

1. **`tests/mocks/*.py`** — hand-built response builders grounded in
   public schemas + the FlightCheck source code's own assumptions.
   Fast, deterministic, no cassette needed. Used by the GOOD/BAD
   integration tests under `tests/flightcheck/`.
2. **`tests/fixtures/cassettes/*.yaml`** — real captured responses
   (redacted) from a live tenant. Used by integration tests that
   exercise full code paths end-to-end. Replayed via VCR.py.

If a `mocks/` builder and a captured cassette disagree about response
shape, **the cassette wins** — it's what the real API actually returns.
Update the mock builder to match.

## Capturing a new cassette

See [`captures/README.md`](captures/README.md) for the recording workflow.
Short version: run a recording wrapper against a real tenant, redact the
raw output, commit the cassette.

## Adding a new mock

See [`mocks/README.md`](mocks/README.md) for the conventions used by the
mock builders.
