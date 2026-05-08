# Troubleshoot issues with the ServiceNow Knowledge connector

Source: https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-troubleshooting

The ServiceNow Knowledge Microsoft 365 Copilot connector enables organizations to index ServiceNow knowledge articles into Microsoft 365 Copilot and search experiences. This article provides troubleshooting information for common errors that you might encounter when you deploy the ServiceNow Knowledge connector.

To verify ServiceNow configuration information and help troubleshoot errors, see [Set up the ServiceNow service for connector ingestion](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-admin-setup).

## Can't find ServiceNow Knowledge articles in Copilot or Microsoft Search

To troubleshoot this issue, try the following steps:

1. Check whether the user searching for the article has the [required permissions to access the ServiceNow Knowledge articles.](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-admin-setup#create-service-account-and-set-up-permissions-to-index-items)
2. Check whether the user is correctly mapped to a Microsoft Entra identity. Mapping problems show as a 2006 error on the **Error** tab. Check the user mapping formula and update it as needed.
3. Check whether an advanced script in any of the user criteria grants access to the article. Advanced scripts aren't currently supported. If you're using advanced scripts, be sure to select **Advanced flow** when you set up the connection and [Set up the REST API](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-admin-setup#set-up-rest-api).
4. Use the [User criteria diagnostics](https://docs.servicenow.com/bundle/washingtondc-servicenow-platform/page/product/knowledge-management/concept/diagnose-knowledge-user-criteria.html) tool in ServiceNow to see if the service account has access to the item in ServiceNow.
5. Use the [Access Analyzer tool in ServiceNow](https://www.servicenow.com/docs/bundle/zurich-platform-security/page/integrate/identity/task/view-permissions-for-a-user.html) to debug further if the service account user missed access to any particular table, field, or record (for example, the `user_criteria` table). If you find any access control list (ACL) or role that blocks access to a required table, field, or record, provide the required roles and ACLs to the service account.
6. If you can't identify the root cause, contact the [Copilot connector support team](mailto:MicrosoftGraphConnectorsFeedback@service.microsoft.com) and provide the following details:
    - Tenant ID
    - Connection ID
    - Article Sys ID
    - Knowledge base Sys ID
    - For the knowledge base, collect:
        - List of user criteria `sys_id` available in the `kb_uc_can_read_mtom` (Who Can Read Knowledge Base) table
        - List of user criteria `sys_id` available in the `kb_uc_cannot_read_mtom` (Who Can't Read Knowledge Base) table
        - List of user criteria `sys_id` available in the `kb_uc_cannot_contribute_mtom` (Who Can't Contribute To Knowledge Base) table
        - List of user criteria `sys_id` available in the `kb_uc_can_contribute_mtom`
    - For the item `sys_id`, share:
        - List of user criteria `sys_id` in the `can_read_user_criteria` field of the article
        - List of user criteria `sys_id` in the `cannot_read_user_criteria` field of the article

    When you provide the required access in ServiceNow, start a full crawl for the configured ServiceNow connection.

## Missing access to certain tables

Without the right access, the crawler might not index all content and might not grant permissions accurately. You must be a ServiceNow admin to troubleshoot this issue.

Use the following steps to validate table permissions by using REST API Explorer:

1. Impersonate the crawling account you created in your ServiceNow instance. Make sure that the account has the following roles: `rest_api_explorer` and `web_service_admin`.
2. Go to **System Web Services** > **REST** > **REST API Explorer**.
3. Select one of the tables mentioned in the error message.
4. Set `sysparm_limit` to 10 (to limit results for testing).
5. Choose **Send**.
6. Review the response:
    - **If you receive a 403 Status Code** and an error message that states that you're not authorized to access the table, see [Grant table access](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/granting-table-access-servicenow-knowledge) to provide table-level access.
    - **If you receive a 200 Status Code** but the response body contains empty results (for example, no fields), row access exists but field-level access is missing. To grant field-level access, see [Grant field-level access](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/granting-table-access-servicenow-knowledge#grant-field-level-access).

If you don't see the table name in the dropdown, you might not have access to the table itself.

Alternatively, you can use a browser to verify access:

1. Open a private browser window.
2. Enter the following URL (replace placeholders with the right values): `https://<instance-url>/api/now/table/<table_name>?sysparm_limit=10`.
3. When prompted, sign in by using the credentials of the crawling account.
4. Review the response. If no response or an error appears, the account doesn't have the necessary access.

When the required access is provided in ServiceNow, start a full crawl for the configured ServiceNow connection.

## Articles without user criteria don't appear in search results

If knowledge articles without user criteria don't appear in Copilot or Microsoft Search results, verify that the service account has read access to the `sys_properties` table in ServiceNow.

The connector reads two system properties to determine how to handle articles without user criteria:

- `glide.knowman.apply_article_read_criteria`
- `glide.knowman.block_access_with_no_user_criteria`

If the service account can't read these properties, the connector defaults to the most restrictive settings. This restriction blocks articles without explicit user criteria from appearing in search results. The admin center shows no error when this restriction happens.

To resolve this issue:

1. Grant the service account read access to the `sys_properties` table. For more information, see [Grant table access to a service account in ServiceNow](https://learn.microsoft.com/en-us/microsoftsearch/granting-table-access-servicenow-knowledge).
2. After granting access, start a full crawl for the configured ServiceNow connection.

> [!NOTE]
> This access applies to both Simple and Advanced flows.

## HR knowledge articles visible to unintended audience

If HR knowledge articles that are restricted in ServiceNow appear in Copilot or Microsoft Search results for users who shouldn't have access, the service account likely lacks the required role to read HR-scoped user criteria.

### Cause

ServiceNow's HR Service Delivery module uses the **Human Resources: Core** (`sn_hr_core`) application scope. This scope enforces a separate scoped ACL on the `user_criteria` table. This ACL requires either the `sn_hr_core.content_reader` or `sn_hr_core.admin` role. Without one of these roles, the service account can query the `user_criteria` table through the global-scope ACL, but HR-scoped user criteria rows are silently filtered out. The connector receives empty results rather than an error, and it might default to granting access to all users for those articles.

### Resolution

To resolve the issue:

1. Assign the `sn_hr_core.content_reader` role to the service account. This role provides the minimum privileges needed to satisfy the HR-scoped ACL on the `user_criteria` table. Alternatively, assign the `sn_hr_core.admin` role for broader scope-level access to all HR Core data.
2. Verify that the service account can read HR-scoped user criteria by querying the following URL as the service account:

    `https://<instance-name>.service-now.com/api/now/table/user_criteria?sysparm_limit=10`

    Confirm that user criteria records associated with HR knowledge bases appear in the response. If the response contains only global-scope user criteria and HR-scoped records are missing, the role assignment didn't take effect.
3. After assigning the role, start a full crawl for the configured ServiceNow connection to re-index permissions.

> [!NOTE]
> The `sn_hr_core.admin` role doesn't include `sn_hr_core.content_reader` in the default ServiceNow role hierarchy. Either role independently satisfies the HR-scoped ACL, but through different mechanisms. For more information, see [Additional roles for HR Service Delivery (HRSD) content](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-admin-setup#additional-roles-for-hr-service-delivery-hrsd-content).

## Issue reading all user criteria from ServiceNow

Sometimes content access is restricted because the service account can't read all user criteria. This issue can happen if you use the `gs.getUserId()` or the `gs.getUser()` function within any user criteria. If you use these functions, update the user criteria to remove them. ServiceNow recommends using the `user_id`.

Also, if you're experiencing performance issues related to the use of the `getAllUserCriteria()` function or are concerned about using a deprecated API, consider using the following alternative script when you [Set up the REST API](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-admin-setup#set-up-rest-api).

```javascript
(function execute (/*RESTAPIRequest*/ request, /*RESTAPIResponse*/ response) {
   var queryParams = request.queryParams;
   var userSysId = queryParams.user ? String(queryParams.user) : null;
   var result = [];
   if (!userSysId) {
       gs.warn("UserCriteriaLoader API: 'user' parameter was not provided in the request.");
       response.setStatus(400);
       return { "error": "User sys_id is required." };
   }
   try {
       var userCriteriaLoader = new sn_uc.UserCriteriaLoader();
       var userCriterias = [];
       var userCriteriaGr = new GlideRecord('user_criteria');
       userCriteriaGr.addQuery('active', true);
       userCriteriaGr.query();
       while (userCriteriaGr.next()) {
           userCriterias.push(userCriteriaGr.getUniqueValue());
       }
       var matchingCriteriaIds = sn_uc.UserCriteriaLoader.getMatchingCriteria(userSysId, userCriterias);
       return matchingCriteriaIds;
   } catch (e) {
       gs.error("UserCriteriaLoader API: Error processing user criteria for user " + userSysId + ". Error: " + e.message);
       response.setStatus(500);
       return {
           error_message: "Error processing user criteria for user " + userSysId,
           error_details: e.message
       };
   }
})(request, response);
```

## Unable to sign in due to single sign-on enabled ServiceNow instance

If your organization uses single sign-on (SSO) to ServiceNow, you might have trouble signing in with the service account. You can bring up a username and password-based authentication by adding `login.do` to the ServiceNow instance URL. For example: `https://<your-organization-domain>.service-now.com./login.do`.

## Can't connect with the ServiceNow instance

A forbidden or unauthorized response in connection status can occur for the following reasons:

- **Incorrect account password:** If you use Basic authentication, the credentials you provided might be incorrect. Check the credentials again. If you use OAuth2.0, verify that the account password is correct and wasn't reset. The ServiceNow Knowledge connector uses an access token fetched on behalf of the service account for the crawl. The access token refreshes every 12 hours. You might need to reauthenticate the connection if you change the password.
- **Table access permissions:** Verify that the service account has the required access to the tables, as described in [Create service account and set up permissions to index items](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-admin-setup#create-service-account-and-set-up-permissions-to-index-items). Verify that the service account has read access to all the tables in the column.
- **The ServiceNow instance is behind a firewall:** The ServiceNow Knowledge connector might not be able to reach your ServiceNow instance if it's behind a network firewall. You must allow access to the connector service. The following table lists the public IP address range for the connector service for each region. Add the IP address to your network allow list.

    | Environment | Region | Range |
    |---|---|---|
    | PROD | North America | 52.250.92.252/30, 52.224.250.216/30 |
    | PROD | Europe | 20.54.41.208/30, 51.105.159.88/30 |
    | PROD | Asia Pacific | 52.139.188.212/30, 20.43.146.44/30 |

## Change the URL of the knowledge article

The ServiceNow Knowledge connector allows you to customize the URL of the knowledge articles as per the needs of your organization. For more information, see [Customize AccessURL property](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-deployment#customize-accessurl-property).

> [!NOTE]
> Currently, you can't edit the URL property for an existing connection. You can only customize the URL when you initially set up the connection. If you have an existing connection, create a new connection and follow the steps to customize the URL.

## Issues with "Only people with access to this data source" permission

### Can't select "Only people with access to this data source"

The **Only people with access to this data source** option might be unavailable if the service account lacks read permissions to the required tables. Make sure that the account can read tables related to user criteria permissions.

### User mapping failures

ServiceNow user accounts that don't have a corresponding Microsoft 365 user in Microsoft Entra ID fail to map. Service accounts and nonuser accounts are expected to fail mapping. You can view mapping failures in the identity stats area of the connection detail window and download logs from the **Error** tab.

## Logout successful window appears when you complete the OAuth process

When you complete the OAuth process, a **Logout successful** window might appear without prompting for ServiceNow credentials.

By default, ServiceNow tries to connect by using Microsoft 365 admin credentials through single sign-on (SSO) from a browser authentication. This default setting can cause the connection to fail. As a result, the **Logout successful** window appears.

To resolve this issue:

1. Open a private browser window and sign in with your ServiceNow credentials.
2. In a new tab, sign in to the Microsoft 365 admin center. This step allows ServiceNow SSO to sign out and switch credentials if needed.
3. Try the OAuth configuration again.

## Issue with OIDC based authorization

Customers with tightened security controls on Entra ID might enable the **Assignment required** option on the Enterprise application registered for OpenID Connect (OIDC). This setting causes the following error during the authorization phase of connector setup:

```
Failed to authenticate using client credentials. Please check the client ID, secret,
and scope configuration. If the issue persists, contact your data source administrator
or Microsoft Support. Error from the data source while getting the token:
Error Description: AADSTS501051: Application '<AppID>'(<App Name>) is not assigned to a
role for the application '<AppID>'(<App Name>).
```

To resolve this issue, disable the option in Microsoft Entra ID:

1. In the Microsoft Entra admin center, go to **Enterprise Apps** > **All apps**.
2. Choose the app you registered for OIDC and choose **Properties**.
3. Turn off **Assignment required**.
4. Choose **Save**.
