# ESS Maker Kit — FlightCheck Test Suite

Pytest-based test suite covering the FlightCheck readiness checks under
`solutions/ess-maker-skills/scripts/flightcheck/` and the parts of the
kit's shared `auth.py` that FlightCheck depends on.

**Audience: kit maintainers and contributors.** Customers don't need to
run this — the kit ships and runs without it. But every change to
FlightCheck or to the parts of `auth.py` it consumes should keep these
tests green and add coverage for new behavior.

The suite also includes shared-script tests under `scripts/` and MCP contract, protocol, and landing-page skill tests under `mcp/`.

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
| `mcp/agentconfig/` | Landing-page MCP contracts, structural instruction guards, and opt-in model-driven skill evaluations. |

## Landing-page skill evaluations

`mcp/agentconfig/test_skill_behaviors.py` runs a real Copilot model with the shipped landing-page skill and MCP tool schemas. Synthetic recording tools emulate server state and workspace files; the model chooses the calls and constructs update payloads. The assertions inspect those actual calls, saved values, and maker-facing replies. No production tenant, external widget, or authored agent workspace is accessed.

Install the optional evaluation dependency and provision its matched runtime:

```powershell
python -m pip install -e ".[test,skill-eval]"
$env:COPILOT_CLI_EXTRACT_DIR = Join-Path $PWD ".local\skill-evals\copilot-runtime"
python -m copilot download-runtime
gh auth status
python -m pytest tests\mcp\agentconfig\test_skill_behaviors.py --run-live -v
```

The `gh` account must have Copilot model access. These tests make billable model calls and are skipped by default, including in the normal offline CI suite. The reference model is `gpt-5.4`; set `ESS_SKILL_EVAL_MODEL` to evaluate another model against the same assertions. Model-specific failures remain failures; the runner does not retry with another model or relax safety assertions. Each turn has a 120-second timeout, each case has a 24-tool-call limit, and each session has the runtime's minimum 30-credit limit. SDK sessions expose only the synthetic tools, with workspace discovery, plugins, skills, memory, host Git operations, and production MCP connections disabled.

Each case writes `trace.json` into its pytest temporary directory, recording the model, skill hash, synthetic context, tool arguments/results, and final replies. Use pytest's `--basetemp` option to choose a retained artifact directory. Authentication tokens and model reasoning are not included in these traces.

The scenarios cover matching widget drafts, stale snapshots, server-side changes between turns, failed or externalized reads, deleted-link preservation, current-value answers, wrong-entity context, instruction-like field text, visual accent lookups, default starter prompts, and the guided overview. They also cover proposed drafts, starter-prompt edits and destructive confirmation, partial insight toggles, and branding validation/contrast confirmation. The local validation command is simulated and recorded without executing model-supplied commands. These evaluations cover model-visible widget context and tool behavior; transport of `updateModelContext` events and widget rendering require separate host integration coverage.

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
