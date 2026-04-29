# Deploy the ServiceNow Knowledge connector

Source: https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-deployment

The ServiceNow Knowledge Copilot connector enables organizations to surface ServiceNow knowledge base (KB) articles within Microsoft 365 Copilot experiences. This article describes the steps to deploy and customize the ServiceNow Knowledge connector.

For advanced ServiceNow configuration information, see [Set up the ServiceNow Knowledge service for connector ingestion](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-admin-setup).

## Prerequisites

| Role | Task |
|---|---|
| ServiceNow admin | [Configure the environment](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-admin-setup#configure-the-environment) |
| ServiceNow admin | [Set up prerequisites](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-admin-setup#set-up-connector-prerequisites) |
| Microsoft 365 admin | Deploy the connector in the Microsoft 365 admin center |
| Microsoft 365 admin | Customize connector settings (optional) |

Before you deploy the connector, make sure that the following prerequisites are met:

- You're a Microsoft 365 admin.
- You have access to a configured ServiceNow instance.
- REST API access is enabled for the required ServiceNow tables.
- Access control lists (ACLs) are configured to allow read access for the connector.
- You identified the ServiceNow instance URL.

## Deploy the connector

To add the ServiceNow Knowledge connector for your organization:

1. In the Microsoft 365 admin center, in the left pane, choose **Copilot** > **Connectors**.
2. Go to the **Connectors** tab, and in the left pane, choose **Gallery**.
3. From the list of available connectors, choose **ServiceNow Knowledge**.

### Set display name

The display name is used to identify references in Copilot responses and helps users recognize the associated file or item. It also signifies trusted content and is used as a content source filter.

You can accept the default **ServiceNow** display name or customize it to use a name that users in your organization recognize.

### Choose flow based on user criteria

The ServiceNow Knowledge connector supports two flows for user criteria permissions: **Simple** (default) and **Advanced**. Both flows evaluate knowledge base (parent)-level and article (child)-level user criteria.

The default is **Simple**. In this flow, advanced script-based user criteria aren't evaluated.

If your ServiceNow instance uses **Advanced Scripts** in your knowledge base or article-level user criteria, use the **Advanced** flow. This flow evaluates script-based user criteria by calling the Scripted REST API in ServiceNow, which ensures accurate permissions handling when content is ingested into Microsoft Graph. For the **Advanced** option to work properly, you need to [Set up REST API](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-admin-setup#set-up-rest-api).

### Set instance URL

To connect to your ServiceNow site, use your site URL, which is typically the following format: `https://<instance-name>.service-now.com`

You can find your instance name in the ServiceNow admin dashboard or by checking the sign in URL used by your organization.

### Choose authentication type

Choose the authentication method that aligns with your organization's security policies. The ServiceNow connector supports the following authentication types:

- **Federated Auth** (recommended)
- **Basic authentication** — Enter the username and password of a ServiceNow account with the **knowledge** role to authenticate to your instance.
- **OAuth 2.0**
- **Microsoft Entra ID OpenID Connect**

#### Federated Auth (Federated Identity Credentials)

Federated Auth uses a Microsoft application with OpenID Connect (OIDC) so that the connector authenticates to your ServiceNow instance without storing or rotating a client secret. Before you begin, make sure you have:

- A ServiceNow admin account with privileges to create OIDC providers and users.
- Your Microsoft Entra tenant ID (Directory ID), available from the Azure portal under **Microsoft Entra ID** > **Overview**.

##### Step 1: Get the service principal object ID

You need the Service Principal Object ID of the first-party connector application in your tenant. This is the Object ID of the service principal (enterprise application), not a new app registration.

**Option A: PowerShell (recommended)**

```powershell
Install-Module -Name Az -AllowClobber -Scope CurrentUser
Connect-AzAccount
Get-AzADServicePrincipal -ApplicationId "933838e2-bec1-440f-a634-9363c82e5b6d"
```

From the output, copy the **Id** value. This is the service principal object ID.

**Option B: Microsoft Graph API**

```http
GET https://graph.microsoft.com/v1.0/servicePrincipals?$filter=appId eq '933838e2-bec1-440f-a634-9363c82e5b6d'
```

In the JSON response, copy the **id** field. This is the service principal object ID.

##### Step 2: Create the OIDC provider in ServiceNow

1. In ServiceNow, go to **All** > **System OAuth** > **Application Registry**.
2. Select **New**.
3. The configuration steps differ depending on your ServiceNow version.

    **For Yokohama and earlier versions:**
    - Choose **Configure an OIDC provider to verify ID tokens**.

    **For Zurich and later versions:**
    - Select **New Inbound Integration Experience** > **New Integration**.
    - Choose **Third party ID token issued by OIDC supporting identity provider**.

4. Fill in the fields:

**OIDC provider configuration:**

| Field | Value |
|---|---|
| Name | Microsoft Entra ID |
| Provider name | Microsoft Entra ID (select existing or create new) |
| Client ID | `933838e2-bec1-440f-a634-9363c82e5b6d` |
| Active | Checked |

Under **OAuth OIDC Provider Configuration**, determine whether a Microsoft Entra ID option already appears in the **OIDC Provider** dropdown. If it exists, select it. If not, select **Create a new configuration** and provide the following values:

| Field | Value |
|---|---|
| OIDC Provider Configuration Name | Microsoft Entra ID |
| OIDC Metadata URL | `https://login.microsoftonline.com/<tenantId>/v2.0/.well-known/openid-configuration` (replace `<tenantId>` with your Microsoft Entra tenant ID) |
| OIDC Configuration Cache Lifespan | 120 |
| User Claim | sub or oid |
| User Field | User ID |
| Enable JTI Verification | Disabled |

Under **Auth Scope**, select **useraccount**, and enable **Allow access only to APIs in selected scope**.

##### Step 3: Create the ServiceNow integration user

1. In ServiceNow, go to **All** > **User Administration** > **Users**.
2. Select **New**.
3. Set the following fields:

| Field | Value |
|---|---|
| User ID | Service principal object ID from Step 1 |
| Identity Type | Machine |
| Active | Checked |

4. Save the user record.

**Assign roles to the integration user:**

Open the user record and, in the **Roles** related list, add these roles: `catalog_admin`, `user_criteria_admin`, `user_admin`.

> [!NOTE]
> If you assigned a custom role to the service account you created for crawling and connection setup, add that custom role to this integration user.

##### Verification

After completing all three steps:

1. **OIDC provider** — Go to **System OAuth** > **Application Registry** and confirm the Microsoft Entra ID entry is **Active** with the correct Client ID and metadata URL.
2. **Integration user** — Go to **User Administration** > **Users**, find the user by the service principal object ID, and confirm that the correct roles are assigned.
3. **Connector setup** — When you configure the connector in the Microsoft 365 admin center, select **Federated Auth** as the authentication method and provide your ServiceNow instance URL. The connector authenticates using the OIDC token issued by Microsoft Entra ID.

#### OAuth 2.0

Provision an OAuth endpoint in your ServiceNow instance for the ServiceNow Knowledge connector to access. For more information, see [Create an endpoint for clients to access the instance](https://www.servicenow.com/docs/bundle/xanadu-platform-security/page/administer/security/task/t_CreateEndpointforExternalClients.html) (for previous versions) or [Configure an OAuth authorization code grant](https://www.servicenow.com/docs/r/platform-security/authentication/configure-an-oauth-authorization-code-grant.html) (for Zurich versions).

Use the information in the following table to complete the endpoint creation form:

| Field | Description | Recommended value |
|---|---|---|
| Name | Unique value that identifies the application that you require OAuth access for. | Microsoft Search |
| Client ID | A read-only, autogenerated unique ID for the application. | NA |
| Client secret | Shared secret string for authorized communications. | Follow security best practices by treating the secret as a password. |
| Redirect URL | A required callback URL that the authorization server redirects to. | For **M365 Enterprise**: `https://gcs.office.com/v1.0/admin/oauth/callback` For **M365 Government**: `https://gcsgcc.office.com/v1.0/admin/oauth/callback` |
| Logo URL | A URL that contains the image for the application logo. | NA |
| Active | Select the check box to make the application registry active. | Set to active |
| Refresh token lifespan | The number of seconds that a refresh token is valid. By default, refresh tokens expire in 100 days (8,640,000 seconds). | 31,536,000 (one year) |
| Access token lifespan | The number of seconds that an access token is valid. | 43,200 (12 hours) |
| Auth Scope | The level of access an application has to a resource. | useraccount |

Enter the client ID and client secret to connect to your instance. After you connect, use a ServiceNow account credential to authenticate permission to crawl. The account should at least have the **knowledge** role.

#### Microsoft Entra ID OpenID Connect

1. Register a new app as a single tenant in Microsoft Entra ID. A redirect URI isn't required. For more information, see [Register an application](https://learn.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app#register-an-application).
2. Copy the **Application (client) ID** and **Directory (tenant) ID** for the app.
3. Create a client secret for the app and save it securely:
    - Go to **Manage** > **Certificates and secrets**.
    - Choose **new client secret**.
    - Provide a name and choose **Save**.
4. Use PowerShell to retrieve the service principal object ID:

    ```powershell
    Install-Module -Name Az -AllowClobber -Scope CurrentUser
    Connect-AzAccount
    Get-AzADServicePrincipal -ApplicationId "Application-ID"
    ```

    Replace "Application-ID" with the Application (client) ID. Note the value of the ID object from the output; this is the Service Principal Object ID.

    Alternatively, in the Microsoft Entra admin center: go to the app registration **Overview** > choose **managed application in local directory** > copy the **ObjectID**.

5. In your ServiceNow instance, register a new OAuth OIDC entity. Use the following values:

    | Field | Value |
    |---|---|
    | Name | Microsoft Entra ID |
    | Client ID | Application (client) ID from step 2 |
    | Client Secret | Client secret from step 3 |

    > [!NOTE]
    > After you create the OAuth OIDC entity, the client secret is generated automatically in ServiceNow. Replace this client secret with the client secret generated in the Microsoft Entra Admin center.

6. In the **OAuth OIDC Provider Configuration** field, select the search icon, and then select **New**. Fill out the form:

    | Field | Value |
    |---|---|
    | OIDC Provider | Microsoft Entra ID |
    | OIDC Metadata URL | `https://login.microsoftonline.com/<tenantId>/.well-known/openid-configuration` (replace `<tenantId>` with the Directory (tenant) ID) |
    | OIDC Configuration Cache Life Span | 120 |
    | Application | Global |
    | User Claim | sub |
    | User Field | User ID |
    | Enable JTI claim verification | Disabled |

    Set **Auth Scope** to the user account.

7. Choose **Submit** to save the configuration.

8. Create a ServiceNow account with the following values:

    | Field | Recommended value |
    |---|---|
    | User ID | Service Principal ID |
    | Web service access only | Checked |

9. Assign the **Knowledge** role to the ServiceNow account. Use the **Application ID** as the Client ID and **Client secret** in the admin center configuration wizard to authenticate with Microsoft Entra ID OpenID Connect.

> [!IMPORTANT]
> Don't turn on **Assignment required**. For more information, see [Properties of an enterprise application](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/application-properties#assignment-required).

### Add API namespace

If you're using the **Advanced** flow, enter the API namespace that you created in your ServiceNow instance. For details, see [Set up REST API](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-admin-setup#set-up-rest-api).

### Roll out

To roll out to a limited audience, choose the toggle next to **Rollout to limited audience** and specify the users and groups to roll the connector out to.

Choose **Create** to deploy the connection. The ServiceNow Knowledge Copilot connector starts indexing content right away.

The following table lists the default values that are set:

| Category | Setting | Default value |
|---|---|---|
| Users | Access permissions | Only people with access to the content in the data source. |
| Users | Map identities | Data source identities mapped using Microsoft Entra IDs. |
| Content | Query string | `active=true^workflow_state=published` |
| Sync | Incremental crawl | Frequency: Every 15 minutes |
| Sync | Full crawl | Frequency: Every day |

## Customize settings

You can customize the default values for the ServiceNow Knowledge connector settings. To customize settings, on the connector page in the admin center, choose **Custom setup**.

### Customize user settings

#### Access permissions

The ServiceNow Knowledge Copilot connector supports the following user search permissions:

- Everyone
- Only people with access to this data source (default)

If you choose **Everyone**, indexed data appears in the search results for all users. If you choose **Only people with access to this data source**, indexed data appears in the search results for users who have access to it.

> [!NOTE]
> If a knowledge article and its knowledge base don't have any `Can Read` user criteria applied, the article appears in the results for everyone in the organization, provided that the `glide.knowman.block_access_with_no_user_criteria` property is set to `false` in your ServiceNow instance. If this property is `true`, or if the service account doesn't have access to the `sys_properties` table (in which case the connector defaults to `true`), articles without user criteria are blocked from appearing in search results.

> [!WARNING]
> If your ServiceNow instance includes knowledge bases in the **HR Service Delivery** (`sn_hr_core`) application scope, verify that the service account has the `sn_hr_core.content_reader` or `sn_hr_core.admin` role. Without one of these roles, the service account can't read HR-scoped user criteria. Because the connector receives empty results rather than an error, it might interpret HR-restricted articles as having no access restrictions and index them as accessible to all users. This situation can result in sensitive HR content appearing in Copilot and Microsoft Search results for unauthorized users.

#### Map identities

By default, ServiceNow maps email IDs to Microsoft Entra ID (UPN or Mail). You can provide a custom mapping formula if your organization uses different identity attributes.

### Customize content settings

#### Query string

ServiceNow uses the following default filter: `active=true^workflow_state=published`.

You can modify this filter to index only specific articles based on your organizational needs. Use ServiceNow's encoded query string builder to create custom filters.

#### Manage properties

You can manage properties in the following ways:

- Add properties to index from ServiceNow.
- Customize the **AccessUrl** property to reflect your organization's URL format.

#### Customize AccessURL property

To define a custom expression for the **AccessURL** property:

1. On the **Content** tab, go to **Manage properties**.
2. In the **Properties** table, select the **AccessURL** property.
3. In the side panel, under **Default expression**, enter your custom expression in the **New default expression** field. Use `${PropertyName}` syntax for dynamic values. For example: `https://instancedomain.service-now.com/sp?id=kb_article&sys_id=${SysId}`.
4. Select **Save changes**.
5. To preview the result, select **Preview data** and scroll to the customized property.

> [!NOTE]
> You must create a new ServiceNow Knowledge connection to customize the **AccessURL** property. Editing an existing connection to customize the schema property isn't currently supported.

You can override the default expression for specific knowledge articles by using rules based on property filters. To add a rule:

1. Under **Set additional rules to configure expressions**, select **Add new rule**.
2. In the rule panel:
    - Choose a filter property (for example, Category).
    - Enter one or more values (comma-separated, case-sensitive).
    - Define the custom expression for those values.
3. Select **Save changes**.

> [!NOTE]
> If multiple rules apply to an item, the first rule in the list is used. Changes take effect after the next full crawl.

### Customize sync intervals

Configure the sync schedule to keep indexed content up to date:

- **Full crawl** — Reindexes all content, removes deleted content, and updates all permissions. The default frequency is daily.
- **Incremental crawl** — Syncs changed content and recomputes permissions for those changed articles and article-level permission changes. Doesn't update user-to-criteria mappings (identity sync) or permissions for articles where knowledge base (parent) level permissions changed. The default frequency is every 15 minutes.

> [!IMPORTANT]
> - Identities (group memberships created between users and user criteria) are only updated during full crawls. Incremental crawls don't update identities or group memberships.
> - During the first full crawl, identity sync runs first, followed by content sync. This ensures that the right permissions are mapped to the ingested items.
> - During subsequent periodic full crawls, content and identity sync happens in parallel.
> - Periodic full crawls are faster than the first full crawl because items already exist in the index. Identity sync uses differential updates, only pushing membership changes to Microsoft Graph.
