# Official ESS Samples

Microsoft-supported sample topics, template configurations, and evaluation test
sets for the Employee Self-Service (ESS) agent. These are mirrored from
[microsoft/CopilotStudioSamples](https://github.com/microsoft/CopilotStudioSamples/tree/main/EmployeeSelfServiceAgent)
via `scripts/sync_samples.py` and used as authoritative examples when creating
new topics or template configs.

## Contents

| Folder | Description |
|--------|-------------|
| [servicenow/](./servicenow/) | ServiceNow integrations (HRSD, ITSM, catalog/CMDB) — topic YAML + JSON template configs |
| [workday/](./workday/) | Workday integrations (employee and manager scenarios) — topic YAML + XML SOAP template configs |
| [facilities/](./facilities/) | Facilities management scenarios (tickets, dining, guests, vehicles) |
| [evaluations/](./evaluations/) | CSV test sets (`starter/` and `templated/`) for the Copilot Studio evaluation tool |

## Refreshing the samples

```powershell
python scripts/sync_samples.py          # fetch any new files
python scripts/sync_samples.py --force  # re-download everything
```
