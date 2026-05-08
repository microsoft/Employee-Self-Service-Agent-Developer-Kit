# Mock response builders

Hand-built response builders grounded in public schemas, the codebase's own
assumptions, and (once captured) real cassette payloads. Used by unit tests
to drive each API client module through its happy paths and known error
paths without hitting a real tenant.

## Conventions

- **One module per API surface.** `dataverse.py`, `graph.py`, `pp_admin.py`,
  `workday.py`, `servicenow.py`, `auth.py`.
- **Builders return canned response payloads, not full HTTP responses.**
  Tests register them with `responses` (or `respx` for httpx-based code).
  Keep builders dumb — they shouldn't know about request matching.
- **Builders take only the fields a caller might want to vary.** Defaults for
  everything else. Tests stay readable: `dataverse.who_am_i(user_id="...")`.
- **Pin every fixture value.** Stable GUIDs, stable timestamps, stable order.
  Tests should not depend on `time.time()` or `uuid.uuid4()`.
- **Keep the schema-grounded mocks honest about what they don't know.**
  If a field's exact serialization shape is unverified, add a TODO comment
  citing the cassette filename it needs to be cross-checked against.

## Adding a new mock

1. Find the production code that makes the call (search for the URL).
2. Read what fields it consumes off the response (search for `.get(` /
   `["..."]` chains on the response object).
3. Build a minimal response with **exactly those fields populated**, plus
   any obvious sibling fields a future caller might need.
4. Cite the source: doc URL, cassette path, or production source line in a
   comment above the builder.
