# ServiceNow Knowledge — Microsoft 365 Copilot Connector Setup Scripts

Source: https://github.com/microsoft/copilot-servicenow-connector-setup-scripts

Background scripts that automate the ServiceNow configuration steps required for
the [ServiceNow Knowledge Microsoft 365 Copilot connector](https://learn.microsoft.com/en-us/microsoftsearch/servicenow-knowledge-connector). These scripts perform the same setup you would do manually through the
ServiceNow UI, but in a single run.

## Scripts

| Script | Purpose | Related docs |
|--------|---------|-------------|
| `row_level_acl_setup.js` | Creates service account, custom role, and row-level READ ACLs for all required tables | Create service account and set up permissions / Grant table access |
| `field_level_acl_setup.js` | Creates field-level READ ACLs (table.*) for tables where field values are restricted | Grant field-level access |
| `scripted_rest_api_setup.js` | Creates the Scripted REST API endpoint for the Advanced connector flow | Set up REST API |

## Prerequisites

- ServiceNow admin account with `security_admin` role elevated
- Access to System Definition > Scripts - Background

## How to Run

1. Elevate your role to `security_admin` in ServiceNow.
2. Navigate to All > System Definition > Scripts - Background.
3. Copy a script file and paste it into the script editor.
4. Review the CONFIGURATION section at the top of the script. Update values (role name, user ID, etc.) to match your organization's naming conventions if needed.
5. Click Run script.
6. Review the output summary to confirm all steps completed successfully.

### Recommended order

1. `row_level_acl_setup.js` — Run first. Creates the service account, role, and row-level ACLs.
2. Verify — Set a password for the service account, then use a REST client (e.g., curl or Postman) to query a table as the service account:

    ```
    GET https://<instance>.service-now.com/api/now/table/kb_knowledge?sysparm_limit=1
    ```

    Authenticate with the service account credentials (Basic Auth). If rows are returned with field values populated, skip to step 4. If rows are returned but field values are empty, proceed to step 3.

    > **Note**: On Zurich and later releases, the script marks the service account as a machine identity (`identity_type = machine`), which automatically enables "Web service access only". Machine identity accounts cannot be impersonated through the ServiceNow UI — use the REST API to verify access instead.

3. `field_level_acl_setup.js` — Run only if field values are not visible after step 2.
4. `scripted_rest_api_setup.js` — If your ServiceNow instance uses advanced scripts in user criteria (rather than simple user/group-based criteria), you should select the Advanced flow when configuring the connector in the Microsoft 365 admin center. Run this script to create the Scripted REST API endpoint that the connector calls to resolve user criteria at query time.

## Key Features

- **Idempotent** — Safe to run multiple times. Existing records are reused, not duplicated.
- **Non-destructive** — Scripts do not modify, delete, or overwrite existing records.
- **Self-contained** — No external dependencies or network calls outside your ServiceNow instance.
- **Cross-version compatible** — Uses `isValidField()` checks to adapt to different ServiceNow releases.
- **Transparent** — Every action is logged in the output summary for review.

## Configuration

Each script has a clearly marked CONFIGURATION section at the top where you can customize:

- **Role name** — Default: `copilot_connector`
- **Service account user ID** — Default: `microsoft.copilot`
- **Table lists** — Add or remove tables based on your instance requirements
- **Optional standard roles** — `knowledge_admin`, `user_criteria_admin`, `user_admin` (included by default in the row-level script as a safety net; can be removed for minimal-permission setups)

## What the Scripts Do NOT Do

- They do not set service account passwords — the admin must set the password after running the row-level script.
- They do not communicate with any service outside your ServiceNow instance.
- They do not install plugins or create application scopes.
