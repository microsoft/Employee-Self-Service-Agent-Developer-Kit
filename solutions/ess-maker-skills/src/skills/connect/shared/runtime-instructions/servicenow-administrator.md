#### Instructions for the ServiceNow administrator

Your organization is connecting the Employee Self-Service (ESS) HR or IT agent to ServiceNow, so employees can create and track HR cases and IT tickets while signed in as themselves. ServiceNow needs to trust Microsoft Entra ID sign-in and match each signed-in employee to their ServiceNow user record. You need the `admin` or `security_admin` role.

ServiceNow allows only one OIDC configuration per Microsoft Entra tenant. If one already exists for your tenant, for example for the Microsoft Graph connector or single sign-on, don't change it. See [Coexistence with the Microsoft Graph connector for ServiceNow](https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/declarative-agent-servicenow-hr-it#coexistence-with-the-microsoft-graph-connector-for-servicenow) and the [ServiceNow Knowledge connector guidance](https://learn.microsoft.com/en-us/microsoftsearch/servicenow-knowledge-connector).

**Values from the maker:** Client ID `<client ID>`, tenant ID `<tenant ID>`, and the custom claim name if the Entra administrator added one.

1. Sign in to `https://<instance>.service-now.com`.
2. From the profile menu at the top right, select **Elevate role**, select `security_admin`, and select **Update**. If the **New** button is missing in the next steps, the role isn't elevated.
3. Select **All**, search for *OAuth*, and select **System OAuth** > **Application Registry**.
4. Select **New** > **Configure an OIDC provider to verify ID tokens**.
5. Fill in the form:
   - **Name:** a name that shows it's for ESS, for example *ESS Microsoft Entra ID*.
   - **Client ID:** `<client ID>`.
   - **Client Secret:** any value. It isn't used.
   - **Scope Restriction:** Broadly scoped.
6. Next to **OAuth OIDC Provider Configuration**, select the search icon, then **New**. Fill in:
   - **OIDC Provider:** a name for your Microsoft Entra tenant, for example *Microsoft Entra ID - Contoso*.
   - **OIDC Metadata URL:** `https://login.microsoftonline.com/<tenant ID>/.well-known/openid-configuration`. Don't use the `/v2.0` URL from Entra's **Endpoints** page.
   - **OIDC Configuration Cache Life Span:** 120.
   - **Application:** Global, if the field is shown.
   - **User Claim:** `upn` or `email`, whichever your user records use to identify users, or the custom claim name from the Entra administrator.
   - **User Field:** the user record field that holds exactly that value for every employee, for example **Email** for `email`, or the field that stores the UPN or employee ID.
   - **Enable JTI claim verification:** off.

   Select **Submit**.
7. Back on the application registry form, confirm that the new configuration is selected, and select **Submit**.
8. **HR agent only:** employees who use HR scenarios need one of the roles `sn_hr_core.basic`, `sn_hr_core.manager`, or `sn_hr_core.admin`.

**Send back to the maker:** confirmation that the configuration is saved, and the User Claim and User Field you used.
