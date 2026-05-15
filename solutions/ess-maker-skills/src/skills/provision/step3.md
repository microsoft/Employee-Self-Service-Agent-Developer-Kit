# Provision Step 3 (New): Workday ISV Install + Parallel Connection Setup

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**This is the simplified post-auth-simplification path.** It assumes the
Workday extension uses delegated OAuth (signed-in user's identity flows
to Workday at runtime). The legacy ISU + SAML path is still required for
existing customer environments and lives separately under
`src/skills/connect/workday/step3.md`. Do not conflate the two.

This step parallelizes Workday ISV install with the OAuth handshake for the
two connections. The connections are created up-front (instantly), then
the install runs while the user signs in to both connections in the maker
portal. By the time the install finishes, both connections are typically
Connected and we auto-bind them to the connection references the install
just registered.

Read `my/provision/{ENV_NAME}/config.json` for ENV_URL, ENV_NAME, PERSONA,
and ENV_ID.

## Auth-mode decision (open, defer to revisit)

The Workday SOAP connector supports four auth modes (`basic`, `oauth`,
`oauthapim`, `oauth2generic`). The current default is `oauth` (Microsoft
Entra ID Integrated) to match the production auth-simplification model
where every runtime call flows under the signed-in user's identity. The
trade-off is that `oauth` requires a one-time browser sign-in to complete
the SAML+OAuth handshake for the connection, which is why this step
parallelizes that sign-in with the ISV install.

If you ever switch to `oauth2generic` (Workday OAuth client credentials)
the sign-in step goes away entirely — connections become Connected
immediately. The trade-off is service-identity runtime auth (one Workday
identity used for every call, regardless of who signed in). See the project
memory note `project_pp_connectivity_api.md` for the full discussion.

---

## 3.1 — Skip if already complete

Read `my/provision/{ENV_NAME}/tasks.md`. Only skip this step if ALL five
Step 3 task items are `- [x]`:

- ISV imported
- Connections active
- Connection refs bound
- Flow runtime connections wired
- User Context Setup topic configured

If all five are checked, skip to 3.11 (Persist final state).

If only some are checked, resume from the first incomplete subsection:

- ISV imported unchecked → start at 3.2 (PAC auth check, then 3.3)
- ISV imported checked but Connections active unchecked → if `connections.workday.connectionId` AND `connections.dataverse.connectionId` already exist in config.json, skip to 3.7 (verify status); otherwise start at 3.4
- Both checked but Connection refs bound unchecked → start at 3.8
- Connection refs bound checked but Flow runtime unchecked → start at 3.9
- Flow runtime checked but User Context unchecked → start at 3.10

---

## 3.2 — Ensure PAC is authenticated for the correct ring

Step 2 runs this check, but if Step 2 was skipped (ESS base already present),
the PAC auth profile may not be set to the correct ring for this provision.

Read RING from config.json. Map to PAC cloud:
- RING `preprod` → cloud `Preprod`
- RING `prod` → cloud `Public`

Run `pac auth list`. If no profile exists for the target cloud, ask the user
to create one (`pac auth create --cloud {cloud} --deviceCode`). If a profile
exists but is not active, run `pac auth select --index {N}`.

---

## 3.3 — Resolve ISV application name from persona

Map PERSONA to the AppSource application name:

- PERSONA `hr` → `msdyn_EssHRWorkday`
- PERSONA `it` → `msdyn_EssITWorkday`

Save as ISV_APP_NAME.

---

## 3.4 — Pre-create the Workday and Dataverse connections

The `/provision` path uses a simplified two-connection model: one Workday
SOAP (OAuthUser) and one Dataverse connection. All Workday connection refs
in the ISV solution are bound to the single Workday connection. For
advanced multi-identity setups (ISU_WQL, ISU_Generic), use `/connect workday`
after provisioning.

Both connections can be created **before** the Workday ISV installs — the
underlying connectors (`shared_workdaysoap`, `shared_commondataserviceforapps`)
are platform-level and exist in every env. We create them now so the user
can complete OAuth in parallel with the install.

Run silently:

```
python scripts/create_connection.py --env-id {ENV_ID} --env-url {ENV_URL} --ring {RING} --connector shared_workdaysoap
```

Capture the `connectionId` and `displayName` from the JSON stdout. Save as
WORKDAY_CONNECTION_ID and WORKDAY_CONNECTION_DISPLAY_NAME.

Then:

```
python scripts/create_connection.py --env-id {ENV_ID} --env-url {ENV_URL} --ring {RING} --connector shared_commondataserviceforapps
```

Capture the `connectionId` and `displayName` from the JSON stdout. Save as
DATAVERSE_CONNECTION_ID and DATAVERSE_CONNECTION_DISPLAY_NAME.

Both connections come back in `status: Error, target: token` ("Unauthenticated").
This is expected — the OAuth handshake has not happened yet.

Write the IDs and display names to `my/provision/{ENV_NAME}/config.json`:

```json
{
  "connections": {
    "workday": {"connectionId": "{WORKDAY_CONNECTION_ID}", "displayName": "{WORKDAY_CONNECTION_DISPLAY_NAME}", "status": "Unauthenticated"},
    "dataverse": {"connectionId": "{DATAVERSE_CONNECTION_ID}", "displayName": "{DATAVERSE_CONNECTION_DISPLAY_NAME}", "status": "Unauthenticated"}
  }
}
```

If either script exits non-zero, show the stderr to the user and stop the
skill. Common causes: PAC token cache expired (re-run `pac auth create`),
the browser sign-in was cancelled, or the custom Entra app's permissions
on the Preprod resource are missing.

---

## 3.5 — Ask the user to sign in to both connections (parallel with install)

Build MAKER_HOST from RING:
- RING `preprod` → MAKER_HOST = `make.preprod.powerapps.com`
- RING `prod` → MAKER_HOST = `make.powerapps.com`

**Message:**

I've created the two connections this env needs. While I install the Workday
extension (takes 2-3 minutes), please sign in to both connections so they
are ready when the install finishes.

Open this page in your browser:

https://{MAKER_HOST}/environments/{ENV_ID}/connections

Then:

1. Find the connection named **{WORKDAY_CONNECTION_DISPLAY_NAME}** in the list.
   Click it → click **Connect** or **Sign in** → complete the Microsoft
   sign-in flow. Status should flip to **Connected**.
2. Find the connection named **{DATAVERSE_CONNECTION_DISPLAY_NAME}** in the same
   list. Click it → **Connect** → sign in. Status should flip to
   **Connected**.

Type **done** when both connections show **Connected** in the maker portal,
or **skip** if you want to keep going and come back to this later (the
final validation step will fail until both are Connected).

**End message.**

Immediately after showing the message above, proceed to 3.6 to start the
ISV install. **Do NOT wait** for the user's `done` response — the install
runs in the terminal while the user signs in via their browser. Show both
the informational message and the install command output in the same turn.
The user's `done` response will be collected after the install finishes
in §3.7.

---

## 3.6 — Install Workday ISV via `pac application install`

**Message:**

Installing Workday {persona} extension now. This typically takes 2-3 minutes.
The PAC CLI will poll until the install completes — you'll see its progress
below. Keep signing in to the connections in the other tab while this runs.

**End message.**

Run in the terminal:

```
pac application install --environment {ENV_URL} --application-name {ISV_APP_NAME}
```

PAC polls AppSource internally. Let the user see PAC's output as-is.

**If pac returns exit code 0:**

Verify via Dataverse. Use `startswith` because the AppSource application
name may differ from the Dataverse solution unique name:

```
GET {ENV_URL}/api/data/v9.2/solutions?$select=uniquename,version,ismanaged&$filter=startswith(uniquename,'msdyn_ess{persona}')
```

Expect at least one row with `ismanaged: true`. Save to config.json:

```json
{
  "isvSolution": {
    "uniqueName": "{ISV_APP_NAME}",
    "version": "{version}",
    "installedAt": "{current ISO datetime}"
  }
}
```

Update `my/provision/{ENV_NAME}/tasks.md` — change "ISV imported" to `- [x]`.

**If pac returns non-zero:** show stderr and stop. Same recovery as step2 §2.3.

---

## 3.7 — Verify both connections are active

If the user already typed **done** while the install was running, skip to
the verification below.

If not, prompt now:

**Message:**

Workday {persona} extension installed.

Last thing: please confirm both connections show **Connected** in the maker
portal at https://{MAKER_HOST}/environments/{ENV_ID}/connections.

Type **done** when both show Connected. Type **skip** to leave them in
unauthenticated state (validation will fail).

**End message.**

Wait for the user. **Cap the wait at 30 minutes** (max 60 polls at 30s
intervals). After 30 minutes without `done` from the user, stop the skill
with a message that says "OAuth not completed within 30 min — re-run
`/provision` later to resume."

Once the user types **done**, verify both connections are actually Connected
by querying the Power Platform Connectivity API.

**Auth for the Connectivity API:** Use the same MSAL token flow as
`create_connection.py` — acquire a token with the ring-appropriate scope
from `pp_helpers.SCOPES_BY_RING[RING]` (preprod:
`https://api.preprod.powerplatform.com/.default`, prod:
`https://api.powerplatform.com/.default`). The token cache from Step 1's
`whoami.py` / `auth.py` is separate (Dataverse scope); the Connectivity
API needs the Power Platform scope. Use the cached MSAL token if available,
otherwise `acquire_token_silent` will handle it.

Build the per-env host from ENV_ID and RING using the same format as
`pp_helpers.per_env_host()`:

```
{first 31 chars of ENV_ID without dashes}.{remaining chars}.{ring-suffix}
```

Where ring-suffix is `environment.api.preprod.powerplatform.com` for preprod
or `environment.api.powerplatform.com` for prod.

Check each connection:

```
GET https://{PER_ENV_HOST}/connectivity/connectors/shared_workdaysoap/connections/{WORKDAY_CONNECTION_ID}?api-version=1
```

```
GET https://{PER_ENV_HOST}/connectivity/connectors/shared_commondataserviceforapps/connections/{DATAVERSE_CONNECTION_ID}?api-version=1
```

Look at `properties.statuses` for each. Prefer the entry where
`target == "token"` (most reliable for OAuth connections). If no token
target exists, fall back to `statuses[0]`. If the status is `Connected`,
the connection is ready. If both are `Connected`, proceed.

If either is still `Error` or not Connected:

**Message:**

Connection **{name}** is not yet Connected (status: {actual_status}).
Please complete the OAuth sign-in in the maker portal and type **done**
again.

**End message.**

Return to waiting. After 3 failed verifications, stop the skill with a
message directing the user to check the connections manually.

Once both connections are Connected, update `my/provision/{ENV_NAME}/tasks.md`
— change "Connections active" to `- [x]`.

---

## 3.8 — Auto-bind connection references to the connections

Now that the Workday ISV is installed, the connection references it registers
exist in the env. Bind each to the matching connection we created in 3.3.

Run:

```
python scripts/bind_connection_refs.py \
    --env-id {ENV_ID} \
    --env-url {ENV_URL} \
    --workday-connection {WORKDAY_CONNECTION_ID} \
    --dataverse-connection {DATAVERSE_CONNECTION_ID}
```

The script:
1. Queries all connection refs in the env
2. Classifies each by connector type (workday / dataverse / etc.)
3. PATCHes each ref's `connectionid` to the matching connection we created

**If exit code is 0:** all bindings succeeded. Parse the JSON stdout for the
`bindings` array and add to config.json:

```json
{
  "connectionBindings": [
    {"refLogicalName": "new_sharedworkdaysoap_ff0df", "connectionId": "{WORKDAY_CONNECTION_ID}", "status": "bound"},
    ...
  ]
}
```

Update `my/provision/{ENV_NAME}/tasks.md` — change "Connection refs bound" to `- [x]`.

**If exit code is 2 (one or more PATCH failures):** show the failures from
the JSON output. The helper uses the simple lookup-field PATCH form
(`{"connectionid": "<guid>"}`), which is confirmed working against
Dataverse Web API v9.2 for the `connectionreferences` table. If a future
Dataverse version rejects this form, the navigation-property form
(`{"connection@odata.bind": "/connections(<guid>)"}`) is the documented
alternative — surface the exact response so the helper can be updated.

---

## 3.9 — Wire flow runtime connections (semi-automated)

After the Workday ISV install, two flows in the agent need their runtime
connections explicitly wired in Copilot Studio. The solution-level
connection references bound in 3.8 are not enough — Copilot Studio's
flow runtime needs a separate per-flow binding through its own API.

Additionally: because connections were unauthenticated at install time,
the install logic leaves the flows in `Draft` / off state. They must be
enabled before the binding can succeed.

First, run the helper to discover and enable the flows:

```
python scripts/wire_flow_bindings.py \
    --env-url {ENV_URL} \
    --persona {hr or it} \
    --workday-connection-name {WORKDAY_CONNECTION_DISPLAY_NAME}
```

The helper:
1. Queries the `workflows` table for `ESS {persona} Workday` and
   `WorkdayRESTExecution` flows.
2. PATCHes any disabled flow to `statecode=1, statuscode=2` (Activated).
3. Outputs manual wiring instructions (see Steps A and B below).

**If exit code is 0:** flows are enabled. Proceed to Step A.

**If exit code is non-zero:** show stderr and stop. Common causes:
- Workday ISV install may be incomplete (missing flows).
- Dataverse auth failed.

> **Why are Steps A and B manual?** The user-connections API requires
> legacy `PowerVirtualAgents.Tokens.Read` and `All.All.ReadWrite`
> permissions that no longer exist in the Power Platform API permission
> catalog. Custom Entra apps cannot acquire them, and the CPS first-party
> app (`a522f059-...`) blocks both device-code (AADSTS7000218) and
> localhost redirect (AADSTS50011) flows from CLI. Only the CPS portal's
> own browser session can call this endpoint.

**Message:**

I've enabled both Workday flows. The remaining wiring needs to be done
in the Copilot Studio portal:

### Step A — Wire flows to connection

1. Open **{CPS_URL}** (use `copilotstudio.preview.microsoft.com` for
   preprod, `copilotstudio.microsoft.com` for prod)
2. Switch to the **{ENV_NAME}** environment
3. Open **Employee Self-Service {PERSONA}** agent → **Actions**
4. For each flow (`ESS {PERSONA} Workday` and `WorkdayRESTExecution`):
   - Click the flow → **Connect** → select **{WORKDAY_CONNECTION_NAME}**

### Step B — Share connection parameters

For each flow you just connected:

1. Click **See details** (under the **Manage** section)
2. Go to the **Connection parameters** tab
3. Toggle **"Allow permission to share parameters"** to ON
   _(Allowing the end-user to use this authentication will provide
   improved responses)_
4. Click **Save**

Repeat for both `ESS {PERSONA} Workday` and `WorkdayRESTExecution`.

Type **done** when both flows are connected and parameter sharing is enabled.

**End message.**

When the user types **done**, update `my/provision/{ENV_NAME}/tasks.md`
— change "Flow runtime connections wired" to `- [x]`.

---

## 3.10 — Update the User Context Setup topic (automated)

The agent's `[Admin] - User Context - Setup` topic must redirect to
`WorkdaySystemGetUserContextV2` so every Workday topic can resolve the
signed-in user's worker ID at runtime. After a fresh install, this topic
is empty. The `update_user_context_topic.py` helper finds the topic by
querying the `botcomponents` table and PATCHes the `data` field with the
correct redirect YAML for the persona.

**Important:** Copilot Studio reads the `data` field, **not** `content`,
for topic body. PATCHing `content` succeeds (HTTP 204) but is invisible
to CPS. This distinction is enforced in the helper.

Run silently:

```
python scripts/update_user_context_topic.py \
    --env-url {ENV_URL} \
    --persona {hr or it}
```

The helper:
1. Authenticates to Dataverse via auth.py (PAC CLI app).
2. Queries `botcomponents` for components in the
   `msdyn_copilotforemployeeselfservice{hr|it}` namespace.
3. Filters client-side for the User Context Setup topic by name/schema.
4. PATCHes the topic's `data` field with the persona-correct YAML (CPS reads `data`, not `content`):

```yaml
kind: AdaptiveDialog
beginDialog:
  kind: OnRedirect
  id: main
  priority: 0
  actions:
    - kind: BeginDialog
      id: QVk2yi
      dialog: msdyn_copilotforemployeeselfservice{hr|it}.topic.WorkdaySystemGetUserContextV2
```

**If exit code is 0:** parse stdout for the patched topic info. Update
config.json:

```json
{
  "userContextTopicPatched": {
    "botcomponentid": "...",
    "name": "[Admin] - User Context - Setup",
    "schemaname": "...",
    "patchedAt": "{current ISO datetime}"
  }
}
```

Update `my/provision/{ENV_NAME}/tasks.md` — change "User Context Setup topic configured" to `- [x]`.

**If exit code is 2 (topic not found or PATCH rejected):**
- Topic not found usually means the Workday ISV install did not complete
  cleanly. Re-run the helper after verifying the ISV solution exists.
- PATCH rejected may indicate the topic is part of a managed solution
  that does not allow direct content modification. Fall back to the
  manual maker-portal edit. The helper has a `--dry-run` flag that
  prints the current and proposed content for inspection.
- Topic has custom content (safety check blocked overwrite). Use
  `--force` if the overwrite is intended.

Do NOT mark the checkbox on failure. Type **retry** or **cancel**.

---

## 3.11 — Persist final state and proceed

Save to config.json:

```json
{
  "connectionsCompletedAt": "{current ISO datetime}",
  "manualConfigCompletedAt": "{current ISO datetime}"
}
```

**Message:**

Workday {persona} extension installed and fully wired.

| Item | Status |
|------|--------|
| Solution imported | {ISV_APP_NAME} |
| Workday connection | Connected |
| Dataverse connection | Connected |
| Connection refs bound | {N of N} |
| ESS HR Workday flow connected | yes |
| WorkdayRESTExecution flow connected | yes |
| User Context Setup topic configured | yes |

The env is now ready for end-to-end Workday queries from the agent.

**End message.**

Continue to step4.md.
