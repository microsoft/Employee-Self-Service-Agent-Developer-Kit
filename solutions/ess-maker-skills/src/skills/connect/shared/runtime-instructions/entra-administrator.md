#### Instructions for the Entra administrator

Your organization is connecting the Employee Self-Service (ESS) HR or IT agent to ServiceNow, so employees can create and track HR cases and IT tickets while signed in as themselves. This needs an app registration in Microsoft Entra ID that ServiceNow trusts to identify users. You need the **Global Administrator** or **Cloud Application Administrator** role.

If your organization already has an app registration that ServiceNow uses to verify Microsoft Entra sign-in, for example for ServiceNow Knowledge or single sign-on, check with your ServiceNow administrator before creating another one. ServiceNow allows only one OIDC configuration per Microsoft Entra tenant. See [Coexistence with the Microsoft Graph connector for ServiceNow](https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/declarative-agent-servicenow-hr-it#coexistence-with-the-microsoft-graph-connector-for-servicenow).

**Part 1: Register the app**

1. Sign in to the [Microsoft Entra admin center](https://entra.microsoft.com).
2. Go to **App registrations** and select **New registration**.
3. Enter a name that shows its purpose, for example *ESS ServiceNow sign-in*. Keep the default account type and leave **Redirect URI** empty.
4. Select **Register**.
5. On the app's **Overview** page, copy the **Application (client) ID** and the **Directory (tenant) ID**.

**Part 2: Add the user claims to the token**

1. In the app, select **Token configuration** > **Add optional claim**.
2. Select token type **Access**, then select **aud**, **email**, and **upn**.
3. Select **Add**. If you're asked to turn on the Microsoft Graph email and profile permissions, select the check box and select **Add**.

**Part 3: Allow the Microsoft ServiceNow connector to sign users in**

1. In the app, select **Expose an API**.
2. Next to **Application ID URI**, select **Add**, keep `api://<client ID>`, and select **Save**.
3. Select **Add a scope**. Enter scope name `user_impersonation`, set **Who can consent** to **Admins and users**, enter display names and descriptions such as *Access ServiceNow*, and select **Add scope**.
4. Select **Add a client application**. Enter the client ID of Microsoft's ServiceNow connector, `c26b24aa-7874-4e06-ad55-7d06b1f79b63`, select the `user_impersonation` scope, and select **Add application**.

**Part 4 (only when ServiceNow identifies users by something other than email or UPN; check with your ServiceNow administrator):**
**Send the identifier as a claim**

1. Make sure the identifier, for example an employee or payroll ID, is stored in a Microsoft Entra user attribute for **every** employee who uses ESS with ServiceNow. Populate it through HR provisioning, directory sync, or directly on the user. Employees with an empty value can't sign in.
2. Add a claim that carries that attribute to this app, following [Customize claims issued in the JSON web token (JWT) for enterprise applications](https://learn.microsoft.com/en-us/entra/identity-platform/jwt-claims-customization). Note the claim name, for example `employeeid`.
3. Change the claim's format from the default email format to a format that fits the value. If the format stays email, sign-in fails.
4. If Microsoft Entra returns an error after you add the claim, set `acceptMappedClaims` to `true` in the app's **Manifest** (single-tenant apps), or configure a custom signing key.

**Send back to the maker:** the Application (client) ID, the Directory (tenant) ID, and, if you did Part 4, the claim name. Don't send any secret.
