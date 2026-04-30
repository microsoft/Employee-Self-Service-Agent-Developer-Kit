# ESS FlightCheck — Permissions Required

FlightCheck queries three API surfaces. Each requires specific permissions.

---

## 1. Microsoft Graph (read-only)

Used for: license checks, role assignments, Entra ID, Conditional Access, user sync.

| Scope | Used by | Type |
|-------|---------|------|
| `Organization.Read.All` | AUTH-001 (Entra org) | Delegated |
| `Directory.Read.All` | PRE-008/009 (role members) | Delegated |
| `User.Read.All` | AUTH-004 (user sync sample) | Delegated |
| `Policy.Read.All` | AUTH-002 (CA policies) | Delegated |

These scopes are requested during the interactive browser sign-in. No admin
consent is required for delegated access if the user has the appropriate
admin role (Global Admin or Global Reader).

**If the user lacks permissions**: Affected checks return Warning status with
"Unable to check" instead of blocking. Other categories proceed normally.

---

## 2. Power Platform Admin API (BAP)

Used for: environment details, flow inventory, connection status, DLP policies.

**Requires**: Power Platform Administrator or Dynamics 365 Admin role.

| API | Used by |
|-----|---------|
| `GET /environments/{id}` | ENV-001, ENV-002, ENV-003 |
| `GET /environments/{id}/v2/flows` | External systems discovery, flow status |
| `GET /environments/{id}/connections` | WD-CONN-xxx |
| `GET /apiPolicies` | ENV-008 (DLP) |

Authentication uses the same MSAL client as Dataverse (`auth.py`), with
the scope `https://service.powerapps.com//.default`.

**If the user lacks PP Admin role**: Environment and flow checks return
Warning status. The check doesn't block; it just can't validate those items.

---

## 3. Dataverse REST API

Used for: environment variable values, template config inventory.

**Requires**: System Administrator or System Customizer role in the
environment (same as what `/setup` requires).

Uses the existing `auth.py` token — no additional sign-in needed.

---

## 4. Workday SOAP API (optional)

Used for: the 17 workflow tests (WD-WF-001 through WD-WF-017).

**Requires**: Workday ISU credentials. FlightCheck resolves these automatically:

1. **Environment variables** — if already set (e.g., from a CI pipeline)
2. **`.vscode/mcp.json`** — base URL and tenant are read directly (they're
   not secrets). Username/password use `${input:...}` so they can't be read.
3. **`my/config.json`** → `connections.Workday` — tenant and base URL from
   the `/connect workday` setup
4. **Interactive prompt** — if creds still missing, prompts for ISU username
   and password at runtime. **Never saved to disk.**
5. **`my/config.json`** → `workdayTestEmployeeId` — cached after first prompt
   so you only enter it once

Environment variables needed (if not auto-resolved):
- `WORKDAY_BASE_URL` — SOAP base URL
- `WORKDAY_TENANT` — Workday tenant name
- `WORKDAY_USERNAME` — ISU account username
- `WORKDAY_PASSWORD` — ISU account password
- `WORKDAY_TEST_EMPLOYEE_ID` — Employee ID for test queries

**If not configured**: SOAP workflow checks are skipped with a clear
message. Other Workday checks (env vars, connections, flows) still run.

---

## Graceful Degradation

FlightCheck is designed to run with whatever permissions are available:

| Missing | Impact |
|---------|--------|
| No Graph permissions | Prerequisites + Auth checks show Warning |
| No PP Admin role | Environment + flow checks show Warning |
| No Workday creds | SOAP workflow tests skipped |
| No agent files | Local file checks skipped |

The CLI still exits with code 0 (success) unless automated checks
produce actual Failed results. Warnings and skipped checks don't
affect the exit code.
