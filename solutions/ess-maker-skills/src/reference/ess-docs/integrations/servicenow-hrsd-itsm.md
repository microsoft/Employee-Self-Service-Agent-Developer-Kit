# Integrate ServiceNow HRSD and ITSM with your Employee Self-Service deployment

> [!IMPORTANT]
> You need to complete the steps to deploy the Employee Self-Service agent before you can configure this supplemental extension pack.

The Employee Self-Service agent is built on Copilot and uses AI to provide relevant information to employees and take actions on their HR data. If your organization uses a human resource management system, the Employee Self-Service agent requires access to that system to function most effectively.

## Functional synopsis

The Employee Self-Service agent acts as a front-end for consuming information from ServiceNow HRSD and ITSM using the Power Platform connector. The following items are the capabilities enabled for this integration:

- Create an HR case
- Get case details
- Get case updates
- Get user cases
- Get ticket status
- Get ticket details
- Get ticket list
- Create ticket
- Update ticket

## Technical synopsis

[Image: Diagram the high-level components comprising overall solution for the Employee Self-Service agent and ServiceNow HRSD integration.]

This diagram outlines the high-level components comprising overall solution for the Employee Self-Service agent and ServiceNow HRSD integration. There are different activities to be performed as a part of initial deployment and for an ongoing operation. As the solution involves multiple technologies, it's better to spend some time initially in understanding the various components. When you're ready, you can bring in the right stakeholders to set up an environment to deploy and test the Employee Self-Service agent.

## Known issues and limitations

These steps are the known issues and limitations of the Power Platform connector for ServiceNow:

- When using the Create Record action, you can't specify the full record description. The field value is ignored due to ServiceNow REST API limitations.
- The Get Records action might return an "Invalid Table" or other error in Power Apps. For Power Apps implementations the suggested workaround is to use the Get Records action in Power Automate and pass the data back to Power Apps.

For detailed documentation about the connector, see [ServiceNow - Connectors](/connectors/service-now/#known-issues-and-limitations).

## Prerequisites

- Have a ServiceNow HRSD/ITSM instance
- Have a Microsoft 365 tenant
- Install the Employee Self-Service agent
- Activate the **Human Resources Scoped App: Core** plugin (`com.sn_hr_core`) in ServiceNow. This plugin provides the `sn_hr_core_case` table and other HR tables required by HRSD scenarios. To activate: navigate to **System Definition → Plugins**, search for `com.sn_hr_core`, and click **Activate**. On developer instances, this plugin is available but inactive by default.

Refer to the Employee Self-Service agent [deployment guide](deploy-overview-alm.md) for installation of the agent and subscription requirements required for the Employee Self-Service agent.

### Deployment role requirements

|Roles/Persona                                         |Description |Activities performed |Configuration Areas |
|------------------------------------------------------|------------|---------------------|--------------------|
|**ServiceNow Administrator**                          |A user who can perform administrative tasks |Create a service account and assign a role to provide read access to specific table records |ServiceNow |
|**ServiceNow Security Administrator**                 |A user who can configure OAuth |Create OAuth Application Registry – *if using OAuth for ServiceNow connector* |ServiceNow |
|**Application Developer** (*minimum privileged role*) |A user who can register an application |Create an App registration - *if using Microsoft Entra OAuth for ServiceNow connector* |Microsoft 365 admin center |
|**Environment Maker**                                 |A user who can customize Employee Self-Service agent |Configure and customize the Employee Self-Service agent |Microsoft Copilot Studio |

## ServiceNow configuration

This section outlines the tasks an administrator needs to configure in ServiceNow. ServiceNow integration supports several types of authentications:

- Microsoft Entra ID User sign in (recommended for production)
- Microsoft Entra ID OAuth using certificates
- OAuth2
- Basic authentication

> [!NOTE]
> For all security related tasks in ServiceNow, the logged in user with `admin` or `security_admin` role must elevate their access using "Elevate role" option from the profile menu in the top right of navigation bar.

> [!TIP]
> Without elevating access, the new security objects can't be created. If **New** button in the top right of configuration pane is missing, then the role isn't elevated to "`security_admin`".

### Microsoft Entra ID User Sign In

This is the **recommended production method**. Users sign in with their Microsoft work account (Entra ID), and the Power Platform ServiceNow connector obtains a delegated access token. No certificates, no client secrets — only a single Entra app registration is needed.

#### Task 1: Register an application in Microsoft Entra ID

1. Sign into the [Microsoft Entra admin center](https://entra.microsoft.com) as an Application Administrator, Cloud App Administrator, or Global Administrator.
2. Go to **Applications** > **App registrations** > **New registration**.
3. Fill in:
   - **Name:** A meaningful name (e.g., `ESS Copilot - ServiceNow OIDC (contoso)`)
   - **Supported account types:** Accounts in this organizational directory only (Single tenant)
   - **Redirect URI:** Leave blank
4. Select **Register**.
5. Note the **Application (client) ID** and **Object ID** from the overview page.

#### Task 2: Add optional claims

1. In the app registration, go to **Token configuration** > **Add optional claim**.
2. Select **Access** token type.
3. Select **email** and **upn** claims.
4. Select **Add**. If prompted to enable Microsoft Graph permissions, check the box and confirm.

#### Task 3: Expose API scope and pre-authorize the Power Platform connector

1. Go to **Expose an API**.
2. Set **Application ID URI** to `api://{Application (client) ID}`.
3. Select **Add a scope**:
   - **Scope name:** `user_impersonation`
   - **Who can consent:** Admins and users
   - **Admin consent display name:** Access ServiceNow
   - **Admin consent description:** Access ServiceNow on behalf of the user
   - **User consent display name:** Access ServiceNow
   - **User consent description:** Access ServiceNow on your behalf
   - **State:** Enabled
4. Select **Add scope**.
5. Select **Add a client application**:
   - **Client ID:** `c26b24aa-7874-4e06-ad55-7d06b1f79b63` (this is the Power Platform ServiceNow connector)
   - Check the `user_impersonation` scope
6. Select **Add application**.

#### Task 4: Create service principal

The service principal is typically created automatically when the app registration is created. Verify it exists:

1. In the Entra admin center, go to **Enterprise applications**.
2. Search for the app name from Task 1.
3. If it doesn't appear, go back to **App registrations** > your app > **Overview** and note the Application (client) ID. Then use the Azure CLI: `az ad sp create --id {Application (client) ID}`.

#### Task 5: Register OIDC provider in ServiceNow

1. Sign in to the ServiceNow instance as an admin with elevated privileges (**Elevate role** from the profile menu).
2. Navigate to **System OAuth** > **Application Registry**.
3. Select **New** > **Configure an OIDC provider to verify ID tokens**.
4. Fill in:

   | Field | Value |
   |-------|-------|
   | **Name** | A meaningful name (e.g., `Microsoft Entra ID - ESS Copilot`) |
   | **Client ID** | The Application (client) ID from Task 1 |
   | **Client Secret** | `not-used` (this field is required but the value is not used for User Login auth) |

5. For **OAuth OIDC Provider Configuration**, select the search icon and choose the built-in **Azure AD** record. Update it with:

   | Field | Value |
   |-------|-------|
   | **OIDC Metadata URL** | `https://login.microsoftonline.com/{tenant-id}/.well-known/openid-configuration` |
   | **User Claim** | `upn` |
   | **User Field** | `user_name` |

6. Select **Submit** to save the OIDC entity.

> [!NOTE]
> The `upn` → `user_name` mapping requires that ServiceNow users have usernames in UPN format (e.g., `user@contoso.com`). Enterprise instances using Entra Connect or SCIM provisioning typically have this already. Developer instances may need a matching user created manually.

> [!IMPORTANT]
> The `oidc_provider_configuration` table may restrict creating new records via the API on some ServiceNow instances (returns 403). If create fails, update the built-in "Azure AD" configuration record instead. Newer instances and PDIs typically allow creating new records.

### Microsoft Entra ID OAuth using Certificate

This authentication uses app tokens, allowing a registered Microsoft Entra ID application to access ServiceNow with a certificate-based credential. This method requires **two** Entra app registrations and is more complex than User Sign In. Use this method when service-level (non-interactive) authentication is required.

For detailed steps, see [Steps to create Microsoft Entra ID OAuth using Certificates](/connectors/service-now/#steps-to-create-microsoft-entra-id-oauth-using-certificates) in the Power Platform connector documentation.

### OAuth2 authentication - Create an OAuth Application Registry

1. Sign in to the ServiceNow instance that needs to be integrated with the Employee Self-Service agent.
2. Elevate access permissions using **Elevate role**.
3. Select **All** in the top navigation bar.
4. Search for **OAuth** in the search box within dropdown navigation menu.
5. Select **System OAuth > Application Registry** from the search results (if you don't see this option, you don't have sufficient privileges).
6. Select **New** button in the top right corner of the configuration section pane.
7. Select **Create an OAuth API endpoint for external clients**.
8. Fill in the following information for the new application registry:

   | Configuration | Description |
   |---------|---------|
   | **Name** | a meaningful name to identify that this application registry is created for the Employee Self-Service agent |
   | **Client ID** | autogenerated code <br><div class="alert">**Note**</br>This value is used in Microsoft 365 Copilot Connector configuration, if no Advanced Scripting is used. |
   | **Client Secret** | leave it blank to automatically generate a string <br><div class="alert">**Note**</br>This value is used in Microsoft 365 Copilot Connector configuration, if no Advanced Scripting is used. |
   | **Redirect URL** | a required callback URL that the authorization server redirects to </br>For Microsoft 365 Enterprise:</br>`https://gcs.office.com/v1.0/admin/oauth/callback`</br>For Microsoft 365 Government:</br>`https://gcsgcc.office.com/v1.0/admin/oauth/callback` Refer to the note after this table for more information.|
   | **Logo URL** | A URL that contains the image for the application logo |
   | **Active** | Set to active |
   | **Refresh token lifespan** | The number of seconds that a refresh token is valid. </br>By default, refresh tokens expire in 100 days (8,640,000 seconds). Recommended value is 31,536,000 (one year) |
   | **Access token lifespan** | The number of seconds that an access token is valid.</br> Recommended value is 43,200 (12 hours) |
   | **Application** | Global |
   | **Accessible from** | All application scopes |
   | **Client Type** | Integration as a Service |

9. Select **Submit** or **Update** button to save the changes.

### Basic authentication

This method of authentication involves a ServiceNow username and password to authenticate API requests. This method is simple to use and is primarily suggested for testing purposes, as it offers lower security compared to other authentication methods.

### Share connection parameters

The ServiceNow connections are configured by the agent maker which need to be shared with all users so that the users are not prompted for authentication the first time the agent is being used with a ServiceNow connection.

Follow the steps in the [Create and manage connections](/microsoft-copilot-studio/authoring-connections#share-connection-parameters-for-on-behalf-of-obo-authentication) article to share connection parameters for On-Behalf-Of (OBO) authentication.

### Connector preparation

With improvements in the ServiceNow integration, the connector objects should be cleaned up before reinstallation or update to the ServiceNow packages. This cleanup is needed because of platform changes for both Power Platform and Copilot Studio.

### Install ServiceNow HRSD extension pack

The Employee Self-Service agent is designed to have separate extension packs for third-party external system solutions like ServiceNow. As a result, these extension packs must be installed first before starting any configurations or customizations.

The following steps are required to install and enable the ServiceNow HRSD extension pack:

1. **Entitlement**:

   Work with your Employee Self-Service agent private preview product managers for the entitlement process. Once the entitlement process is complete for your tenant, the ServiceNow HRSD extension pack shows up under "Customize" section of the Employee Self-Service agent.

   > [!NOTE]
   > "Entitlement" process is a preview workaround until the extension pack installation is streamlined in Microsoft Copilot Studio.

2. **Install the extension**:

   1. Open the Employee Self-Service agent in Copilot Studio.
   2. Navigate to **Settings**.   
   3. Select **Customize** from the left navigation under **Settings**.
   4. Select **Employee Self-Service Agent in Microsoft 365 Copilot – ServiceNow HR Service Delivery** and select **Install**.
   5. When prompted, update the connections as described by selecting " ..." or **sign in** buttons on the right hand side for ServiceNow connection.
   6. Use the following parameters to complete the configuration (**for Microsoft Entra ID using Certificate**):

      | Feature                  | Description |
      |--------------------------|-------------|
      | **Authentication Type**  | Microsoft Entra ID OAuth using Certificate |
      | **Instance Name**        | The instance name used to identify the ServiceNow Site URL <br>For example:</br>**contoso** – *don't use the full url or domain name, like contoso.service-now.com* |
      | **Tenant ID**            | The tenant ID of the Microsoft Entra tenant |
      | **Client ID**            | The client ID created in Task 3 of [Microsoft Entra ID OAuth using Certificate](#microsoft-entra-id-oauth-using-certificate) |
      | **Resource URI**         | The client ID of the Entra organization created in Task 1 of [Microsoft Entra ID OAuth using Certificate](#microsoft-entra-id-oauth-using-certificate) |
      | **Client Secret**        | The .pfx file of the certificate created in Task 3 of [Microsoft Entra ID OAuth using Certificate](#microsoft-entra-id-oauth-using-certificate) |
      | **Certificate password** | The password of the .pfx file |

   7. Use the following parameters to complete the configuration for **Microsoft Entra ID User Login**:

      | Feature                  | Description |
      |--------------------------|-------------|
      | **Authentication Type**  | Microsoft Entra ID user login |
      | **Instance Name**        | The instance name used to identify the ServiceNow Site URL <br>For example:</br>**contoso** – *don't use the full url or domain name, like contoso.service-now.com* |
      | **Resource URI**         | The client ID of the Entra organization created in Task 1 of [Microsoft Entra ID OAuth using Certificate](#microsoft-entra-id-oauth-using-certificate) |

   8. Use the following parameters to complete the configuration for **OAuth2**:

      | Feature                  | Description |
      |--------------------------|-------------|
      | **Authentication Type**  | OAuth2      |
      | **Instance Name**        | The instance name used to identify the ServiceNow Site URL <br>For example:</br>**contoso** – *don't use the full url or domain name, like contoso.service-now.com* |
      | **Client ID**            | Client ID created in Task 1 |
      | **Client Secret**        | Client secret created in Task 1 |

   9. ServiceNow asks for sign-in again. Use the same account for ServiceNow configutation as you supplied in the previous steps.
   10. Confirm the consent by selecting **Allow**.
   11. The **Microsoft Dataverse** connection is the user account that should be automatically signed in, if not, select **Sign in**.

### Install ServiceNow ITSM extension pack

The Employee Self-Service agent is designed to have separate extension packs for each third party external system solutions like ServiceNow, and so on. As a result, these extension packs must be installed before starting any configurations or customizations.

These steps are required to install and enable the ServiceNow HRSD extension pack:

1. **Entitlement**:

   Work with your Employee Self-Service agent private preview product managers for the entitlement process. Once the entitlement process is complete for your tenant, the ServiceNow HRSD extension pack shows up under "Customize" section of the Employee Self-Service agent.

   > [!NOTE]
   > "Entitlement" process is a preview workaround until the extension pack installation is streamlined in Microsoft Copilot Studio.

2. **Install the extension**:
   1. Open the Employee Self-Service agent in Copilot Studio.   
   2. Navigate to **Settings**.   
   3. Select **Customize** from the left navigation under **Settings**.
   4. Select **Employee Self-Service Agent in Microsoft 365 Copilot – ServiceNow IT Service Management** and select **Install**.
   5. When prompted, update the connections as described by selecting " ..." or **sign in** buttons on the right hand side for ServiceNow connection.
   6. Use the following parameters to complete the configuration for **Microsoft Entra ID using Certificate**:

      | Feature | Description |
      |---------|---------|
      | **Authentication Type** | Use Oauth2 |
      | **Instance Name** | The instance name used to identify the ServiceNow Site URl <br>For example:</br>**contoso** – *don't use the full url or domain name like contoso.service-now.com* |
      | **Tenant Type**   | Tenant ID of the Microsoft Entra tenant |
      | **Client Id** | Client ID created in Task 3 of [Microsoft Entra ID OAuth using Certificate](#microsoft-entra-id-oauth-using-certificate) |
      | **Resource URI** | Client ID created in Task 1 of [Microsoft Entra ID OAuth using Certificate](#microsoft-entra-id-oauth-using-certificate) </br>(Application (client) ID) – not application URI |
      | **Client certificate secret** | The .pfx file created in Task 3 of [Microsoft Entra ID OAuth using Certificate](#microsoft-entra-id-oauth-using-certificate) |
      | **Certificate password**  | The password of the .pfx file |

   7. Use the following parameters to complete the configuration for **Microsoft Entra ID User Login**:

      | Feature                  | Description |
      |--------------------------|-------------|
      | **Authentication Type**  | Microsoft Entra ID user login |
      | **Instance Name**        | The instance name used to identify the ServiceNow Site URL <br>For example:</br>**contoso** – *don't use the full url or domain name, like contoso.service-now.com* |
      | **Resource URI**         | The client ID of the Entra organization created in Task 1 of [Microsoft Entra ID OAuth using Certificate](#microsoft-entra-id-oauth-using-certificate) |

   8. Use the following parameters to complete the configuration for **OAuth2**:

      | Feature                  | Description |
      |--------------------------|-------------|
      | **Authentication Type**  | OAuth2      |
      | **Instance Name**        | The instance name used to identify the ServiceNow Site URL <br>For example:</br>**contoso** – *don't use the full url or domain name, like contoso.service-now.com* |
      | **Client ID**            | Client ID created in Task 1 |
      | **Client Secret**        | Client secret created in Task 1 |

   9. ServiceNow asks for sign-in again. Use the same account used previously for ServiceNow configuration.
   10. Confirm the consent by selecting **Allow**.

## ServiceNow - HRSD

### Topics

The following Topics are available from the ServiceNow HRSD extension pack:

|Serial number |Topics |Description |
|--------------|-------|------------|
| 1  | **ServiceNow HRSD Create Case** | Creating an HR case in ServiceNow. |
| 2  | **ServiceNow HRSD System Create Case** | This topic isn't an editable topic. Create case calls this topic for further processing. |
| 3  | **ServiceNow HRSD Get Case Details** | Gets latest created case details. |
| 4  | **ServiceNow HRSD System Get Case Details** | This topic isn't an editable topic. Get case details calls this topic for further processing. |
| 5  | **ServiceNow HRSD Get Case Updates** | Get case update details in text format.</br> Not as detailed as case details. |
| 6  | **ServiceNow HRSD Get User Cases** | List of user cases |
| 7  | **ServiceNow HRSD System Get Cases List** | This topic isn't an editable topic. Get user cases calls this topic for further processing. |
| 8  | **ServiceNow HRSD System Get Metadata Cached** |  |
| 9  | **ServiceNow HRSD System Common Execution** |  |
| 10 | **ServiceNow HRSD System Case Details Cache Lookup** |  |
| 11 | **ServiceNow HRSD System Graceful Exit**  |  |

### Flows

The following Flows are available from the ServiceNow HRSD extension pack:

|Serial number |Flow                                                    |
|--------------|--------------------------------------------------------|
| 1            | **ServiceNow HRSD Common Create Record**               |
| 2            | **ServiceNow HRSD Common Get Record**                  |
| 3            | **ServiceNow HRSD Common List Records**                |
| 4            | **ServiceNow HRSD Common Orchestrator**                |
| 5            | **ServiceNow HRSD Common Update Record**               |
| 6            | **ServiceNow HRSD Create Case**                        |
| 7            | **ServiceNow HRSD Get Case Details**                   |
| 8            | **ServiceNow HRSD Get Cases List**                     |
| 9            | **ServiceNow HRSD Get HR Services with COEs for User** |

## ServiceNow - ITSM

### Topics

The following Topics are available from the ServiceNow ITSM extension pack:

|Topic                                  |Description |
|---------------------------------------|------------|
|**ServiceNow ITSM Create Ticket**      |This topic takes user input like description, severity, and so on. and sends these details to the corresponding system topic. Successful creation generates another adaptive card with ticket details. |
|**ServiceNow ITSM Get User Tickets**   |This topic fetches the active or closed tickets, and does a quick check on a global variable, which we're using as cache for this data. |
|**ServiceNow ITSM Get Ticket Details** |This topic acquires the *sysID* and passes it down to corresponding system topic. |
|**ServiceNow ITSM Update Ticket** | This topic gets the *sysID* and other necessary input required for the update call. Also validates if the user has necessary permission to update that ticket. |
|**ServiceNow ITSM Get Ticket Updates** |This topic retrieves the latest update of IT support tickets for the user. It fetches the list of tickets and then provides the update related to the latest one. |

### Modify agent starter configurations

For any required modifications to the backend ServiceNow Incident APIs, the starter configurations for each scenario can be adjusted in coordination with updates to the frontend topics.

To access the starter configurations:

1. Navigate to the overview tab within the Employee Self-Service agent and scroll down to the ***Customize*** tab.
2. Select the installed customization titled ***Employee Self Service IT Helpdesk ServiceNow ITSM***.
3. This action redirects you to the installed customization details page, where you can view all the Topics and Flows included in the customization package. Additionally, there's a ***Configuration*** option at the top with a manage button.
4. By selecting the **Manage** button, you're directed to the Dataverse Template Configurations table, which lists all available starter configurations.
5. Select the specific scenario starter configuration. It opens the actual value in the Dynamics 365 webpage in a new tab, which can edit the JSON as needed and save your changes.

### Capabilities for the ServiceNow extension pack

Based on the SNOW connector and public APIs, the Service NOW extension pack includes several capabilities. **The initial version focuses on Incident Management**. Specifically, it offers Create, Read, and Update (CRU) functionalities for managing ServiceNow incidents.

#### Get Ticket Status

This function allows users to retrieve the latest status of a ticket using ServiceNow APIs, enabling seamless integration with existing IT workflows. When users access real-time ticket status information, they can efficiently track the progress of reported issues.

#### Get Ticket Details

The Get Ticket Details feature lets users retrieve comprehensive information about a specific ticket within the ServiceNow platform. This functionality provides user details for attributes like the ticket number, short description, full description, and current state. By providing these details, users can gain a complete understanding of the ticket's context and status, allowing more effective communication and issue resolution.

#### Get Ticket List

The Get Ticket List feature lets users retrieve a history of user tickets. This functionality provides essential details about each ticket, like its unique number, a brief description, the status, and the date of the last update.

#### Create Ticket

Provides user the ability to create a ticket for IT helpdesk support. Users can add attachments to the ticket, letting them provide more context for easier resolution.

#### Update Ticket

The Update Ticket feature allows users to modify existing helpdesk tickets by adding comments and attributes. This functionality is crucial for maintaining clear and concise communication between users and support agents, ultimately enhancing the resolution process.

Users can now add attachments to the ticket, letting them provide more context for easier resolution.

### ServiceNow ITSM starter configurations

These JSON configurations are intended for the ServiceNow APIs within the backend. These configurations facilitate the linkage between input and output variables from and to the bot. Each scenario has a corresponding JSON configuration, enabling extension pack users to adjust the parameters utilized in the APIs without altering anything in the backend workflows. The way the backend interacts with bot topics regarding input and output variables is defined within these configurations.

The starter configurations reside within a custom Dataverse table, created through the Employee Self-Service agent base package upon installation in an environment. Extension packs contribute extra rows to this table, each containing a stringified JSON configuration for a specific scenario. These configurations are retrieved at runtime using the Dataverse connectors within Power Automate flows.

### Understanding configurations naming

- **Scenario**: The name of the scenario used as the identifier of the operation. This item is the primary key for the starter configuration and shouldn't be changed.
- **FilterCriteria**: This criterion is used to filter the ServiceNow table by applying the "Operator" on a specific "FieldName". "VariableName" refers to the name of the variable passed from the bot topics containing the actual value. If this variable isn't mandatory, the bot author may choose not to send it.
- **SortCriteria**: Used to sort the list of records from a ServiceNow Table on "FieldName" by "Operator".
- **Limit**: Maximum number of records to return.
- **Offset**: Starting record index for which to begin retrieving records.
- **DisplaySystemReferences**: Flag that indicates the type of data returned, either the actual values from the DB or the display values of the fields.
- **ExcludeReferenceLinks**: Flag that indicates whether to exclude Table API links for reference fields.
- **OutputFieldMapping**: Used to model the ServiceNow Table API output to JSON understood by the bot. Corresponding "FieldName" is mapped to "OutputName".
- **UserParameters (InputFieldMapping)**: Values of the fields that need to be passed from the user via the bot to the backend flows. Used when creating and updating.
- **GlobalParameters (InputFieldMapping)**: Global values that are consistently passed to the API with each call. Includes essential values such as AssignmentGroup, which remain unchanged in every case.

## References

- [ServiceNow - Connectors](/connectors/service-now/#actions)
- [External ID Token Authentication (OIDC) for Rest APIs - Support and Troubleshooting](https://support.servicenow.com/kb?id=kb_article_view&sysparm_article=KB0720547)
- [ServiceNow Catalog Microsoft 365 Copilot connector | Microsoft Learn](/microsoftsearch/servicenow-catalog-connector#3-authentication-type)

For ServiceNow Knowledge documentation, refer to the following link, which requires ServiceNow logins:

- [Table API](https://www.servicenow.com/docs/bundle/xanadu-api-reference/page/integrate/inbound-rest/concept/c_TableAPI.html)
