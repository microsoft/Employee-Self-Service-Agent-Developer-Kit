# Test Run 5 — /provision end-to-end trace

**Date:** 2026-05-13
**Invocation:** `/provision` (no ISV argument — interactive)
**Outcome:** In progress

---

## Step 0: Load .env

**Action:** Read `.local/.env`
**Result:** File found. Parsed values (canonical keys):

| Canonical key | Source alias in .env |
|---------------|---------------------|
| WORKDAY_ENTRA_APP_ID_URI | `microsoft_entra_resource_url` |
| WORKDAY_OAUTH_TOKEN_URL | `oauth_token_url` |
| WORKDAY_OAUTH_CLIENT_ID | `oauth_client_id` |
| WORKDAY_BASE_URL | `soap_url` |
| WORKDAY_TENANT | `tenant` |

**Not found in .env:** PERSONA, ENV_URL, ENV_NAME, RING, ESS_PROVISION_CLIENT_ID

---

## Step 1: Pick persona

**Action:** Asked user via interactive picker (ENV.PERSONA not in .env)
**User chose:** ESS HR → PERSONA = `hr`

---

## Step 2: Pick ISV

**Action:** Asked user via interactive picker (no PRE_SELECTED_ISV from invocation)
**User chose:** Workday HCM → ISV = `workday`

---

## Step 3: Pick or create target environment

### 3 — Mode selection

**Action:** ENV.ENV_URL not in .env → asked user to choose create vs bind
**User chose:** Create a new env → MODE = `create`

### 3a-ring — Ring selection

**Action:** ENV.RING not in .env → asked user via picker
**User chose:** Preprod (PPE) → RING = `preprod`

### 3b — Env name

**Action:** ENV.ENV_NAME not in .env → asked user for a name
**User typed:** `provision2` → ENV_NAME = `provision2`

---

## Step 4: Initialize run state

**Action:** Created directory `my/provision/provision2/`
**Created:** `my/provision/provision2/config.json` with mode=create, ring=preprod, persona=hr, isv=workday
**Created:** `my/provision/provision2/tasks.md` (copied from `src/skills/provision/tasks.md`)

---

## Step 5: Run provisioning steps

### Step 5.1: step1.md — Environment creation & binding

#### Attempt 1: create_env.py --ring preprod --name provision2

**Command:**
```
python scripts/create_env.py --ring preprod --name provision2
```

**Exit code:** 1 (from the script, though `pac admin create` itself returned 0)
**Stderr:**
```
Creating env 'provision2' (type=Developer, ring=preprod)...
ERROR: pac admin create succeeded but env 'provision2' was not found in pac admin list.
This usually means the active pac auth profile is for a different ring than the one that
received the new env. Check 'pac auth list' and 'pac auth select --index <N>'.
```

**Root cause:** `pac admin create` returned **exit code 0** but printed:
```
Error: You have reached the limit of 3 developer environments for a user.
```

The script's error-handling was gated on `if rc != 0`, so it never caught the
error text. It proceeded to `_lookup_env_in_list("provision2")`, didn't find
the env (because it was never created), and reported the misleading
"not found in pac admin list" error.

**Diagnosis steps:**
1. Ran `pac auth list` — confirmed active profile is `[2]` gouthams@EmployeeHub.onmicrosoft.com on Preprod (correct ring)
2. Ran `pac admin list` — env `provision2` NOT in the list. User also confirmed from the PP Admin Center UI that the env was not created.
3. Ran `pac admin create --name provision2 --type Developer ...` directly — got the actual error: "You have reached the limit of 3 developer environments for a user."

#### Bug fix 1: create_env.py — check output text regardless of exit code

**File:** `scripts/create_env.py` — `create_env()` function

**Before:**
```python
if rc != 0:
    lower = combined.lower()
    if "capacity" in lower or "quota" in lower:
```

**After:**
```python
lower = combined.lower()
if rc != 0 or "error" in lower:
    if "capacity" in lower or "quota" in lower or "limit" in lower:
```

Also updated the docstring from "We trust rc=0 as success" to explain that
PAC sometimes returns rc=0 on failure.

#### Bug fix 2: step1.md — offer recovery options on exit code 2

**File:** `src/skills/provision/step1.md`

**Before:** Exit code 2 just said "show the stderr and stop."

**After:** If error mentions "limit" or "capacity", ask the user to choose:
- Retry as Sandbox (uses tenant capacity)
- Retry as Trial (free, expires in 30 days)
- Delete an existing env and retry
- Use an existing env (switch to bind mode)
- Cancel

#### Attempt 2: create_env.py --ring preprod --name provision2 --type Trial

**User chose:** Retry as Trial

**Command:**
```
python scripts/create_env.py --ring preprod --name provision2 --type Trial
```

**Exit code:** 0
**Stdout (JSON):**
```json
{
  "envUrl": "https://org701f0fa3.crm10.dynamics.com",
  "envId": "6194b6cc-8007-e799-9260-5ba7f542e23c",
  "organizationId": "94ed4c04-6b4e-f111-a817-6045bd052f9a",
  "envName": "provision2",
  "ring": "preprod"
}
```

**Result:** Environment created successfully. Updated `my/provision/provision2/config.json` with envUrl, envId, organizationId.

#### 1.3 — Authenticate and verify env is reachable

**Command:**
```
python scripts/whoami.py --env-url https://org701f0fa3.crm10.dynamics.com
```

**Exit code:** 0
**Stdout (JSON):**
```json
{
  "status": "ok",
  "userId": "ec2cb405-734b-f111-bec6-00224803e54d",
  "organizationId": "94ed4c04-6b4e-f111-a817-6045bd052f9a",
  "businessUnitId": "fa25b405-734b-f111-bec6-00224803e54d"
}
```

**Result:** Auth OK, Dataverse reachable.

#### 1.5 — Detect pre-existing ESS solutions

**Attempt 1 (failed):** Inline Python one-liner using `auth.authenticate()` + `requests.get()` to query:
```
GET {ENV_URL}/api/data/v9.2/solutions?$select=uniquename,version,ismanaged&$filter=startswith(uniquename,'msdyn_copilotforemployeeselfservice')...
```

PowerShell mangled the `$select` and `$filter` query param keys (interpreted
`$` as PS variable interpolation), resulting in empty param keys and a 400
Bad Request.

**Attempt 2 (success):** Created a temp script `my/provision/provision2/_check_solutions.py`
to avoid PS quoting issues.

**Command:**
```
python my/provision/provision2/_check_solutions.py
```

**Exit code:** 0
**Stdout:** `[]` (empty array — no pre-existing ESS solutions)

**Result:** Fresh environment. Saved `preExistingSolutions: []` to config.json.

#### 1.6 — Mark complete

Updated `tasks.md`: "Environment bound" → `[x]`

---

### Step 5.2: step2.md — Install ESS base persona pack

#### 2.2 — Resolve application name

PERSONA = `hr` → APP_NAME = `msdyn_CopilotForEmployeeSelfServiceHR`

#### 2.4 — Install via pac application install

**Command:**
```
pac application install --environment https://org701f0fa3.crm10.dynamics.com --application-name msdyn_CopilotForEmployeeSelfServiceHR
```

**Exit code:** 0
**Output:**
```
Connected as gouthams@EmployeeHub.onmicrosoft.com
Verifying if application(s) are already installed...
Installing 'msdyn_CopilotForEmployeeSelfServiceHR'...
Polling to check the status of your Application... Execution time: 00:00:30.3834406
Polling to check the status of your Application... Execution time: 00:01:00.8196187
Application successfully installed
Package Name                          Operation ID
msdyn_CopilotForEmployeeSelfServiceHR e5673686-e851-4615-ace6-1aace1d8eef9
```

**Result:** Installed successfully in ~1 minute.

#### Verify install via Dataverse query

**Command:**
```
python my/provision/provision2/_verify_ess.py
```

**Exit code:** 0
**Stdout:**
```json
[
  {
    "solutionid": "4107b61c-1e36-4c15-89d0-2198c055cbb9",
    "uniquename": "msdyn_CopilotForEmployeeSelfServiceHR",
    "ismanaged": true,
    "version": "1.1.0.2"
  }
]
```

**Result:** Confirmed in Dataverse. Updated config.json with `essBase` block. Marked "ESS base installed" → `[x]`.

---

### Step 5.3: step3-new.md — Workday ISV install + connection wiring

#### 3.4 — Pre-create Workday and Dataverse connections

**Attempt 1 (failed):**

**Command:**
```
python scripts/create_connection.py --env-id 6194b6cc-8007-e799-9260-5ba7f542e23c --env-url https://org701f0fa3.crm10.dynamics.com --ring preprod --connector shared_workdaysoap
```

**Exit code:** 1
**Stderr:**
```
ERROR: no client ID for the ESS Dev Kit custom Entra app.
Set ESS_PROVISION_CLIENT_ID in .local/.env, or pass --client-id.
See README for app registration steps.
```

**Root cause:** The `.env` file has `client_id=42222862-e2ae-4d1c-9be2-96dc1992f4da`
but the alias table in `scripts/pp_helpers.py` → `ENV_ALIASES["ESS_PROVISION_CLIENT_ID"]`
only accepts these aliases:
- `ESS_PROVISION_CLIENT_ID`
- `provision_client_id`
- `ess_devkit_client_id`

The bare key `client_id` is **not** in the alias list. This is arguably correct
(bare `client_id` is ambiguous — could be confused with `oauth_client_id` for
Workday), but it means the `.env` file as written doesn't match any accepted alias.

**Bug/gap identified:** Either:
1. Add `client_id` as an alias (risky — ambiguous with Workday's `oauth_client_id`)
2. Document that the .env key must be `provision_client_id` or `ess_provision_client_id`
3. Pass `--client-id` explicitly when the alias doesn't match

**Next action:** Updated `.env` to use canonical key names directly. Re-ran.

#### Fix: Updated .env to use canonical keys

**Before:**
```
microsoft_entra_resource_url=http://www.workday.com/microsoft_dpt6
oauth_token_url=https://wd2-impl-services1.workday.com/ccx/oauth2/microsoft_dpt6/token
oauth_client_id=OGM5ZmRhNDEtNTJhNS00YWUwLThjZWMtY2I1YzIzM2YzY2U3
soap_url=https://wd2-impl-services1.workday.com/ccx/service
Workday REST correct Endpoint=https://wd2-impl-services1.workday.com/ccx/api
tenant=microsoft_dpt6
client_id=42222862-e2ae-4d1c-9be2-96dc1992f4da
```

**After:**
```
WORKDAY_ENTRA_APP_ID_URI=http://www.workday.com/microsoft_dpt6
WORKDAY_OAUTH_TOKEN_URL=https://wd2-impl-services1.workday.com/ccx/oauth2/microsoft_dpt6/token
WORKDAY_OAUTH_CLIENT_ID=OGM5ZmRhNDEtNTJhNS00YWUwLThjZWMtY2I1YzIzM2YzY2U3
WORKDAY_BASE_URL=https://wd2-impl-services1.workday.com/ccx/service
WORKDAY_REST_URL=https://wd2-impl-services1.workday.com/ccx/api
WORKDAY_TENANT=microsoft_dpt6
ESS_PROVISION_CLIENT_ID=42222862-e2ae-4d1c-9be2-96dc1992f4da
```

Issues fixed: `client_id` → `ESS_PROVISION_CLIENT_ID`, `Workday REST correct Endpoint`
(spaces in key) → `WORKDAY_REST_URL`, all keys now match canonical names in code.

**Attempt 2 — Create Workday connection (success):**

**Command:**
```
python scripts/create_connection.py --env-id 6194b6cc-8007-e799-9260-5ba7f542e23c --env-url https://org701f0fa3.crm10.dynamics.com --ring preprod --connector shared_workdaysoap
```

First run prompted for device-code sign-in (Power Platform API scope, separate from
PAC CLI and Dataverse auth). User completed sign-in at https://login.microsoft.com/device.

**Exit code:** 0
**Result:**
```json
{
  "connectionId": "6a4345763b1c4244828ad811ca91194d",
  "connector": "shared_workdaysoap",
  "displayName": "workday_oauth_20260513_120056",
  "status": "Error",
  "statusTarget": "token"
}
```

Status `Error` / `Unauthenticated` is expected — the OAuth handshake (Entra SAML →
Workday) requires a browser click in the maker portal.

**Create Dataverse connection (success):**

**Command:**
```
python scripts/create_connection.py --env-id 6194b6cc-8007-e799-9260-5ba7f542e23c --env-url https://org701f0fa3.crm10.dynamics.com --ring preprod --connector shared_commondataserviceforapps
```

**Exit code:** 0
**Result:**
```json
{
  "connectionId": "36900dd1e3334f6cad5553dbcc662de5",
  "connector": "shared_commondataserviceforapps",
  "displayName": "dataverse_oauth_20260513_120601",
  "status": "Error",
  "statusTarget": "token"
}
```

Both connections saved to config.json.

#### 3.5 — User signs in to connections (parallel with install)

Directed user to https://make.preprod.powerapps.com/connections to sign in
to both connections while the ISV installs.

#### 3.6 — Install Workday ISV via pac application install

**Command:**
```
pac application install --environment https://org701f0fa3.crm10.dynamics.com --application-name msdyn_EssHRWorkday
```

**Exit code:** 0
**Output:**
```
Connected as gouthams@EmployeeHub.onmicrosoft.com
Verifying if application(s) are already installed...
Installing 'msdyn_EssHRWorkday'...
Polling to check the status of your Application... Execution time: 00:00:30.3942899
Polling to check the status of your Application... Execution time: 00:01:00.7781479
Polling to check the status of your Application... Execution time: 00:01:31.1479567
Polling to check the status of your Application... Execution time: 00:02:01.5385889
Application successfully installed
Package Name       Operation ID
msdyn_EssHRWorkday c876853c-01bd-4341-869c-2000951a3dc8
```

**Result:** Installed successfully in ~2 minutes.

#### Verify ISV install via Dataverse query

**Command:**
```
python my/provision/provision2/_verify_isv.py
```

**Exit code:** 0
**Stdout:**
```json
[
  {
    "solutionid": "378ad4fd-6f3d-4e2a-a7f6-6ceeafa119c9",
    "uniquename": "msdyn_EssHRWorkday",
    "ismanaged": true,
    "version": "1.1.0.2"
  }
]
```

Updated config.json with `isvSolution` block. Marked "ISV imported" → `[x]`.

#### 3.7 — Verify both connections are active

**Attempt 1 (failed):** Called Connectivity API GET without `$filter` param.
```
GET https://{per-env-host}/connectivity/connectors/shared_workdaysoap/connections/{id}?api-version=1
```
→ 400: `MissingEnvironmentFilter: The environment filter must be set.`

**Attempt 2 (success):** Added `$filter=environment eq '{env_id}'` as query param.

**Result:**
- Workday connection: `Connected`
- Dataverse connection: `Connected`

**Learning:** The per-env connectivity API GET endpoint requires `$filter=environment eq '{env_id}'`
even though the host is already per-env. The PUT (create) does not require this because the
environment is in the request body.

Marked "Connections active" → `[x]`.

#### 3.8 — Bind connection references

**Command:**
```
python scripts/bind_connection_refs.py \
    --env-id 6194b6cc-8007-e799-9260-5ba7f542e23c \
    --env-url https://org701f0fa3.crm10.dynamics.com \
    --workday-connection 6a4345763b1c4244828ad811ca91194d \
    --dataverse-connection 36900dd1e3334f6cad5553dbcc662de5
```

**Exit code:** 1 (partial success)
**Result:**
```json
{
  "totalRefsInEnv": 1,
  "bindings": [
    {
      "purpose": "workday",
      "refLogicalName": "new_sharedworkdaysoap_ff0df",
      "connectionId": "6a4345763b1c4244828ad811ca91194d",
      "status": "bound"
    }
  ],
  "failures": [
    {
      "purpose": "dataverse",
      "connectionId": "36900dd1e3334f6cad5553dbcc662de5",
      "reason": "no connection refs found matching connector(s): {'shared_commondataserviceforapps', 'shared_commondataservice'}"
    }
  ]
}
```

**Analysis:** Only 1 connection reference exists in the env (`new_sharedworkdaysoap_ff0df`
for Workday). There is no Dataverse connection reference in the Workday ISV solution —
Dataverse is used internally by CPS flows without a solution-level connection ref.
The Workday binding succeeded. The Dataverse "failure" is expected/harmless.

**Exit code 1 is misleading** — the script treats any failure as non-zero even when all
existing refs are bound. This could be improved (exit 0 if all existing refs are bound,
even if a requested connector has no refs).

Marked "Connection refs bound" → `[x]`.

#### 3.9 — Wire flow runtime connections

**Command:**
```
python scripts/wire_flow_bindings.py \
    --env-id 6194b6cc-8007-e799-9260-5ba7f542e23c \
    --env-url https://org701f0fa3.crm10.dynamics.com \
    --ring preprod \
    --persona hr \
    --workday-connection 6a4345763b1c4244828ad811ca91194d
```

**Exit code:** 1 (flow enable succeeded, flow binding failed)

**Result — flow enables (success):**
```json
{
  "flowEnables": [
    {"name": "ESS HR Workday", "action": "enabled"},
    {"name": "WorkdayRESTExecution", "action": "enabled"}
  ]
}
```

**Result — flow bindings (FAILED):**
Both flows returned HTTP 403:
```json
{
  "code": "Forbidden",
  "message": "The caller is not authorized to perform the request.",
  "innererror": {
    "code": "InsufficientDelegatedPermissions",
    "message": "Authorization denied: Application missing required delegated permissions: [PowerVirtualAgents.Tokens.Read, All.All.ReadWrite]"
  }
}
```

**Root cause:** The custom Entra app (`42222862-e2ae-4d1c-9be2-96dc1992f4da`) does
not have the required delegated permissions for the Copilot Studio / PVA API:
- `PowerVirtualAgents.Tokens.Read`
- `All.All.ReadWrite`

These permissions need to be added to the app registration in Entra ID (Azure portal
→ App registrations → ESS Dev Kit app → API permissions → Add a permission →
APIs my organization uses → search "Power Virtual Agents" or "Microsoft Copilot Studio").

**Status:** BLOCKED. User needs to add delegated permissions to the Entra app registration.

#### 3.9 — Investigation: what permissions are available?

**Approach 1 — Azure CLI (`az ad sp list`):**
```
az ad sp list --filter "displayName eq 'Power Platform API - Test'" ...
```
→ Failed: `az` not installed on this machine.

**Approach 2 — Microsoft Graph API via MSAL device-code:**

Created `_find_permissions.py` to query Graph for the "Power Platform API - Test"
service principal's `oauth2PermissionScopes`. Required device-code sign-in to Graph
(code: `F9PQ2UD87`).

Timed out on first attempt (120s) because user was still signing in.
Second attempt was cancelled (terminal killed) before completing.

**Approach 3 — User listed permissions from Azure Portal:**

User shared all 62 permissions currently granted on the Entra app:
- **Power Platform API - Test**: 38 delegated permissions (AiFlows.*, Authorization.*, Connectivity.*, CopilotStudio.*, EnvironmentManagement.*, MCPServer.*, PowerApps.*, PowerAutomate.*)
- **Power Platform API (prod)**: 20 delegated permissions (subset of above)
- **Connectors**: webhook.readwrite.all
- **Copilot SSO**: WorkdayApp.Copilot.SSO
- **Microsoft Graph**: User.Read
- **Power Platform Environment Service**: User
- **PowerPlatform-WorkdaySOAP-Connector**: ConnectorsAuth

**Key finding:** Neither `PowerVirtualAgents.Tokens.Read` nor `All.All.ReadWrite`
exist in the current "Power Platform API - Test" permission catalog. These appear to
be **legacy PVA-era permission names** that were never migrated to the consolidated
Power Platform API resource. The user searched for "Power Virtual Agents" in
"APIs my organization uses" and could not find it.

#### 3.9 — Retry after user added more permissions

User added additional permissions to the app. Cleared the MSAL token cache:
```
Remove-Item ".local\.token_cache_42222862.bin" -Force
```

**Attempt 2 — wire_flow_bindings.py (first try with fresh cache):**

Script prompted for device-code sign-in (code: `B9RXNYALA`). Script exited before
token acquisition completed (the device-code flow timed out internally).

**JWT decode of fresh token:**

Created `_decode_token.py` to acquire a new token and decode it. Required another
device-code sign-in (code: `EF75QTWNN`).

**Token claims:**
```
aud: https://api.preprod.powerplatform.com
app: 42222862-e2ae-4d1c-9be2-96dc1992f4da
upn: gouthams@EmployeeHub.onmicrosoft.com

scp (37 permissions):
  AiFlows.Ai.Execute, AiFlows.Ai.Read, AiFlows.Ai.Write,
  AiFlows.Connections.Read, AiFlows.Runs.Execute, AiFlows.Runs.Read,
  AiFlows.Runs.Write, AiFlows.Workflows.Execute, AiFlows.Workflows.Read,
  AiFlows.Workflows.Write, AiTools.Prompt.Invoke, AiTools.Prompt.Read,
  AiTools.Prompt.Write, Authorization.RoleAssignments.Read,
  Authorization.RoleAssignments.Write, Connectivity.Connections.Read,
  Connectivity.Connections.Write, Connectivity.Connectors.Read,
  CopilotStudio.AdminActions.Invoke, CopilotStudio.AgentNodes.Invoke,
  CopilotStudio.Copilots.Invoke, CopilotStudio.Licenses.Read,
  CopilotStudio.MakerOperations.Delete, CopilotStudio.MakerOperations.Read,
  CopilotStudio.MakerOperations.ReadWrite, CopilotStudio.MinimalBot.Read,
  CopilotStudio.MinimalBot.ReadWrite, EnvironmentManagement.Environments.Read,
  EnvironmentManagement.Groups.Read, EnvironmentManagement.Groups.ReadWrite,
  EnvironmentManagement.Settings.Read, EnvironmentManagement.Settings.ReadWrite,
  MCPServer.Tools.Execute, PowerApps.Apps.Play, PowerApps.Apps.Read,
  PowerAutomate.Flows.Read, PowerAutomate.Flows.Write
```

**Confirmed:** Token has 37 delegated permissions but **NOT** the two required:
`PowerVirtualAgents.Tokens.Read` and `All.All.ReadWrite`.

**Attempt 3 — wire_flow_bindings.py (with new CopilotStudio.* permissions):**

**Command:**
```
python scripts/wire_flow_bindings.py \
    --env-id 6194b6cc-8007-e799-9260-5ba7f542e23c \
    --env-url https://org701f0fa3.crm10.dynamics.com \
    --ring preprod \
    --persona hr \
    --workday-connection 6a4345763b1c4244828ad811ca91194d
```

**Exit code:** 1
**Result:** Same 403 error — still demands `PowerVirtualAgents.Tokens.Read` and
`All.All.ReadWrite`. The new `CopilotStudio.MakerOperations.ReadWrite` permission
does **not** satisfy this endpoint.

**Conclusion:** The `/powervirtualagents/bots/{bot}/channels/pva-studio/user-connections`
endpoint requires legacy permission names that no longer exist in the Power Platform
API permission catalog. This is a **platform-side gap** — the endpoint's permission
check references permissions that cannot be granted through the current Entra portal.

**Workaround options:**
1. **Manual wiring in Copilot Studio portal** — open the agent in CPS, go to Actions,
   connect each flow to the Workday connection manually (4 clicks per flow)
2. **Use a first-party app ID** that already has the legacy permissions baked in
3. **File a platform bug** — the `user-connections` endpoint should accept the
   modern `CopilotStudio.MakerOperations.ReadWrite` permission

**Decision:** Proceed with manual wiring. Step 3.9 marked as requiring manual action.

#### 3.9 — Additional retry attempts after user modified Entra app permissions

**Context:** User went to Azure Portal and added many more permissions to the
custom Entra app (`42222862-...`). In the process, a `CopilotStudio.Copilots.Invoke`
**Application** permission (`"type": "Role"`) was added alongside the existing
Delegated version. This broke the device-code flow.

**Attempt 4 — wire_flow_bindings.py (default CPS first-party app, after cache clear):**

```
Remove-Item ".local\.token_cache_42222862.bin" -Force
python scripts/wire_flow_bindings.py --env-id ... --persona hr --workday-connection ...
```

**Exit code:** 1
**Error:** `AADSTS7000218: The request body must contain 'client_assertion' or 'client_secret'`

**Analysis:** The script defaults to `CPS_FIRST_PARTY_APP_ID = a522f059-bb65-47c0-8934-7db6e5286414`
(Copilot Studio's first-party app). This app was returning `invalid_client`, suggesting
it has been reconfigured server-side as a confidential client (or tenant policy blocks
device-code for first-party apps in preprod).

**Attempt 5 — wire_flow_bindings.py with custom app `--client-id 42222862-...`:**

Same device-code error: `AADSTS7000218`.

**Root cause identified:** User had added `CopilotStudio.Copilots.Invoke` as an
**Application** permission (type=Role) in the Entra app manifest:
```json
{
    "id": "b104e8ac-114c-4085-8e71-3ba6ef39d091",
    "type": "Role"  // <-- Application permission, not Delegated
}
```

When Entra sees an Application permission (Role) on an app registration, it forces
confidential-client mode (requires `client_secret` or `client_assertion`) regardless
of the `isFallbackPublicClient: true` setting. The device-code flow (which is a
public-client flow) then fails with AADSTS7000218.

**Fix attempted:** Asked user to remove the Application permission. User accidentally
removed the wrong one initially, then attempted to fix it.

**Attempt 6 — Cleared ALL token caches, retried with CPS first-party app:**

```
Remove-Item ".local\.token_cache_*.bin" -Force
python scripts/wire_flow_bindings.py --env-id ... --persona hr --workday-connection ...
```

**Exit code:** 1
**Error:** Same `AADSTS7000218` on the CPS first-party app (`a522f059-...`).

**Key insight:** The AADSTS7000218 is on the **CPS first-party app**, not the user's
custom app. This is a server-side issue — the CPS first-party app itself may have been
reconfigured in the preprod ring, or the tenant blocks device-code for first-party apps.
This is outside the user's control.

**Attempt 7 — Cleared ALL caches, retried with custom app `--client-id 42222862-...`:**

```
Remove-Item ".local\.token_cache_*.bin" -Force
python scripts/wire_flow_bindings.py --env-id ... --persona hr \
    --workday-connection ... --client-id 42222862-e2ae-4d1c-9be2-96dc1992f4da
```

**Exit code:** 1
**Token acquisition:** ✅ Succeeded! Device-code sign-in worked (the Application
permission removal fixed the custom app).
**Flow binding:** ❌ Same 403:
```json
{
  "code": "Forbidden",
  "innererror": {
    "code": "InsufficientDelegatedPermissions",
    "message": "Authorization denied: Application missing required delegated permissions: [PowerVirtualAgents.Tokens.Read, All.All.ReadWrite]"
  }
}
```

**Final conclusion on 3.9:**

| App tried | Token acquisition | Flow binding |
|-----------|-------------------|-------------|
| CPS first-party (`a522f059-...`) | ❌ AADSTS7000218 (confidential client error) | N/A |
| Custom app (`42222862-...`) with Application perm | ❌ AADSTS7000218 | N/A |
| Custom app (`42222862-...`) without Application perm | ✅ Works | ❌ 403 — missing `PowerVirtualAgents.Tokens.Read`, `All.All.ReadWrite` |

The `user-connections` endpoint is **not automatable in preprod** with any available
app registration:
- The CPS first-party app that should have the legacy permissions is broken (AADSTS7000218)
- Custom apps can authenticate but lack the required legacy permission names
- The permissions `PowerVirtualAgents.Tokens.Read` and `All.All.ReadWrite` do not exist
  in the Power Platform API - Test (preprod) permission catalog

**Resolution:** Manual flow wiring in Copilot Studio portal is required.

#### 3.10 — Update User Context Setup topic (success)

**Command:**
```
python scripts/update_user_context_topic.py --env-url https://org701f0fa3.crm10.dynamics.com --persona hr
```

**Exit code:** 0
**Output:**
```json
{
  "action": "patched",
  "topic": {
    "botcomponentid": "553319c3-6b49-48a1-93c8-d2194e079a9a",
    "name": "[Admin] - User Context - Setup",
    "schemaname": "msdyn_copilotforemployeeselfservicehr.topic.Setusercontext",
    "previousContent": "kind: AdaptiveDialog\r\nbeginDialog:\r\n  kind: OnRedirect\r\n  id: main\r\n  priority: 0"
  },
  "newContent": "kind: AdaptiveDialog\nbeginDialog:\n  kind: OnRedirect\n  id: main\n  priority: 0\n  actions:\n    - kind: BeginDialog\n      id: QVk2yi\n      dialog: msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemGetUserContextV2\n",
  "httpStatus": 204
}
```

**Result:** Topic patched to redirect to `WorkdaySystemGetUserContextV2`. Marked
"User Context Setup topic configured" → `[x]`.

---

## Current status

| Task | Status |
|------|--------|
| Environment bound | ✅ provision2 (Trial, preprod) |
| ESS base installed | ✅ msdyn_CopilotForEmployeeSelfServiceHR v1.1.0.2 |
| ISV imported | ✅ msdyn_EssHRWorkday v1.1.0.2 |
| Connections active | ✅ Workday + Dataverse both Connected |
| Connection refs bound | ✅ new_sharedworkdaysoap_ff0df → bound |
| Flow runtime connections wired | ❌ BLOCKED — requires manual CPS portal wiring |
| User Context Setup topic configured | ✅ Patched to WorkdaySystemGetUserContextV2 |
| Health check passed | ⏳ Pending (awaiting 3.9 manual completion) |

## Pending steps

- [ ] 3.9 — Wire flow runtime connections MANUALLY in Copilot Studio portal:
  1. Open https://copilotstudio.preview.microsoft.com
  2. Switch to **provision2** environment
  3. Open **Employee Self-Service HR** agent → **Actions**
  4. **ESS HR Workday** → Connect → select **workday_oauth_20260513_120056**
  5. **WorkdayRESTExecution** → Connect → select same Workday connection
- [ ] step4.md — Validate via `/flightcheck --scope provision`
- [ ] Step 6 — Mark provisioning complete

---

## Summary of bugs/gaps found

| # | Issue | File(s) affected | Fix applied? |
|---|-------|-------------------|-------------|
| 1 | `pac admin create` returns exit 0 on failure (env limit) | `scripts/create_env.py` | ✅ Now checks output text regardless of exit code |
| 2 | step1.md exit-code-2 handler just stops instead of offering recovery | `src/skills/provision/step1.md` | ✅ Added Sandbox/Trial/delete/bind options |
| 3 | `.env` key `client_id` not in alias list for `ESS_PROVISION_CLIENT_ID` | `.local/.env`, `scripts/pp_helpers.py` | ✅ Workaround — renamed key in .env to canonical form |
| 4 | `.env` key `Workday REST correct Endpoint` has spaces (unparseable) | `.local/.env` | ✅ Renamed to `WORKDAY_REST_URL` |
| 5 | Connectivity API GET requires `$filter=environment` even on per-env host | step3-new.md instructions | ❌ Not yet fixed in docs |
| 6 | `bind_connection_refs.py` exits 1 when requested connector has no refs | `scripts/bind_connection_refs.py` | ❌ Not yet fixed (exit code misleading) |
| 7 | `user-connections` API requires legacy PVA permissions not in PP API catalog | `scripts/wire_flow_bindings.py` | ❌ Platform-side gap — permissions don't exist in catalog |
| 8 | PowerShell `$` variable interpolation breaks inline Python with `$select`/`$filter` | Agent execution pattern | ✅ Workaround — use temp .py script files instead of inline one-liners |
| 9 | Device-code sign-in: 3 separate auth contexts required (PAC CLI, Dataverse/MSAL, PP API/MSAL) | UX friction | Informational — not a bug, but users hit 3+ sign-in prompts |
| 10 | CPS first-party app (`a522f059-...`) returns AADSTS7000218 in preprod | `scripts/wire_flow_bindings.py` | ❌ Server-side issue — app may be reconfigured as confidential client in preprod |
| 11 | Adding Application (Role) permission to Entra app breaks device-code flow | Entra app config | ✅ User removed the Role permission to restore public-client behavior |

---

## Auth flow summary (for reference)

| Step | Auth method | App ID | Scope/Resource | Cache file |
|------|------------|--------|----------------|------------|
| PAC CLI (create env, install apps) | `pac auth` device-code | PAC CLI built-in | Power Platform Admin | PAC internal |
| Dataverse (whoami, solutions, workflows) | MSAL interactive browser | `51f81489-...` (PAC CLI) | `{env_url}/.default` | `.local/.token_cache.bin` |
| PP Connectivity API (create connection) | MSAL device-code | `42222862-...` (custom) | `https://api.preprod.powerplatform.com/.default` | `.local/.token_cache_42222862.bin` |
| PVA user-connections API (flow binding) | MSAL device-code | `a522f059-...` (CPS 1P) or custom | `https://api.preprod.powerplatform.com/.default` | `.local/.token_cache_a522f059.bin` |
