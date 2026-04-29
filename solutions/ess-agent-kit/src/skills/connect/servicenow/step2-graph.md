# ServiceNow Step 2: Graph Connector Setup (Federated Auth)

**This file sets up the Microsoft 365 Graph Connector for ServiceNow
Knowledge search using Federated Auth.** It creates the OIDC provider,
integration user, role assignments, and table ACLs in ServiceNow.

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "SP_OBJECT_ID = ..." or "OIDC_ENTITY_SYS_ID = ..." in
chat. The user should only see Message blocks and tool output tables.

**Do NOT ask the user any questions before reading azure/login.md in
section 2.1.** Go directly to 2.1.

Read `my/connect/servicenow/config.json` for INSTANCE_NAME and TENANT_ID
(if already captured from an earlier Entra login). If TENANT_ID is not
in config, section 2.1 will collect it.

---

## 2.1 — Azure login

Read `src/skills/connect/azure/login.md` and follow it.

When it completes, you will have TENANT_ID.

---

## 2.2 — Get the service principal object ID

The Graph Connector uses Microsoft's first-party app
(`933838e2-bec1-440f-a634-9363c82e5b6d`). We need its service principal
object ID in the user's tenant.

Run in the terminal:

```
az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals?$filter=appId eq '933838e2-bec1-440f-a634-9363c82e5b6d'" --query "value[0].id" -o tsv
```

Save the output as SP_OBJECT_ID.

**If the output is empty or the command fails**:

**Message:**

The Graph Connector service principal hasn't been provisioned in your
tenant yet. This usually happens automatically when you start setting
up a Graph connector in the M365 Admin Center.

1. Go to [M365 Admin Center](https://admin.microsoft.com/)
2. Navigate to **Copilot** → **Connectors** → **Gallery**
3. Click **ServiceNow Knowledge** → start the wizard → then cancel
4. Come back here and type **retry**

**End message.**

Wait for the user. Then retry the `az rest` command.

---

## 2.3 — Create OIDC provider entity in ServiceNow

Before making any changes to ServiceNow, explain what will happen
and get confirmation.

**Message:**

Setting up the Graph Connector requires creating several records in
your ServiceNow instance:

- An **OIDC provider entity** (for Microsoft authentication)
- A **provider configuration** (claims mapping)
- An **integration user** (machine account for the connector)
- **6 role assignments**
- **Read ACLs on 20 tables** (so the connector can index knowledge articles)

This is all automated and takes about 30 seconds.

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Set up Graph Connector",
    "question": "OK to create these records in ServiceNow?",
    "options": [
      { "label": "Go ahead, set it all up", "recommended": true },
      { "label": "Wait, tell me more first" }
    ],
    "allowFreeformInput": false
  }
]
```

If the user chose "Wait, tell me more first":

**Message:**

Here's what each piece does:

- **OIDC provider**: Tells ServiceNow how to verify tokens from
  Microsoft's Graph Connector service
- **Claims mapping**: Maps the `oid` claim in the token to a
  ServiceNow user account
- **Integration user**: A machine account whose username matches the
  Graph Connector's service principal ID — this is how ServiceNow
  identifies the connector
- **Roles**: The integration user needs `knowledge`, `knowledge_admin`,
  `knowledge_manager`, `catalog_admin`, `user_criteria_admin`, and
  `user_admin` to read knowledge base content
- **ACLs**: Explicit read permissions on 20 tables that the connector
  indexes (knowledge articles, user criteria, attachments, etc.)

All records are tagged with "Created by ESS Copilot Kit" so they're
easy to find and remove later if needed.

Type **go** when you're ready to proceed.

**End message.**

Wait for the user.

---

**Message (do NOT wait for user response — continue immediately):**

Creating OIDC provider...

**End message.**

First, check if an OIDC entity already exists for the Graph Connector
(idempotency).

Call the ServiceNow MCP `query_table` tool:

```
query_table(table="oauth_oidc_entity", query="client_id=933838e2-bec1-440f-a634-9363c82e5b6d", fields="sys_id,name,client_id", limit=1)
```

**If a result exists**: extract its `sys_id` as OIDC_ENTITY_SYS_ID.
Skip to 2.4.

**If no result**: create a new one.

Call the ServiceNow MCP `register_oidc_provider` tool:

```
register_oidc_provider(
  name="Microsoft Entra ID - Graph Connector",
  client_id="933838e2-bec1-440f-a634-9363c82e5b6d",
  client_secret="not-used",
  well_known_url="https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration"
)
```

Note the **v2.0** endpoint — this differs from the Power Platform path.

Extract `sys_id` from the response → save as OIDC_ENTITY_SYS_ID.

**Immediately save OIDC_ENTITY_SYS_ID** to
`my/connect/servicenow/config.json` under `graph.oidcEntitySysId`.

**If the call fails**: retry once. If still fails, show the error and
suggest manual creation in ServiceNow admin.

**Message (do NOT wait for user response — continue immediately):**

✅ OIDC provider created.

**End message.**

---

## 2.4 — Create OIDC provider configuration (claims mapping)

**CRITICAL: `user_field` must be `user_name`, NOT `user_id`.**

The docs say "User Field: User ID" but in ServiceNow's schema, the
column labeled "User ID" in the UI is actually the `user_name` API
field. Setting `user_field` to `user_id` causes "Connection setup
details are not valid" in the M365 Admin Center.

First, check if a Graph-specific config already exists:

Call the ServiceNow MCP `query_table` tool:

```
query_table(table="oidc_provider_configuration", query="nameLIKEGraph^ORnameLIKEv2", fields="sys_id,name,user_claim,user_field,oidc_url", limit=5)
```

**If a matching record exists** with `user_claim=oid` and
`user_field=user_name`: extract its `sys_id` as OIDC_CONFIG_SYS_ID.
Skip to 2.5.

**If no match**: create a new config.

Call the ServiceNow MCP `create_record` tool:

```
create_record(table="oidc_provider_configuration", data="{\"name\": \"Microsoft Entra ID v2 - Graph Connector\", \"oidc_url\": \"https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration\", \"oidc_config_cache_life_span\": \"120\", \"user_claim\": \"oid\", \"user_field\": \"user_name\", \"enable_jti_verification\": \"false\"}")
```

Extract `sys_id` from the response → save as OIDC_CONFIG_SYS_ID.

**Immediately save OIDC_CONFIG_SYS_ID** to
`my/connect/servicenow/config.json` under `graph.oidcConfigSysId`.

**If create returns 403**: fall back to querying for the built-in
"Azure AD" config and updating it:

```
query_table(table="oidc_provider_configuration", query="nameLIKEAzure", fields="sys_id,name", limit=5)
```

Find the record, save its `sys_id` as OIDC_CONFIG_SYS_ID, then update:

```
update_record(table="oidc_provider_configuration", sys_id="{OIDC_CONFIG_SYS_ID}", data="{\"oidc_url\": \"https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration\", \"user_claim\": \"oid\", \"user_field\": \"user_name\"}")
```

---

## 2.5 — Link configuration to OIDC entity

Call the ServiceNow MCP `update_record` tool:

```
update_record(table="oauth_oidc_entity", sys_id="{OIDC_ENTITY_SYS_ID}", data="{\"oidc_provider_configuration\": \"{OIDC_CONFIG_SYS_ID}\"}")
```

**If the update fails**: retry once. If still fails, show error and
suggest manual linking in ServiceNow admin.

---

## 2.6 — Create integration user

**Message (do NOT wait for user response — continue immediately):**

Creating integration user...

**End message.**

The Graph Connector authenticates as a machine user whose `user_name`
matches the `oid` claim in the OIDC token (which is the service
principal object ID).

First check if the user already exists:

```
query_table(table="sys_user", query="user_name={SP_OBJECT_ID}", fields="sys_id,user_name,active", limit=1)
```

**If found**: extract `sys_id` as GRAPH_USER_SYS_ID. Skip to 2.7.

**If not found**: create the user.

```
create_record(table="sys_user", data="{\"user_name\": \"{SP_OBJECT_ID}\", \"first_name\": \"Graph Connector\", \"last_name\": \"Service Account\", \"active\": \"true\", \"web_service_access_only\": \"true\", \"internal_integration_user\": \"true\"}")
```

Extract `sys_id` from the response → save as GRAPH_USER_SYS_ID.

**Immediately save GRAPH_USER_SYS_ID** to
`my/connect/servicenow/config.json` under `graph.userSysId`.

---

## 2.7 — Assign roles

**Message (do NOT wait for user response — continue immediately):**

Assigning roles...

**End message.**

The integration user needs ALL 6 of these roles:

```
catalog_admin, user_criteria_admin, user_admin, knowledge, knowledge_admin, knowledge_manager
```

Query for the role sys_ids:

```
query_table(table="sys_user_role", query="name=catalog_admin^ORname=user_criteria_admin^ORname=user_admin^ORname=knowledge^ORname=knowledge_admin^ORname=knowledge_manager", fields="sys_id,name", limit=10)
```

For each role in the results, check if the user already has it:

```
query_table(table="sys_user_has_role", query="user={GRAPH_USER_SYS_ID}^role={ROLE_SYS_ID}", fields="sys_id", limit=1)
```

If not found, assign it:

```
create_record(table="sys_user_has_role", data="{\"user\": \"{GRAPH_USER_SYS_ID}\", \"role\": \"{ROLE_SYS_ID}\"}")
```

Repeat for all 6 roles.

**Roles alone are NOT sufficient.** You MUST also do section 2.8 to
create explicit table ACLs.

**Message (do NOT wait for user response — continue immediately):**

✅ 6 roles assigned.

**End message.**

---

## 2.8 — Create ACLs via temporary Scripted REST API

**Message (do NOT wait for user response — continue immediately):**

Setting up table ACLs (this takes a few seconds)...

**End message.**

**This is the most critical step.** The Graph Connector requires
explicit read ACLs on 20 tables. Without them, the M365 Admin Center
shows "Missing access to tables" and connection creation fails.

ACLs CANNOT be created via the ServiceNow Table REST API (returns 403).
The solution is a temporary Scripted REST API that runs server-side
with admin context.

### 2.8a — Create temporary API definition

```
create_record(table="sys_ws_definition", data="{\"name\": \"Copilot ACL Setup\", \"api_id\": \"copilot_acl_setup\", \"active\": \"true\"}")
```

Extract `sys_id` from the response → save as API_SYS_ID.

From the response, find the `namespace` value. It is typically in the
`sys_scope` or derived from `base_uri`. If not directly available,
query for it:

```
get_record(table="sys_ws_definition", sys_id="{API_SYS_ID}", fields="sys_id,api_id,base_uri,namespace")
```

Extract `namespace` → save as API_NAMESPACE. If `namespace` is empty,
use `api_id` value (`copilot_acl_setup`) as the namespace.

### 2.8b — Build the ACL setup script

Build the following JavaScript string. Replace `{GRAPH_USER_SYS_ID}`
with the actual value:

```javascript
(function() {
    var tables = [
        'kb_knowledge', 'kb_knowledge_base', 'kb_uc_can_read_mtom',
        'kb_uc_can_contribute_mtom', 'kb_uc_cannot_read_mtom',
        'kb_uc_cannot_contribute_mtom', 'user_criteria', 'sys_user',
        'sys_user_group', 'sys_user_role', 'sys_user_grmember',
        'sys_user_has_role', 'sys_attachment', 'kb_feedback',
        'sys_properties', 'sys_db_object', 'sys_dictionary',
        'cmn_department', 'cmn_location', 'core_company'
    ];
    var MARKER = 'Created by ESS Copilot Kit - Graph Connector ACL Setup';
    var roleName = 'copilot_graph_connector';
    var userSysId = '{GRAPH_USER_SYS_ID}';
    var results = [];

    // Create or find custom role
    var roleGr = new GlideRecord('sys_user_role');
    roleGr.addQuery('name', roleName);
    roleGr.query();
    var roleSysId;
    if (roleGr.next()) {
        roleSysId = roleGr.getUniqueValue();
        results.push('Role exists: ' + roleName);
    } else {
        roleGr.initialize();
        roleGr.setValue('name', roleName);
        roleGr.setValue('description', MARKER);
        roleSysId = roleGr.insert();
        results.push('Created role: ' + roleName);
    }

    // Assign role to user
    var hasRole = new GlideRecord('sys_user_has_role');
    hasRole.addQuery('user', userSysId);
    hasRole.addQuery('role', roleSysId);
    hasRole.query();
    if (!hasRole.next()) {
        hasRole.initialize();
        hasRole.setValue('user', userSysId);
        hasRole.setValue('role', roleSysId);
        hasRole.insert();
        results.push('Assigned role to user');
    }

    for (var i = 0; i < tables.length; i++) {
        var tbl = tables[i];
        // Row-level ACL
        var rowAcl = new GlideRecord('sys_security_acl');
        rowAcl.addQuery('name', tbl);
        rowAcl.addQuery('operation', 'read');
        rowAcl.addQuery('type', 'record');
        rowAcl.addQuery('description', MARKER);
        rowAcl.query();
        var rowAclId;
        if (rowAcl.next()) {
            rowAclId = rowAcl.getUniqueValue();
        } else {
            rowAcl.initialize();
            rowAcl.setValue('name', tbl);
            rowAcl.setValue('operation', 'read');
            rowAcl.setValue('type', 'record');
            rowAcl.setValue('active', true);
            rowAcl.setValue('admin_overrides', true);
            rowAcl.setValue('description', MARKER);
            rowAclId = rowAcl.insert();
            results.push('Created row ACL: ' + tbl);
        }
        // Link row ACL to role
        var rowLink = new GlideRecord('sys_security_acl_role');
        rowLink.addQuery('sys_security_acl', rowAclId);
        rowLink.addQuery('sys_user_role', roleSysId);
        rowLink.query();
        if (!rowLink.next()) {
            rowLink.initialize();
            rowLink.setValue('sys_security_acl', rowAclId);
            rowLink.setValue('sys_user_role', roleSysId);
            rowLink.insert();
        }

        // Field-level ACL
        var fieldAcl = new GlideRecord('sys_security_acl');
        fieldAcl.addQuery('name', tbl + '.*');
        fieldAcl.addQuery('operation', 'read');
        fieldAcl.addQuery('type', 'record');
        fieldAcl.addQuery('description', MARKER);
        fieldAcl.query();
        var fieldAclId;
        if (fieldAcl.next()) {
            fieldAclId = fieldAcl.getUniqueValue();
        } else {
            fieldAcl.initialize();
            fieldAcl.setValue('name', tbl + '.*');
            fieldAcl.setValue('operation', 'read');
            fieldAcl.setValue('type', 'record');
            fieldAcl.setValue('active', true);
            fieldAcl.setValue('admin_overrides', true);
            fieldAcl.setValue('description', MARKER);
            fieldAclId = fieldAcl.insert();
            results.push('Created field ACL: ' + tbl + '.*');
        }
        // Link field ACL to role
        var fieldLink = new GlideRecord('sys_security_acl_role');
        fieldLink.addQuery('sys_security_acl', fieldAclId);
        fieldLink.addQuery('sys_user_role', roleSysId);
        fieldLink.query();
        if (!fieldLink.next()) {
            fieldLink.initialize();
            fieldLink.setValue('sys_security_acl', fieldAclId);
            fieldLink.setValue('sys_user_role', roleSysId);
            fieldLink.insert();
        }
    }

    results.push('Done. Created ACLs for ' + tables.length + ' tables.');
    response.setBody({status: 'success', details: results});
})(request, response);
```

### 2.8c — Deploy the script as an API resource

**IMPORTANT**: The field is `operation_script`, NOT `script`.
**IMPORTANT**: Set `requires_snc_internal_role` to `false`.

```
create_record(table="sys_ws_operation", data="{\"name\": \"RunSetup\", \"http_method\": \"GET\", \"relative_path\": \"/run\", \"web_service_definition\": \"{API_SYS_ID}\", \"active\": \"true\", \"is_scripted\": \"true\", \"requires_authentication\": \"true\", \"requires_snc_internal_role\": \"false\", \"operation_script\": \"{ESCAPED_SCRIPT}\"}")
```

The script must be JSON-escaped (newlines as `\n`, quotes as `\"`).

Extract `sys_id` from the response → save as RESOURCE_SYS_ID.

### 2.8d — Execute the ACL setup

Call the ServiceNow MCP `call_api` tool to execute the temporary
Scripted REST API. This reuses the existing authenticated session —
no additional credentials needed.

```
call_api(method="GET", path="/api/{API_NAMESPACE}/copilot_acl_setup/run")
```

Replace `{API_NAMESPACE}` with the namespace from step 2.8a.

If the response contains `"status": "success"`, proceed to 2.8e.

**If the call fails**:

- **404**: The API namespace is wrong. Re-check the `base_uri` or
  `namespace` from the `sys_ws_definition` record. The path format
  is `/api/{namespace}/{api_id}/{relative_path}`.
- **403**: The `requires_snc_internal_role` may be `true` on the
  operation. Update it to `false` and retry.
- **500**: The script has an error. Check the response body for
  details.

If the call cannot be resolved, show the user the manual fallback:

**Message:**

The automated ACL setup didn't complete. You can run it manually:

1. Log into ServiceNow as admin
2. Navigate to **System Definition** → **Scripts - Background**
3. Paste the ACL setup script and click **Run script**

The scripts are available at:
https://github.com/microsoft/copilot-servicenow-connector-setup-scripts

Type **done** when you've run the scripts.

**End message.**

Wait for the user.

### 2.8e — Clean up the temporary API

**IMPORTANT: This cleanup MUST run regardless of whether 2.8d succeeded
or failed.** Do not skip this step on failure — orphaned API records
will remain in the user's ServiceNow instance.

Delete the resource and API definition:

```
delete_record(table="sys_ws_operation", sys_id="{RESOURCE_SYS_ID}")
delete_record(table="sys_ws_definition", sys_id="{API_SYS_ID}")
```

If the deletes fail, note the sys_ids and inform the user:

**Message:**

I couldn't clean up the temporary API records. You can delete them
manually in ServiceNow:

- **Scripted REST Services** → find "Copilot ACL Setup" → delete it

**End message.**

---

## 2.9 — Save config and display results

Update `my/connect/servicenow/config.json` — add or update the `graph`
object. Some fields may already be saved from incremental saves above;
ensure all fields are present:

```json
{
  "graph": {
    "tenantId": "{TENANT_ID}",
    "spObjectId": "{SP_OBJECT_ID}",
    "oidcEntitySysId": "{OIDC_ENTITY_SYS_ID}",
    "oidcConfigSysId": "{OIDC_CONFIG_SYS_ID}",
    "userSysId": "{GRAPH_USER_SYS_ID}"
  }
}
```

**Message:**

✅ ServiceNow is configured for the Graph Connector.

Here's what was set up:

| Record | Status |
|--------|--------|
| OIDC provider | ✅ Created |
| Claims configuration | ✅ Configured |
| Integration user | ✅ Created |
| Role assignments | ✅ 6 roles assigned |
| Table ACLs | ✅ 20 tables configured |

Now you need to create the connection in the Microsoft 365 Admin Center.
Type **go** to continue.

**End message.**

Wait for the user. Then read `src/skills/connect/servicenow/step3-graph.md`
and follow it.

---

## 2.10 — Cleanup on failure (reference)

This section is NOT part of the normal flow. Use it only if a step
fails permanently and the user wants to start over.

Records created during this flow (check config.json for sys_ids):

| Table | Record | Config key |
|-------|--------|------------|
| `oauth_oidc_entity` | OIDC provider | `graph.oidcEntitySysId` |
| `oidc_provider_configuration` | Claims config | `graph.oidcConfigSysId` |
| `sys_user` | Integration user | `graph.userSysId` |
| `sys_user_has_role` | 6 role assignments | (query by user sys_id) |
| `sys_security_acl` | ~40 ACL records | (query by description marker) |
| `sys_ws_definition` | Temp API | Should already be cleaned up in 2.8e |
| `sys_ws_operation` | Temp API resource | Should already be cleaned up in 2.8e |

To clean up ACLs, query:
```
query_table(table="sys_security_acl", query="descriptionLIKEESS Copilot Kit", fields="sys_id", limit=50)
```
Then delete each record.

To deactivate the integration user:
```
update_record(table="sys_user", sys_id="{GRAPH_USER_SYS_ID}", data="{\"active\": \"false\"}")
```
