# ESS ServiceNow Scenarios

This folder contains sample topic definitions and ESS template configurations
(JSON) that customers can use to extend the functionality of their ESS agent
with ServiceNow HRSD, ITSM, and CMDB/Catalog integrations.

## Usage Notes

- Each scenario folder contains a `topic.yaml` (the Copilot Studio topic) and a
  template configuration JSON used by the topic.
- Copy `topic.yaml` into your Copilot topic catalog and ensure the template
  configuration is added to the Employee Self-Service Template Configuration
  table in Dataverse (`msdyn_employeeselfservicetemplateconfigs`).
- Update placeholder values (e.g., `<YOUR_HR_ASSIGNMENT_GROUP_SYS_ID>`) to match
  your ServiceNow environment.
- The topic `.yaml` files include trigger queries (sample prompts). Use those as
  seeds for testing.

## Scenarios

### HRSD (HR Service Delivery)

| Scenario | Description | Sample Prompts |
|----------|-------------|----------------|
| ServiceNowHRSDCreateCase | Create an HR case in ServiceNow HRSD | "I need to create an HR case" / "Open an HR service request" |
| ServiceNowHRSDGetUserCases | List the user's HR cases | "Show me my HR cases" / "What are my open HR cases?" |

### ITSM (IT Service Management)

| Scenario | Description | Sample Prompts |
|----------|-------------|----------------|
| ServiceNowITSMCreateTicket | Create an IT incident ticket | "I need to create an IT ticket" / "I have a technical issue" |
| ServiceNowITSMGetUserTickets | List the user's IT tickets | "Show me my IT tickets" / "What are my open incidents?" |
| ServiceNowITSMGetTicketDetails | Get details of a specific ticket | "What's the status of INC0012345?" / "Check on my IT ticket" |

### Catalog & CMDB

| Scenario | Description | Sample Prompts |
|----------|-------------|----------------|
| ServiceNowBrowseCatalog | Search the service catalog | "What can I request from the IT catalog?" / "Show me available services" |
| ServiceNowCMDBLookup | Look up a configuration item/asset | "Look up my laptop in the CMDB" / "Find asset LAPTOP-12345" |

## Template Configuration Format

Unlike Workday (which uses XML SOAP templates), ServiceNow template configs are
**JSON** documents. The JSON schema includes:

- **Scenario** — unique identifier (primary key)
- **Table** — ServiceNow table name (`incident`, `sn_hr_core_case`, `sc_cat_item`, `cmdb_ci`)
- **Operation** — `CREATE` or `READ`
- **FilterCriteria** — WHERE clause filters
- **SortCriteria** — ORDER BY fields
- **OutputFieldMapping** — maps ServiceNow fields to bot-facing output names
- **UserParameters** — input fields from the user (for CREATE/UPDATE)
- **GlobalParameters** — static values passed with every call

See the individual scenario `*.json` files for complete examples.
