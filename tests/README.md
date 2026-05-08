# ESS Maker Kit — Test Suite

Pytest-based test suite covering the kit's API client modules, FlightCheck
checks, and the bundled MCP servers (Workday, ServiceNow).

**Audience: kit maintainers and contributors.** Customers don't need to run
this — the kit ships and runs without it. But every change to the production
code under `solutions/ess-maker-skills/scripts/` or
`solutions/ess-maker-skills/src/mcp/` should keep these tests green and add
coverage for new behavior.

## Why these tests matter

The kit talks to five external systems (Dataverse, Microsoft Graph, Power
Platform Admin, Workday, ServiceNow). Each one has authentication, retry,
and response-shape quirks that are easy to break and hard to spot in code
review. The test suite gives contributors (and AI coding agents) a fast
feedback loop that catches those breakages before they reach a customer
environment.

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
| `mocks/` | Reusable response builders for each external API (Dataverse, Graph, BAP, Workday, ServiceNow). Importable from any test. |
| `captures/` | One-off recording wrappers that hit real tenants and write VCR cassettes. Run manually by maintainers, not as part of the suite. |
| `fixtures/cassettes/` | Committed VCR.py cassettes (redacted). Replayed by `@pytest.mark.vcr` tests. |
| `flightcheck/`, `scripts/`, `mcp/` | Test modules mirroring the production source tree. |
| `conftest.py` | Shared fixtures (MSAL token stub, base URLs, sample config dict, tmp workspace). |

## Two layers of mocks

1. **`tests/mocks/*.py`** — hand-built response builders grounded in public
   schemas. Fast, deterministic, no cassette needed. Used by unit tests for
   the API client modules.
2. **`tests/fixtures/cassettes/*.yaml`** — real captured responses (redacted)
   from a live tenant. Used by integration tests that exercise full code
   paths end-to-end. Replayed via VCR.py.

If a `mocks/` builder and a captured cassette disagree about response shape,
**the cassette wins** — it's what the real API actually returns. Update the
mock builder to match.

## Capturing a new cassette

See [`captures/README.md`](captures/README.md) for the recording workflow.
Short version: run a recording wrapper against a real tenant, redact the raw
output, commit the cassette.

## Adding a new mock

See [`mocks/README.md`](mocks/README.md) for the conventions used by the
mock builders.
