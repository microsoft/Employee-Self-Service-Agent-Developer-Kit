# Workday REST endpoint diagnostic

Standalone interactive diagnostic that validates the 9 Workday REST
connector actions the Employee Self-Service (ESS) agent invokes at
runtime. Uses the OAuth 2.0 Authorization Code grant against a Workday
API Client you register in your own tenant.

## Why this lives outside FlightCheck

The FlightCheck runner (`scripts/flightcheck/cli.py`) is designed to
authenticate against a customer's environment using credentials the
operator already has (Dataverse, Microsoft Graph, Power Platform Admin,
Copilot Studio Island Gateway) and validate everything automatically.
Workday REST validation can't fit that model: Workday REST endpoints
accept ONLY OAuth 2.0 Bearer tokens, and obtaining one requires the
customer to register their own API Client in Workday. That's the same
chicken-and-egg auth problem documented in
[`tests/fixtures/cassettes/INDEX.md`](../../../../tests/fixtures/cassettes/INDEX.md)
under "Workday WQL config-validation pattern."

So FlightCheck surfaces a `NotConfigured` checkpoint (`WD-REST-MANUAL`)
that points customers at this script. Customers run it interactively
once and attach the resulting JSON to their deployment ticket.

## What it tests

9 endpoints corresponding to the 9 Workday REST connector actions in
ESS. The PowerShell ancestor (`Test-WorkdayRESTEndpoints.ps1` in
`ess-preflight-validator`) used identical checkpoint IDs.

| # | Checkpoint | Operation | Type | Validates |
|---|---|---|---|---|
| 0 | `WD-REST-AUTH` | OAuth Token | Auth | Authorization Code flow yields a bearer token |
| 1 | `WD-REST-ME` | `GET workers/me` | Identity | Authenticated user's profile is returned (gate for all subsequent reads) |
| 2 | `WD-REST-001` | `GetWorkerInboxTasks` | Read | Inbox tasks endpoint is reachable + permitted |
| 3 | `WD-REST-002` | `GetWorkerPaySlips` | Read | Pay slips endpoint is reachable + permitted |
| 4 | `WD-REST-003` | `SearchWorkers` | Read | People picker queries work |
| 5 | `WD-REST-004` | `GetWorkerDirectReports` | Read | Manager view of direct reports works |
| 6 | `WD-REST-005` | `GetSupervisoryOrganizationsManaged` | Read | Manager view of orgs works |
| 7 | `WD-REST-006` | `GetFeedbackTemplates` | Read | Feedback templates endpoint is reachable |
| 8 | `WD-REST-007` | `TransferEmployee` | Write | Job change endpoint reachable (opt-in via `--include-write-tests`) |
| 9 | `WD-REST-008` | `RequestFeedback` | Write | Feedback request endpoint reachable (opt-in) |

Write tests send a minimal body; an HTTP 400 or 422 response is treated
as a PASS because it confirms the endpoint is reachable and the OAuth
client is authorized — the request body was intentionally not a real
business payload.

## Prerequisites

1. **Python 3.11+** (matches the rest of the kit).
2. The kit's script dependencies installed:
   ```bash
   pip install -r solutions/ess-maker-skills/scripts/requirements.txt
   ```
3. **A Workday OAuth API Client** registered in your tenant:
   - Workday > **Register API Client** (or **Edit API Client**)
   - Grant Type: **Authorization Code**
   - Redirect URI: `https://localhost:8888/callback` (default) or your
     own — pass it via `--redirect-uri`
   - Note the **Client ID** and **Client Secret** (the secret is shown
     exactly once; copy it immediately)
4. **Security domain access** for the API Client:
   - Self-Service: Current Staffing Information (gates `/workers/me`)
   - Worker Data: Inbox / Pay / Reports / Organizations (read tests)
   - Performance Management (feedback templates)
   - Staffing (write tests, if you opt in)

## Usage

### Interactive (recommended for the first run)

```bash
python solutions/ess-maker-skills/scripts/diagnostics/test_workday_rest_endpoints.py
```

You'll be prompted for the tenant, hosts, Client ID, and Client Secret.
The browser opens to Workday's login page; sign in. The browser then
redirects to `https://localhost:8888/callback?code=...` and shows a
connection error (expected — there's no server listening on HTTPS).
**Copy the FULL URL from the address bar** and paste it back at the
prompt. The script extracts the `code`, verifies the `state` parameter
matches what it sent, exchanges the code for an access token, and runs
the 9 endpoint tests.

### Fully parameterized (CI-friendly, non-interactive prompts disabled)

```bash
python solutions/ess-maker-skills/scripts/diagnostics/test_workday_rest_endpoints.py \
    --workday-tenant contoso_impl1 \
    --workday-host wd2-impl-services1.workday.com \
    --authorize-host impl.workday.com \
    --oauth-client-id YTIzM2RlNDct... \
    --oauth-client-secret '<paste-here-or-let-the-script-prompt>'
```

Even fully-parameterized, the OAuth flow still needs a browser. There
is no fully-headless mode by design — the chicken-and-egg auth bootstrap
problem is precisely what this script does NOT try to solve.

### Optional: HTTP loopback listener (advanced)

If your Workday API Client is registered with `http://localhost:8888/callback`
(plain HTTP, not HTTPS), you can let the script spin up a tiny stdlib
HTTP server to capture the callback automatically:

```bash
python solutions/ess-maker-skills/scripts/diagnostics/test_workday_rest_endpoints.py \
    --redirect-uri http://localhost:8888/callback \
    --listen
```

The script falls back to the paste-the-URL flow if `--listen` is set
but `--redirect-uri` is HTTPS, because stdlib `http.server` cannot
terminate TLS without a cert and shipping a self-signed cert with the
diagnostic causes its own trust-store friction.

### Include write tests (test/impl tenants only!)

```bash
python solutions/ess-maker-skills/scripts/diagnostics/test_workday_rest_endpoints.py \
    --include-write-tests \
    ...
```

> ⚠️ Only enable write tests in test/impl tenants. The bodies are
> intentionally minimal placeholders; if your security domain permits
> them, the requests are recorded by Workday. A `400` or `422` response
> is a PASS — the endpoint is reachable.

## Output

A summary is printed to stdout and a structured JSON file is written
to `workspace/flightcheck/workday-rest-<UTC-timestamp>.json` (override
with `--output-dir`).

### What the JSON contains

- Test metadata: timestamp, tenant, API root, totals per status.
- Per-checkpoint result: `id`, `operation`, `type`, `status`,
  `details`, `latency_ms`, `http_status`.
- A `workers_me_response` block with the GetWorkerMe response, useful
  for reviewing which Workday security domains the API client has.

### Secrets and PII hygiene

- The OAuth **client secret**, **authorization code**, **access token**,
  and **refresh token** are NEVER logged to stdout, the JSON output, or
  the OAuth callback log. The token endpoint's error responses are
  reduced to status + error class to avoid leaking either the secret
  or the code.
- The **GetWorkerMe response** is included in the JSON for diagnostic
  value but PII fields (`descriptor`, `primaryWorkEmail`,
  `businessTitle`, `primarySupervisoryOrganization.descriptor`, and the
  raw WID in `id`) are **redacted by default**. Pass `--include-pii` to
  keep them when debugging inside your own tenant. Even then, do not
  paste the JSON into a public issue tracker.

## Parameters

| Flag | Required | Description |
|------|----------|-------------|
| `--workday-tenant` | Yes (or prompted) | Workday tenant name (e.g. `contoso_impl1`). |
| `--workday-host` | Yes (or prompted) | Workday REST API host (e.g. `wd2-impl-services1.workday.com`). |
| `--authorize-host` | Yes (or prompted) | Workday OAuth authorize host (e.g. `impl.workday.com`). |
| `--oauth-client-id` | Yes (or prompted) | OAuth Client ID. |
| `--oauth-client-secret` | Yes (or prompted) | OAuth Client Secret (use a credential manager when scripting). |
| `--redirect-uri` | No | Override the OAuth redirect URI. Default: `https://localhost:8888/callback`. |
| `--listen` | No | Start an HTTP loopback listener for the callback. Only valid with `http://localhost` redirect URIs. |
| `--include-write-tests` | No | Include `TransferEmployee` + `RequestFeedback`. Skipped by default. |
| `--include-pii` | No | Keep employee PII in the JSON output. Default: redacted. |
| `--test-worker-id` | No | Worker ID to use for employee-specific reads. Default: WID returned by GetWorkerMe. |
| `--search-term` | No | Search term for SearchWorkers. Default: first word of GetWorkerMe descriptor. |
| `--output-dir` | No | Where to write the JSON. Default: `workspace/flightcheck`. |

## Common host values

| Environment | `--workday-host` (REST API) | `--authorize-host` (OAuth) |
|-------------|------------------------------|----------------------------|
| Implementation (DC2) | `wd2-impl-services1.workday.com` | `impl.workday.com` |
| Implementation (DC5) | `wd5-impl-services1.workday.com` | `impl.workday.com` |
| Production (DC5) | `wd5-services1.workday.com` | `wd5.myworkday.com` |

## Troubleshooting

### `[WD-REST-AUTH] FAIL — token endpoint returned HTTP 401`

Workday rejected the client credentials. Verify:
- Client ID and Secret match what Workday > Register API Client shows
- The grant type on the API Client is **Authorization Code**
- The redirect URI you used matches exactly (including scheme and port)

### `[WD-REST-ME] FAIL 403`

Auth worked but the API Client lacks
**Self-Service: Current Staffing Information**. Ask the Workday admin to
grant that domain to the API Client.

### `[WD-REST-00x] FAIL 403`

The API Client is missing one of the Worker Data / Performance
Management security domains. The `details` field on the result names
which checkpoint failed; map back to the prerequisites section above.

### `[WD-REST-00x] FAIL 404`

The endpoint path doesn't exist on this tenant's API version. This is
rare for the ESS-supported endpoints but possible when running against
a very old tenant or a tenant in a different data center than expected.
Check `--workday-host` against the common host values above.

### Browser shows "connection refused" — expected

When the redirect URI is `https://localhost:8888/callback` (default),
Workday will redirect the browser there after sign-in. There's no
server listening because the script does not ship a TLS cert. The
browser shows a connection error; this is normal — copy the URL from
the address bar and paste it.

## How this relates to other validators

- **SOAP-side SSO**: `solutions/ess-maker-skills/src/reference/workday-sso-test-flow/`
  is a Power Automate flow template that tests the `OAuthUser` Entra
  SSO connection via `Get_Workers` SOAP. Different connection, different
  auth model — not a substitute for this REST diagnostic.
- **FlightCheck Workday checks** (`checks/workday.py`): validate
  Dataverse env vars, connection references, flow status, and SOAP
  workflows. They do NOT validate REST endpoints (deliberately — see
  the architecture note above).
- **Tier registry**: this diagnostic is referenced from the
  `Workday WQL / REST` row of `tests/fixtures/cassettes/INDEX.md`.
