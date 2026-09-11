## Analysis: Programmatic Connection Creation for Preprod Power Platform Environments

### Goal
Create a Workday SOAP connection and a Dataverse connection in a Preprod (PPE) Power Platform environment (`87b98cf3-70b5-ebc7-af50-61327a5bd8fe`, URL `https://orgc32b44e3.crm10.dynamics.com`) and bind them to connection references — all without manual portal interaction.

### The Core Problem
There are **three layers** to this problem, and each has a blocker:

---

### Layer 1: The environment is invisible to Prod API endpoints

The environment was created via `pac admin create --cloud Preprod`. This means it lives in the **Preprod ring**, not the Prod ring. All standard API endpoints (`api.bap.microsoft.com`, `api.powerapps.com`) only see Prod-ring environments.

**Evidence:**
- `api.bap.microsoft.com` → `GET .../environments/{ENV_ID}` → **404 EnvironmentNotFound** ("could not be found in tenant")
- `api.powerapps.com` → `GET .../apis/shared_workdaysoap?$filter=environment eq '{ENV_ID}'` → **404 ServiceToServiceEnvironmentNotFound**
- `api.bap.microsoft.com` → `GET .../scopes/admin/environments` → lists 118 environments, **none match** `orgc32b44e3`

The environment IS reachable via its Dataverse URL directly (`https://orgc32b44e3.crm10.dynamics.com/api/data/v9.2/` works fine with MSAL tokens). But the PowerApps/BAP management plane can't see it.

---

### Layer 2: The Preprod API surface has different endpoints and scopes

**DNS resolution results:**

| Hostname | Resolves? |
|---|---|
| `api.preprod.powerapps.com` | NO |
| `api.preprod.bap.microsoft.com` | NO |
| `tip1.api.powerapps.com` | YES, but returns **410 ServiceDecommissioned** |
| `tip2.api.powerapps.com` | YES (untested) |
| `api.preprod.powerplatform.com` | YES — **this is the working Preprod base** |
| `api.powerplatform.com` | YES (Prod equivalent) |

**The working endpoint is `api.preprod.powerplatform.com`**, and it uses a **different path pattern** than the old PowerApps APIs:

| Old pattern (api.powerapps.com) | New pattern (api.preprod.powerplatform.com) |
|---|---|
| `/providers/Microsoft.PowerApps/connections?$filter=environment eq '{id}'` | `/connectivity/environments/{id}/connections` |
| `/providers/Microsoft.PowerApps/apis/shared_workdaysoap?$filter=...` | `/connectivity/environments/{id}/apis/shared_workdaysoap` |
| API versions: `2020-06-01` through `2024-05-01` | API versions: `2024-10-01`, `2026-05-01-preview`, `2022-03-01-preview`, `2021-10-01-preview` |

---

### Layer 3: The `/connectivity/` endpoint requires a different token audience and delegated permissions

**Token scope test results for `GET /connectivity/environments/{id}/connections?api-version=2024-10-01`:**

| Scope | Result |
|---|---|
| `https://service.powerapps.com//.default` | **401 InvalidAudience** |
| `https://api.powerplatform.com/.default` | **401 InvalidAudience** |
| `https://management.azure.com/.default` | **401 InvalidAudience** |
| `https://api.preprod.powerplatform.com/.default` | **403 InsufficientDelegatedPermissions** — "Application missing required delegated permissions: `[Connectivity.Connections.Read, All.All.ReadWrite]`" |

**`https://api.preprod.powerplatform.com/.default` is the correct audience** (it gets past the 401 to a 403). But the public client app we're using (`51f81489-12ee-4a9e-aaae-a2591f45987d`, which is the Power Platform CLI / Dataverse delegated access app) **does not have the `Connectivity.Connections.Read` or `All.All.ReadWrite` delegated permissions** registered for the `api.preprod.powerplatform.com` resource.

When we tried requesting specific scopes like `https://api.preprod.powerplatform.com/Connectivity.Connections.ReadWrite`, MSAL opened a browser for interactive consent — but this requires an admin to consent to those permissions on the app, and the flow hung waiting for user interaction.

---

### Summary Table

| Approach | Base URL | Status | Blocker |
|---|---|---|---|
| BAP Admin API | `api.bap.microsoft.com` | 404 | Env not visible (Preprod ring) |
| PowerApps API | `api.powerapps.com` | 404 | Env not visible (Preprod ring) |
| Preprod BAP | `api.preprod.bap.microsoft.com` | DNS fail | Hostname doesn't exist |
| Preprod PowerApps | `api.preprod.powerapps.com` | DNS fail | Hostname doesn't exist |
| Tip1 PowerApps | `tip1.api.powerapps.com` | 410 | Decommissioned |
| Preprod PowerPlatform (old paths) | `api.preprod.powerplatform.com` with `/providers/...` | 404 RouteNotFound | Old path pattern not supported |
| **Preprod PowerPlatform (new paths)** | `api.preprod.powerplatform.com` with `/connectivity/...` | **403** | **Correct endpoint, wrong permissions on the client app** |
| PAC CLI `connection create` | N/A | N/A | Only supports Dataverse S2S (tenant-id + app-id + client-secret), not Workday SOAP connector |
| Browser automation | `make.preprod.powerapps.com` | Stuck on sign-in | MFA flow blocks headless automation |

---

### What Would Unblock This

**Option A: Use a first-party app ID that already has `Connectivity.Connections.ReadWrite`**
- Find the app ID that `make.preprod.powerapps.com` itself uses (we saw `60f38cf4-a0bf-4fdf-b0b5-14d3131bc031` in the login redirect). That app definitely has the right permissions. But we can't impersonate it without its secret.

**Option B: Register a custom Entra app with the right delegated permissions**
- Create an app registration in the Preprod tenant
- Add delegated permission `Connectivity.Connections.ReadWrite` (or `All.All.ReadWrite`) for resource `api.preprod.powerplatform.com`
- Grant admin consent
- Use that app's client ID in MSAL

**Option C: Find if PAC CLI has hidden/newer connection commands**
- `pac connection create` only does Dataverse S2S today. A newer PAC version might support connector-specific connections. Worth checking `pac connector` or `pac flow` subcommands, or a newer PAC CLI version.

**Option D: Use the Dataverse `connectionreferences` table directly**
- We CAN write to Dataverse (auth works). If we could discover the internal connection ID format and PATCH `connectionreferences({id})` with a `connectionid`, that might wire things up. But the chicken-and-egg problem is that the connection doesn't exist yet — we need to CREATE it first, and that requires the PowerApps/connectivity API.

**Option E: Use Power Automate Management connector or the Flow API**
- The Power Automate management API (`https://management.azure.com/providers/Microsoft.ProcessSimple/...` or similar) might expose connection creation. This is what the Azure Portal uses to manage Logic Apps connections.

**Option F: Script the browser properly**
- Use Playwright/Puppeteer outside VS Code's embedded browser (the embedded browser had viewport/MFA issues). A standalone Playwright script could handle the full sign-in + connection creation flow with proper waits.