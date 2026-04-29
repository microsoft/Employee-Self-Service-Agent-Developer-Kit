# ServiceNow Step 2: Entra ID Setup

**This file is ONLY for Entra ID authentication. Do not use for OAuth2 or Basic.**

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "APP_CLIENT_ID = ..." or "OIDC_ENTITY_SYS_ID = ..." in
chat. The user should only see Message blocks and tool output tables.

Read `my/connect/servicenow/config.json` for INSTANCE_NAME.

**Do NOT ask the user any questions or show any messages before reading
login.md in section 2.1.** Go directly to 2.1.

---

## 2.1 — Azure login

Read `src/skills/connect/azure/login.md` and follow it.

When it completes, you will have TENANT_ID.

---

## 2.2 — Create Entra app registration

Set APP_DISPLAY_NAME to `ESS Copilot - ServiceNow OIDC ({INSTANCE_NAME})`.

Read `src/skills/connect/azure/app-registration.md` and follow it, passing
APP_DISPLAY_NAME and TENANT_ID.

When it completes, you will have APP_CLIENT_ID, APP_OBJECT_ID, and
SCOPE_GUID.

---

## 2.3 — Verify ServiceNow user matching

Enterprise instances typically have UPN-format usernames already
(provisioned by Entra Connect or SCIM). Dev instances use bare aliases
(`admin`, `john.doe`) that won't match Entra UPNs. Check before proceeding.

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Entra UPN",
    "question": "What Microsoft account will you test with? (e.g. user@yourcompany.com)"
  }
]
```

Save the answer as ENTRA_UPN.

Call the ServiceNow MCP `query_table` tool:

```
query_table(table="sys_user", query="user_name={ENTRA_UPN}", fields="sys_id,user_name,name,email,active", limit=1)
```

**If a matching user is found**: proceed to 2.4.

**If no matching user is found**:

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Create test user",
    "question": "Your ServiceNow instance doesn't have a user matching this Microsoft account. I can create a test user so the connection can be verified.",
    "options": [
      { "label": "Create the user", "recommended": true },
      { "label": "I'll create it manually in ServiceNow" }
    ],
    "allowFreeformInput": false
  }
]
```

**If the user chose "I'll create it manually in ServiceNow":**

**Message:**

No problem. In ServiceNow, go to **User Administration** → **Users** →
**New** and create a user with:

| Field | Value |
|-------|-------|
| **User ID** | `{ENTRA_UPN}` |
| **Email** | `{ENTRA_UPN}` |

Type **done** when you've created the user.

**End message.**

Wait for the user. Then proceed to 2.4.

**If the user chose "Create the user":**

Call the ServiceNow MCP `create_record` tool:

```
create_record(table="sys_user", data="{\"user_name\": \"{ENTRA_UPN}\", \"email\": \"{ENTRA_UPN}\", \"first_name\": \"ESS\", \"last_name\": \"Test User\", \"active\": \"true\"}")
```

Save the `sys_id` from the response as CREATED_USER_SYS_ID.

**Immediately save CREATED_USER_SYS_ID** to
`my/connect/servicenow/config.json` under `entra.createdUserSysId`.
This ensures the created user is tracked for cleanup if later steps fail.

**Message (do NOT wait for user response — continue immediately):**

Your ServiceNow instance didn't have a user matching `{ENTRA_UPN}`, so
I've created one. You can update the name and details later in ServiceNow
admin.

**End message.**

**If the create_record call fails**: show the error and suggest the user
create the user manually in ServiceNow (navigate to User Administration →
Users → New).

---

## 2.4 — Register OIDC provider entity

**Message:**

Next I'll configure the OIDC authentication link between Entra and
ServiceNow. This creates an OIDC provider record and updates the
claims mapping in your ServiceNow instance.

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Configure OIDC",
    "question": "OK to set up OIDC authentication in ServiceNow?",
    "options": [
      { "label": "Go ahead", "recommended": true },
      { "label": "Wait" }
    ],
    "allowFreeformInput": false
  }
]
```

If the user chose "Wait", pause and wait for them to say they're ready.
If they chose "Go ahead", proceed.

First, check if an OIDC entity already exists for this tenant (idempotency).

Call the ServiceNow MCP `query_table` tool:

```
query_table(table="oauth_oidc_entity", query="nameLIKEESS Copilot", fields="sys_id,name,client_id", limit=5)
```

**If a result exists** whose `client_id` matches APP_CLIENT_ID: extract
its `sys_id` as OIDC_ENTITY_SYS_ID. Skip to 2.5.

**If no match**: create a new one.

Call the ServiceNow MCP `register_oidc_provider` tool:

```
register_oidc_provider(
  name="Microsoft Entra ID - ESS Copilot",
  client_id="{APP_CLIENT_ID}",
  client_secret="not-used",
  well_known_url="https://login.microsoftonline.com/{TENANT_ID}/.well-known/openid-configuration"
)
```

Extract `sys_id` from the response → save as OIDC_ENTITY_SYS_ID.

**If the call fails**: retry once. If still fails, show the error and
suggest manual creation:

**Message:**

I couldn't register the OIDC provider automatically. You can do it
in ServiceNow:

1. Go to **System OAuth** → **Application Registry**
2. Click **New** → **Configure an OIDC provider to verify ID tokens**
3. Enter:
   - **Name**: `Microsoft Entra ID - ESS Copilot`
   - **Client ID**: `{APP_CLIENT_ID}`
   - **Client Secret**: `not-used`
   - **OIDC Metadata URL**: `https://login.microsoftonline.com/{TENANT_ID}/.well-known/openid-configuration`
4. Click **Submit**

Type **done** when you've created it.

**End message.**

Wait for the user. Then query again to get OIDC_ENTITY_SYS_ID.

---

## 2.5 — Update OIDC provider configuration (claims mapping)

The `oidc_provider_configuration` table is **write-protected for creates**
(returns 403). Every ServiceNow instance ships with a built-in "Azure AD"
config record. We query for it by name and update it.

Call the ServiceNow MCP `query_table` tool:

```
query_table(table="oidc_provider_configuration", query="nameLIKEAzure", fields="sys_id,name,user_claim,user_field", limit=5)
```

Find the record whose name contains "Azure AD" or "Azure". Save its
`sys_id` as OIDC_CONFIG_SYS_ID.

**If no record is found**: try a broader query:

```
query_table(table="oidc_provider_configuration", query="", fields="sys_id,name,user_claim,user_field", limit=10)
```

Look for any record that could be the default Azure AD config. If still
nothing is found:

**Message:**

I couldn't find the built-in Azure AD OIDC configuration in your
ServiceNow instance. This record is required for Entra ID
authentication.

Please check:
1. Log into ServiceNow as admin
2. Navigate to **Multi-Provider SSO** → **Identity Providers**
3. Look for an "Azure AD" entry

If it doesn't exist, you may need to activate the **Multi-Provider SSO**
plugin (`com.snc.integration.sso.multi`) first.

**End message.**

Stop here. Do not proceed.

---

Now update the record with the tenant-specific configuration:

Call the ServiceNow MCP `update_record` tool:

```
update_record(table="oidc_provider_configuration", sys_id="{OIDC_CONFIG_SYS_ID}", data="{\"oidc_url\": \"https://login.microsoftonline.com/{TENANT_ID}/.well-known/openid-configuration\", \"user_claim\": \"upn\", \"user_field\": \"user_name\"}")
```

**If the update fails**: retry once. If still fails, show the error and
suggest manual update in ServiceNow admin.

---

## 2.6 — Link OIDC config to entity

Call the ServiceNow MCP `update_record` tool:

```
update_record(table="oauth_oidc_entity", sys_id="{OIDC_ENTITY_SYS_ID}", data="{\"oidc_provider_configuration\": \"{OIDC_CONFIG_SYS_ID}\"}")
```

**If the update fails**: retry once. If still fails, show the error
and tell the user to link them manually in ServiceNow admin.

---

## 2.7 — Save config and display results

Update `my/connect/servicenow/config.json` — add an `entra` object:

```json
{
  "entra": {
    "tenantId": "{TENANT_ID}",
    "appClientId": "{APP_CLIENT_ID}",
    "appObjectId": "{APP_OBJECT_ID}",
    "scopeGuid": "{SCOPE_GUID}",
    "oidcEntitySysId": "{OIDC_ENTITY_SYS_ID}",
    "oidcConfigSysId": "{OIDC_CONFIG_SYS_ID}",
    "appDisplayName": "{APP_DISPLAY_NAME}"
  }
}
```

If CREATED_USER_SYS_ID was set (user was created in step 2.3), also add:
```json
{
  "entra": {
    "createdUserSysId": "{CREATED_USER_SYS_ID}"
  }
}
```

Update `my/connect/servicenow/tasks.md` — change step 2 from
`- [ ]` to `- [x]`.

**Message:**

✅ Entra ID connection secured — app registered and ServiceNow OIDC
configured.

| # | Task | Status |
|---|------|--------|
| 1 | Instance configured | ✅ |
| 2 | Connection secured | ✅ |
| 3 | Extension installed | ⬜ |
| 4 | Connection verified | ⬜ |

Here are the values you'll need for the next step:

| Field | Value |
|-------|-------|
| **Authentication Type** | Microsoft Entra ID User Login |
| **Resource URI** | `{APP_CLIENT_ID}` |
| **Instance Name** | `{INSTANCE_NAME}` |

Ready to install the integration in Copilot Studio? Type **go** to
continue.

**End message.**

Wait for the user. Then read `src/skills/connect/servicenow/step3-entra.md`
and follow it.

---

## 2.8 — Cleanup on failure (reference)

This section is NOT part of the normal flow. Use it only if a step
fails permanently and the user wants to start over.

If a test user was created in 2.3 (CREATED_USER_SYS_ID is set), it
can be deactivated:

```
update_record(table="sys_user", sys_id="{CREATED_USER_SYS_ID}", data="{\"active\": \"false\"}")
```

If the OIDC entity was created in 2.4 (OIDC_ENTITY_SYS_ID is set),
it can be deleted:

```
delete_record(table="oauth_oidc_entity", sys_id="{OIDC_ENTITY_SYS_ID}")
```

The Entra app registration can be deleted using the cleanup command
in `azure/app-registration.md` section B.8.
