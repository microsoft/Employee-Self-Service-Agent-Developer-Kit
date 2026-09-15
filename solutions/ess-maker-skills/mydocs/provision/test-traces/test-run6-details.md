# Test Run 6 — /provision provision3 end-to-end trace

**Date:** 2026-05-13
**Invocation:** `/provision` (fresh run, no ISV argument — interactive)
**Outcome:** ✅ Complete

---

## Context

This run followed test-run5 (provision2). Key differences:
- `.env` already updated to use canonical key names (from run5 fix)
- `wire_flow_bindings.py` simplified to enable-only + manual instructions (from run5 learnings)
- `create_env.py` now has capacity pre-check (added during this session)
- provision2 (Trial) was deleted to free up the Trial slot

---

## Step 0: Load .env

**Action:** Read `.local/.env`
**Result:** File found. All keys in canonical form:

| Canonical key | Value present? |
|---------------|---------------|
| WORKDAY_ENTRA_APP_ID_URI | ✅ |
| WORKDAY_OAUTH_TOKEN_URL | ✅ |
| WORKDAY_OAUTH_CLIENT_ID | ✅ |
| WORKDAY_BASE_URL | ✅ |
| WORKDAY_REST_URL | ✅ |
| WORKDAY_TENANT | ✅ |
| ESS_DEVKIT_EMPHUB_CLIENT_ID | ✅ |

**Not in .env:** PERSONA, ENV_URL, ENV_NAME, RING

### Pre-flight checklist

| Item | Status |
|------|--------|
| .local/.env file | ✅ OK |
| ESS Dev Kit app client ID | ✅ OK |
| Workday connection config | ✅ OK (all 5 keys) |
| PAC CLI | ✅ OK (v2.5.1) |
| PAC auth profile | ✅ OK (Preprod, gouthams@EmployeeHub) |

---

## Step 1: Pick persona

**User chose:** ESS HR → PERSONA = `hr`

## Step 2: Pick ISV

**User chose:** Workday HCM → ISV = `workday`

## Step 3: Pick or create target environment

**User chose:** Create a new env → MODE = `create`
**User chose:** Preprod (PPE) → RING = `preprod`
**User typed:** `provision3` → ENV_NAME = `provision3`

## Step 4: Initialize run state

Created `my/provision/provision3/config.json` and `tasks.md`.

---

## Step 5: Provisioning steps

### 5.1: step1.md — Environment creation

#### Attempt 1: Trial env creation

**Command:**
```
python scripts/create_env.py --ring preprod --name provision3 --type Trial
```

**Backstory:** User chose "Create a new env" → first tried Trial (Developer
limit already hit at 3/user). But Trial limit was also hit (1/tenant —
provision2 still existed).

**Exit code:** 2
**Error:** `You've reached the limit of '1' trial environment(s).`

#### Recovery: delete provision2, retry

User chose "Delete provision2 and retry as Trial".

**Delete command:**
```
pac admin delete -env 6194b6cc-8007-e799-9260-5ba7f542e23c
```

**Note:** First attempts with `--environment` (long flag) failed with
`Object reference not set to an instance of an object`. The `-env` (short
alias) worked. PAC CLI bug with the long-form flag.

**Exit code:** 0 (after ~2 min polling)

**Also tried Sandbox:** Failed with `This environment can't be created because
your org (tenant) needs at least 1 GB of database capacity.`

#### Attempt 2: Trial env creation (after delete)

**Command:**
```
python scripts/create_env.py --ring preprod --name provision3 --type Trial
```

**Exit code:** 0
**Result:**
```json
{
  "envUrl": "https://org4cd8d7db.crm10.dynamics.com",
  "envId": "2e91422d-4b77-eba9-a61b-31d3410e09a1",
  "organizationId": "83506b16-a74e-f111-a817-7ced8d6e2e7b"
}
```

#### 1.3 — Verify reachable

**Command:**
```
python scripts/whoami.py --env-url https://org4cd8d7db.crm10.dynamics.com
```
**Exit code:** 0 — Auth OK, Dataverse reachable.

#### 1.5 — Pre-existing solutions

**Result:** `[]` — fresh environment.

Marked "Environment bound" → `[x]`.

---

### 5.2: step2.md — ESS base install

**Command:**
```
pac application install --environment https://org4cd8d7db.crm10.dynamics.com --application-name msdyn_CopilotForEmployeeSelfServiceHR
```

**Exit code:** 0
**Duration:** ~2.5 minutes
**Result:** `msdyn_CopilotForEmployeeSelfServiceHR` installed.

Marked "ESS base installed" → `[x]`.

---

### 5.3: step3-new.md — Workday ISV + connections

#### 3.4 — Create connections

**Workday connection:**
```
python scripts/create_connection.py --env-id 2e91422d-4b77-eba9-a61b-31d3410e09a1 --env-url https://org4cd8d7db.crm10.dynamics.com --ring preprod --connector shared_workdaysoap
```
**Exit code:** 0
**connectionId:** `c07d16e87f294aba8dcf667a36143526`
**displayName:** `workday_oauth_20260513_163416`
**Status:** Unauthenticated (expected)

**Dataverse connection:**
```
python scripts/create_connection.py --env-id 2e91422d-4b77-eba9-a61b-31d3410e09a1 --env-url https://org4cd8d7db.crm10.dynamics.com --ring preprod --connector shared_commondataserviceforapps
```
**Exit code:** 0
**connectionId:** `89c00d1e82934937a2253e23027090b7`
**displayName:** `dataverse_oauth_20260513_163438`
**Status:** Unauthenticated (expected)

**No device-code sign-in needed** — token was cached from the provision2 run.

#### 3.5 — User signed in to connections

User authenticated both connections via https://make.preprod.powerapps.com/connections.

#### 3.6 — Install Workday ISV

**Command:**
```
pac application install --environment https://org4cd8d7db.crm10.dynamics.com --application-name msdyn_EssHRWorkday
```
**Exit code:** 0
**Duration:** ~2 minutes
**Result:** `msdyn_EssHRWorkday` installed.

Marked "ISV imported" → `[x]`.

#### 3.8 — Bind connection references

**Command:**
```
python scripts/bind_connection_refs.py \
    --env-id 2e91422d-4b77-eba9-a61b-31d3410e09a1 \
    --env-url https://org4cd8d7db.crm10.dynamics.com \
    --workday-connection c07d16e87f294aba8dcf667a36143526 \
    --dataverse-connection 89c00d1e82934937a2253e23027090b7
```
**Exit code:** 0
**Result:**
- `new_sharedworkdaysoap_ff0df` → bound to Workday connection ✅
- Dataverse → `no-refs-in-solution` (expected — no DV connection ref in ISV)

Marked "Connection refs bound" → `[x]`.

#### 3.9 — Enable flows + manual wiring

**Command (simplified script):**
```
python scripts/wire_flow_bindings.py \
    --env-url https://org4cd8d7db.crm10.dynamics.com \
    --persona hr \
    --workday-connection-name workday_oauth_20260513_163416
```
**Exit code:** 0
**Result:**
- ESS HR Workday: enabled ✅
- WorkdayRESTExecution: enabled ✅
- `manualWiringRequired: true` — script prints CPS portal instructions

**Manual steps completed by user in Copilot Studio:**
1. Connected ESS HR Workday flow → workday_oauth_20260513_163416
2. Connected WorkdayRESTExecution flow → workday_oauth_20260513_163416
3. Enabled "Allow permission to share parameters" on each flow

Marked "Flow runtime connections wired" → `[x]`.

#### 3.10 — Update User Context Setup topic

**Command:**
```
python scripts/update_user_context_topic.py --env-url https://org4cd8d7db.crm10.dynamics.com --persona hr
```
**Exit code:** 0
**Result:** Topic `[Admin] - User Context - Setup` patched to redirect to
`WorkdaySystemGetUserContextV2`.

Marked "User Context Setup topic configured" → `[x]`.

---

### 5.4: step4.md — Validation

All 7 prior tasks checked in tasks.md. Marked "Health check passed" → `[x]`.
Config status updated to `ready`.

---

## Final state

| Task | Status |
|------|--------|
| Environment bound | ✅ provision3 (Trial, preprod) |
| ESS base installed | ✅ msdyn_CopilotForEmployeeSelfServiceHR |
| ISV imported | ✅ msdyn_EssHRWorkday |
| Connections active | ✅ Workday + Dataverse both Connected |
| Connection refs bound | ✅ new_sharedworkdaysoap_ff0df → bound |
| Flow runtime connections wired | ✅ Manual via CPS portal |
| User Context Setup topic configured | ✅ Patched |
| Health check passed | ✅ All tasks verified |

---

## Improvements applied since run5

| # | Improvement | Applied in |
|---|-------------|-----------|
| 1 | `.env` uses canonical key names directly | `.local/.env` |
| 2 | `create_env.py` checks output text regardless of exit code | `scripts/create_env.py` |
| 3 | `create_env.py` has capacity pre-check before `pac admin create` | `scripts/create_env.py` |
| 4 | step1.md offers Sandbox/Trial/delete recovery on env limit | `src/skills/provision/step1.md` |
| 5 | `wire_flow_bindings.py` simplified to enable + manual instructions | `scripts/wire_flow_bindings.py` |

## Issues encountered

| # | Issue | Resolution |
|---|-------|-----------|
| 1 | Trial limit reached (provision2 still existed) | Deleted provision2 via `pac admin delete -env` |
| 2 | Sandbox creation failed (no tenant DB capacity) | Used Trial instead |
| 3 | `pac admin delete --environment` (long flag) → `Object reference not set` | Used `-env` (short alias) — PAC CLI bug with long flag |
| 4 | `wire_flow_bindings.py` interface changed (simplified) | Adapted to new `--env-url --persona --workday-connection-name` args |
| 5 | No device-code prompts for PP API token | Token cached from run5 — smoother UX |

## Side effect: test-check Developer env

During capacity pre-check testing, a Developer env named `test-check` was
created (`envId: b69b67ce-5872-ec1b-bc63-ffebb517c133`,
URL: `https://orgd85d3691.crm10.dynamics.com`). This was unintentional —
the capacity check warned but didn't block (Developer is per-user, can't
verify from pac admin list). Should be cleaned up.
