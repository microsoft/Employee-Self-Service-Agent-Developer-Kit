# TASK-008 — Authentication Token Provider

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-008                  |
| Workstream | 0 — Repository Foundation |
| Status     | DONE                     |
| Consumes   | —                         |

## Description

Implement the **Token Provider** — the single infrastructure primitive that
*acquires* and *refreshes* Dataverse access tokens. It lives at
`src/core/auth/` and is the upstream *producer* of the bearer token that every
downstream layer merely *accepts*.

The architecture deliberately keeps token acquisition out of the service and
client layers: `AuthenticationService` (see `02_ARCHITECTURE/SERVICES.md`,
section 13) only *accepts* a bearer token and *never* stores credentials, and
`AuthenticationClient` (see `02_ARCHITECTURE/DATAVERSE_CLIENT.md`, section 5)
*never* acquires, refreshes, or persists tokens. Nothing in the current
specifications produces the token those layers consume. This task fills that
gap with a dedicated primitive so the higher layers stay clean.

The toolkit runs unattended for long sessions (an hour or more per migration).
A single token acquired at start would expire mid-run, breaking both reads and
writeback. The Token Provider therefore performs **proactive refresh**: it
exposes a `get_token()` operation that returns a currently-valid token on every
call, silently refreshing before expiry, so callers never cache a raw token
string and never observe an expired one. Downstream code obtains a fresh token
from the provider immediately before each Dataverse read and each writeback
call.

This is a foundation task consumed by `TASK-004` (Dataverse Client): TASK-004's
`AuthenticationClient` accepts the token produced here and attaches it to
requests, but does not itself acquire or refresh it.

### Reuse and coupling

The `solutions/ess-maker-skills/scripts/` clients (`auth.py`, `graph_client.py`,
`pp_admin_client.py`, `pva_client.py`) demonstrate a proven MSAL acquisition
pattern (silent-first acquisition, interactive fallback, per-resource scopes,
bounded retry on read-only verbs). Reuse the **pattern**, not the code: that
kit is an independent solution with its own lifecycle, dependencies, and
`print`/`sys.exit` conventions. Do **not** import from it or add a dependency on
it. Reimplement natively against toolkit conventions (framework Logger, typed
exceptions, dependency injection).

### Divergence from the reference pattern (mandatory)

The ess-maker clients persist their MSAL token cache to disk
(`.local/.token_cache.bin`). The toolkit **must not** do this.
`00_META/INVARIANTS.md` DIAG-003 forbids persisting sensitive information and
names access tokens and OAuth tokens explicitly. The Token Provider therefore
keeps its MSAL token cache **in memory only** for the lifetime of the process.
Cross-run single sign-on is intentionally sacrificed to honor the invariant;
within a single run, the in-memory refresh token still enables silent proactive
refresh for the whole session.

## Acceptance Criteria

- [ ] A `TokenProvider` abstraction (protocol/interface) is defined, exposing a
  `get_token()` operation that returns a currently-valid bearer token for a
  requested Dataverse resource.
- [ ] A concrete MSAL-backed provider implements silent-first acquisition
  (`acquire_token_silent`) with an interactive fallback only on cold start.
- [ ] `get_token()` performs **proactive refresh**: every call returns a token
  that is valid at return time, refreshing transparently before expiry, so a
  long-running session (an hour or more) never issues an expired token on reads
  or writeback.
- [ ] The MSAL token cache is held **in memory only** and is never written to
  disk or any durable store (INVARIANTS DIAG-003).
- [ ] Access tokens, refresh tokens, and provider error detail (for example
  MSAL `error_description`) are never logged or included in exception messages.
- [ ] All provider output flows through the framework Logger; `print()` is not
  used.
- [ ] The authority and resource/scope values are validated to be HTTPS.
- [ ] Acquisition failures raise a typed authentication exception (aligned with
  `AuthenticationException` in `03_ENGINEERING/CODING_STANDARDS.md`); the
  provider never calls `sys.exit`.
- [ ] Client id, authority/tenant, and scopes are configuration-driven, and the
  provider accepts injected collaborators (the MSAL application and a clock) so
  acquisition and refresh are unit-testable without a network or browser
  (INVARIANTS TEST-001).
- [ ] `msal` is added as a project dependency in `pyproject.toml` and pinned in
  `uv.lock`.
- [ ] Unit tests cover cold-start acquisition, silent refresh, proactive
  refresh near expiry, HTTPS validation, and the no-persistence guarantee.
- [ ] Toolkit gates pass: `uv run ruff check .`, `uv run mypy src`,
  `uv run pytest`.

## Deliverables

- `TokenProvider` abstraction (`src/core/auth/`)
- MSAL-backed token provider with in-memory cache and proactive refresh
- Typed authentication exception
- Unit tests for the provider
- `msal` dependency added to `pyproject.toml` / `uv.lock`

## References

- 02_ARCHITECTURE/SERVICES.md (AuthenticationService, section 13; Service
  Dependency Graph, section 14)
- 02_ARCHITECTURE/DATAVERSE_CLIENT.md (AuthenticationClient, section 5;
  Dataverse Client-005)
- 02_ARCHITECTURE/DOMAIN_MODEL.md (AuthenticationContext)
- 00_META/INVARIANTS.md (DIAG-003; TEST-001)
- 03_ENGINEERING/CODING_STANDARDS.md (AuthenticationException, section 205)
