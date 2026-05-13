# Instructions for AI agents adding or modifying FlightCheck checks

If you are an AI coding agent (Copilot CLI, Claude, or any other) working
in this directory tree, **read this file first and follow it strictly.**

This document covers the rules for the **production checks themselves**
(the code customers run via `/flightcheck`). Test-authoring rules are
in `tests/AGENTS.md`. They complement each other; you need both.

---

## The cardinal rule

> **Every FlightCheck check that calls an external API must have a
> captured cassette of real responses from that API, AND a test that
> exercises the check against the cassette.**

A check that calls an endpoint nobody has confirmed exists is worse than
no check at all — it produces a confidently wrong result and erodes the
trust customers place in FlightCheck.

"Confirmed real" means: there is a cassette in
`tests/fixtures/cassettes/` listed in `tests/fixtures/cassettes/INDEX.md`
that captured the exact endpoint + method + response shape from a live
tenant. If the endpoint isn't in `INDEX.md`, it isn't confirmed.

---

## Workflow when adding a new check that calls an external API

Do these steps in order. Don't skip any.

### 1. Check whether the API is confirmed real

Read `tests/fixtures/cassettes/INDEX.md`. Look in the "Confirmed
endpoints" table for the exact `method + URL pattern` you intend to
call. If it's there with a green status, proceed to step 4.

### 2. If the API is NOT in the index — STOP

Do not write the check. Do not invent a URL based on what seems plausible
from the docs. Do not copy a snippet from another part of the codebase
and assume the endpoint works. Do not write a mock builder by hand and
assume it matches reality. Tell the user:

> I need to write a FlightCheck check for `<checkpoint id>` which calls
> `<HTTP method> <full URL pattern>` on `<service name>`. This endpoint
> is not in `tests/fixtures/cassettes/INDEX.md`, so I cannot confirm
> the response shape or even that the endpoint exists.
>
> Before I continue, please capture a cassette for this endpoint.
> Follow the steps in `tests/AGENTS.md` under "How to add a new mock
> builder (validated path)". Then I'll resume.

### 3. After a cassette is captured

Once the cassette is in `tests/fixtures/cassettes/` and `INDEX.md` is
updated, you can write the check. The cassette is your ground truth
for the response shape.

### 4. Write the check

Place the check in the appropriate `checks/{category}.py` module. The
check function:
- Uses `runner.<client>` (e.g. `runner.pp_admin`, `runner.graph`,
  `runner.workday`) — don't instantiate HTTP clients yourself.
- Returns `list[CheckResult]`.
- Each result has `checkpoint_id`, `category`, `priority`, `status`,
  `description`, `result`, optional `remediation` and `doc_link`.
- Maps cleanly to good-state / bad-state / partial-state branches.

### 5. Write the test BEFORE you ship

In `tests/flightcheck/checks/test_{category}.py`:
- One test for the GOOD state (mock returns valid data → check returns
  PASSED).
- One test for the BAD state (mock returns missing/invalid data → check
  returns FAILED with a remediation that points at a real fix path).
- Edge tests for any branches in the check logic.

If a placeholder mock would be needed for any of the above, **the API
isn't actually confirmed real for your purpose** — go back to step 2.

---

## Things you must NOT do

- **Don't invent endpoint URLs, methods, or response shapes.** If the
  docs prescribe a config step you don't have a cassette for, request
  the cassette per step 2 above.
- **Don't import `responses`, `respx`, or VCR from a check file.** Those
  are test-only libraries. Check files use real HTTP clients
  (`requests`, `httpx`, or the kit's `*_client.py` wrappers).
- **Don't ship a check whose only "test" is a unit test of a hand-rolled
  mock builder.** If the test doesn't replay a real cassette, it
  doesn't prove the check works against the API.
- **Don't bypass `runner.<client>` and create your own session.** The
  runner clients carry auth, retry, and pagination logic the check
  depends on, plus they're the layer the tests mock.
- **Don't add a check that depends on an API for which the cassette
  has a documented blocker.** Example: WQL bearer-only auth requires
  Workday API Client registration — `tests/fixtures/cassettes/INDEX.md`
  and the WQL recorder explicitly say "do NOT build a runtime check
  on this cassette without resolving the chicken-and-egg first." Read
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
- `tests/fixtures/cassettes/INDEX.md` — the registry of confirmed-real
  endpoints. The first thing to check when planning a new check.
- `tests/mocks/<system>.py` — validated mock builders cited from real
  cassettes. The vocabulary your test uses to set up mock state.
