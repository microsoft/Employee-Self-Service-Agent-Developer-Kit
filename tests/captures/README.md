# Recording wrappers

One-off Python scripts that import real production code and run it once
against a real tenant under VCR.py to capture a cassette. Run manually,
**not** as part of the test suite.

## Why these exist

The `tests/mocks/` builders are hand-written from public schemas + the
codebase's assumptions. That gets us 80% there but real APIs always have
quirks (extra fields, namespace prefixes, error-shape differences) that
schema-only mocks miss. Capturing real responses and replaying them via
VCR.py catches the remaining 20%.

## Workflow

1. **Authenticate against your test tenant once** (e.g. run `flightcheck/cli.py`
   interactively to populate `.local/.token_cache.bin`).
2. **Pick the recording wrapper** for the scenario you want
   (`record_dataverse_fetch.py`, `record_flightcheck_workday.py`, etc.).
3. **Run it.** It writes a raw cassette to `tests/fixtures/cassettes/.raw/`
   (this folder is `.gitignore`d).
4. **Redact.** Run `python tests/captures/_redact.py <raw> <out>`. The
   redactor applies the substitution table for tenant GUIDs, org names,
   employee IDs, tokens, real names, and emails. **Manually review** the
   output — automated redaction can miss things.
5. **Commit** the redacted cassette to `tests/fixtures/cassettes/`.

## Safety

- **Never commit unredacted cassettes.** `tests/fixtures/cassettes/.raw/`
  is gitignored for this reason. If you're unsure, run with
  `--dry-redact` first to preview the substitutions.
- **Use a non-production tenant** when possible. Some endpoints (Workday
  RaaS, ServiceNow Live Agent) leak tenant-shape information even after
  redaction.
- **Read-only operations only.** All wrappers are scoped to GET/list calls.
  Don't extend them to POST/PATCH/DELETE without explicit team review.

## Substitution table (applied by `_redact.py`)

| Real value | Redacted value |
|---|---|
| Bearer tokens / `Authorization` headers | `Bearer REDACTED_TOKEN` |
| Tenant ID GUIDs | `00000000-0000-0000-0000-000000001111` |
| Real org URL fragment (`orgb78b4a3b`) | `orgmocktenant` |
| Real employee IDs / WIDs | `MOCK_EMP_001`, `MOCK_EMP_002`, … |
| Real user names | `Mock User N` |
| Real email addresses | `mock.user.N@contoso.com` |
| ISU service account names | `ISU_MOCK` |
| WS-Security `wsse:Password` element contents | `REDACTED_WSSE_PASSWORD` |
