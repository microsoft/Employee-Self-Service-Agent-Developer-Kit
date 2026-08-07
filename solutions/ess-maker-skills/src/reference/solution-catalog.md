# Solution Catalog

This catalog maps each **parent package** to its **child packages**, together with the connection references each child package requires.

> [!NOTE]
>
> This is a static source-package catalog. It describes package dependencies,
> declared connection references, and packaged cloud-flow definitions. It does
> **not** report which solutions are installed in a customer environment,
> whether connection references are bound, or whether connections are active.

**Provenance:** This catalog was generated from the `essvivacopilot` solution
source tree at commit `6c9cf4b4f9a8d5b85505160019ef2d2e7e0ed102`
(reviewed **2026-07-31**). Package relationships and schema values were read
from package manifests, connection-reference definitions from solution
customization XML, and flow names, workflow IDs, connector names, logical
reference names, and runtime sources from packaged workflow definitions.

- A **child** declares its parent via `applicationTargets[].targetApplicationUniqueName`. An **anchor** package declares its own schema name via `AnchorSolutionUniqueName` and has no `applicationTargets`; an anchor targeted by at least one child is listed below as a **parent**.
- **Schema name** is the `msdyn_...` unique name (the key under `DeploymentSettings[]` for a child). It does not always equal `msdyn_` + the package name.
- The **Connector** column shows the friendly name displayed in Power Apps and
  the packaged connection-reference logical name on separate lines.

## Parents

> [!IMPORTANT]
>
> `src/reference/ess-agent-installation/config.json` stores the installation
> selector and Marketplace identities. `scripts/install_ess_agent.py` validates
> every configured application and parent solution unique name against the
> **Parent package**, **Parent schema name**, and **Status** values below.
> Update both files together.

| # | Parent package | Parent schema name | Status | Required connector |
| --- | --- | --- | --- | --- |
| 1 | Employee Self-Service HR | `msdyn_CopilotForEmployeeSelfServiceHR` | Active (CEA bundle) | _(none)_ |
| 2 | Employee Self-Service IT | `msdyn_CopilotForEmployeeSelfServiceIT` | Active (CEA bundle) | Name: `Microsoft 365 Self-Help`<br>Logical name: `msdyn_copilotforemployeeselfserviceit.shared_alchemy.shared-alchemy-8262076a-e778-450b-8a35-5ae815712319` |
| 3 | Employee Self-Service HR | `msdyn_CopilotForEmployeeSelfServiceDAHR` | Active (DA bundle) | _(none)_ |
| 4 | Employee Self-Service IT | `msdyn_CopilotForEmployeeSelfServiceDAIT` | Active (DA bundle) | Name: `Microsoft 365 Self-Help`<br>Logical name: `msdyn_copilotforemployeeselfservicedait.shared_alchemy.shared-alchemy-8262076a-e778-450b-8a35-5ae815712319` |
| 5 | Employee Self-Service Hub | `msdyn_CopilotForEmployeeSelfServiceCore` | Active (CEA bundle) | _(none)_ |
| 6 | Employee Self-Service Hub | `msdyn_CopilotForEmployeeSelfServiceCoreDA` | Active (DA bundle) | _(none)_ |

## Child packages, connection references, and flows

Each row maps a packaged cloud flow to one connection reference declared in that flow's `properties.connectionReferences` block. Flows using multiple connectors therefore appear on multiple rows. Flows without declared connection references are omitted. Blank cells continue the value from the preceding row, providing a vertically grouped view.

| Parent schema | Child package | Child schema | Connector | Flow usage |
| --- | --- | --- | --- | --- |
| `msdyn_CopilotForEmployeeSelfServiceDAHR` | `ESS DA HR ServiceNow HRSD` | `msdyn_EssDAHRServiceNowHRSD` | Name: `Microsoft Dataverse`<br>Logical name: `new_sharedcommondataserviceforapps_41c83` | title: `ESS DA HR ServiceNow HRSD Common Orchestrator`<br>workflowid: `a1f4c28d-6b7c-49b9-a32e-55d8f19c7a03`<br>runtime: `embedded` |
|  |  |  | Name: `ServiceNow`<br>Logical name: `msdyn_copilotforemployeeselfservicedahr.a1f4c28d-6b7c-49b9-a32e-55d8f19c7a03.shared_service-now` | title: `ESS DA HR ServiceNow HRSD Common Orchestrator`<br>workflowid: `a1f4c28d-6b7c-49b9-a32e-55d8f19c7a03`<br>runtime: `invoker` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `new_sharedcommondataserviceforapps_41c83` | title: `ESS DA HR ServiceNow HRSD Get HR Services With COEs for User`<br>workflowid: `b9a7f3c8-1d5e-4e0f-96c3-7b2184d5f219`<br>runtime: `embedded` |
| `msdyn_CopilotForEmployeeSelfServiceDAHR` | `ESS DA HR Workday` | `msdyn_EssDAHRWorkday` | Name: `Microsoft Dataverse`<br>Logical name: `msdyn_sharedcommondataserviceforapps_92b66` | title: `ESS HR Workday`<br>workflowid: `9f1b2c3d-4e5f-6789-abcd-1234567890ab`<br>runtime: `embedded` |
|  |  |  | Name: `Workday`<br>Logical name: `new_sharedworkdaysoap_ff0df` | title: `ESS HR Workday`<br>workflowid: `9f1b2c3d-4e5f-6789-abcd-1234567890ab`<br>runtime: `invoker` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `msdyn_sharedcommondataserviceforapps_92b66` | title: `ESS HR Workday References`<br>workflowid: `8ed25b3a-8a7d-4007-95f5-b81fc662f3ae`<br>runtime: `embedded` |
|  |  |  | Name: `Workday`<br>Logical name: `new_sharedworkdaysoap_ff0df` | title: `WorkdayRESTExecution`<br>workflowid: `9248c265-3050-4aeb-834a-8d90fedf9df5`<br>runtime: `invoker` |
| `msdyn_CopilotForEmployeeSelfServiceDAIT` | `ESS DA IT ServiceNow ITSM` | `msdyn_EssDAITServiceNowITSM` | Name: `ServiceNow`<br>Logical name: `msdyn_copilotforemployeeselfservicedait.cr.w2LCWZTZ` | title: `ESS DA IT ServiceNow ITSM Common Orchestrator`<br>workflowid: `3f7a2b1c-8d6e-4a5b-9c0d-2e3f4a5b6c7d`<br>runtime: `invoker` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `new_sharedcommondataserviceforapps_41c83` | title: `ESS DA IT ServiceNow ITSM Common Orchestrator`<br>workflowid: `3f7a2b1c-8d6e-4a5b-9c0d-2e3f4a5b6c7d`<br>runtime: `embedded` |
|  |  |  |  | title: `ESS DAIT ServiceNow ITSM Get Tickets List`<br>workflowid: `4b2c3d1e-5f6a-7b8c-9d0e-1f2a3b4c5d6e`<br>runtime: `embedded` |
|  |  |  |  | title: `ESS DA IT ServiceNow ITSM Request Body Generator`<br>workflowid: `8c7b6a5d-4e3f-2b1a-0c9d-7e6f5a4b3c2d`<br>runtime: `embedded` |
| `msdyn_CopilotForEmployeeSelfServiceDAIT` | `ESS DA IT Workday` | `msdyn_EssDAITWorkday` | Name: `Microsoft Dataverse`<br>Logical name: `msdyn_sharedcommondataserviceforapps_92b66` | title: `ESS IT Workday`<br>workflowid: `84d6a7c2-5f91-43e8-b3c7-9a21f0d4e6b5`<br>runtime: `embedded` |
|  |  |  | Name: `Workday`<br>Logical name: `new_sharedworkdaysoap_ff0df` | title: `ESS IT Workday`<br>workflowid: `84d6a7c2-5f91-43e8-b3c7-9a21f0d4e6b5`<br>runtime: `invoker` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `msdyn_sharedcommondataserviceforapps_92b66` | title: `ESS IT Workday References`<br>workflowid: `ac166e76-b8fd-4ae0-95cd-ea2942d2517d`<br>runtime: `embedded` |
|  |  |  | Name: `Workday`<br>Logical name: `new_sharedworkdaysoap_ff0df` | title: `WorkdayRESTExecution`<br>workflowid: `b7f07ab6-da94-4e92-a6ef-a7193068ea48`<br>runtime: `invoker` |
| `msdyn_CopilotForEmployeeSelfServiceHR` | `ESS HR ADP` | `msdyn_EssHRADP` | Name: `ADP Employee Self Service`<br>Logical name: `new_sharedadpemployeeselfservi_de34b` | title: `[ADP] Flow - Unified`<br>workflowid: `5a62a319-c943-f111-88b4-7c1e528d11b6`<br>runtime: `invoker` |
| `msdyn_CopilotForEmployeeSelfServiceHR` | `ServiceNow HR` | `msdyn_EssHRServiceNowHRSD` | Name: `Microsoft Dataverse`<br>Logical name: `new_sharedcommondataserviceforapps_41c83` | title: `ESS HR ServiceNow HRSD Common Orchestrator`<br>workflowid: `a1f4c28d-6b7c-49b9-a32e-55d8f19c7a03`<br>runtime: `embedded` |
|  |  |  | Name: `ServiceNow`<br>Logical name: `msdyn_copilotforemployeeselfservicehr.a1f4c28d-6b7c-49b9-a32e-55d8f19c7a03.shared_service-now` | title: `ESS HR ServiceNow HRSD Common Orchestrator`<br>workflowid: `a1f4c28d-6b7c-49b9-a32e-55d8f19c7a03`<br>runtime: `invoker` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `new_sharedcommondataserviceforapps_41c83` | title: `ESS HR ServiceNow HRSD Get HR Services With COEs for User`<br>workflowid: `b9a7f3c8-1d5e-4e0f-96c3-7b2184d5f219`<br>runtime: `embedded` |
| `msdyn_CopilotForEmployeeSelfServiceHR` | `ServiceNow IT` | `msdyn_EssHRServiceNowITSM` | Name: `ServiceNow`<br>Logical name: `msdyn_copilotforemployeeselfservicehr.cr.w2LCWZTZ` | title: `ESS HR ServiceNow ITSM Common Orchestrator`<br>workflowid: `7e2b1c3a-9f4a-4e2a-8b1e-2c3a9f4a8b1e`<br>runtime: `invoker` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `new_sharedcommondataserviceforapps_41c83` | title: `ESS HR ServiceNow ITSM Common Orchestrator`<br>workflowid: `7e2b1c3a-9f4a-4e2a-8b1e-2c3a9f4a8b1e`<br>runtime: `embedded` |
|  |  |  |  | title: `ESS HR ServiceNow ITSM Get Tickets List`<br>workflowid: `2a4c7e1b-3f9a-4b2e-8c1a-7e1b3f9a4b2e`<br>runtime: `embedded` |
|  |  |  |  | title: `ESS HR ServiceNow ITSM Request Body Generator`<br>workflowid: `9f1e2c3a-7b4a-4e2c-8a1e-2c3a7b4a4e2c`<br>runtime: `embedded` |
| `msdyn_CopilotForEmployeeSelfServiceHR` | `ServiceNow Live Agent` | `msdyn_EssHRServiceNowLiveAgent` | Name: `ServiceNow`<br>Logical name: `new_sharedservicenow_4ef05` | title: `ESS HR ServiceNow Live Agent Save Summary`<br>workflowid: `4b3f7e5c-9a1d-4c8e-b6a2-5f9d8c7b6a5e`<br>runtime: `invoker` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `new_sharedcommondataserviceforapps_09a8b` | title: `ESS HR ServiceNow Live Agent Save Summary`<br>workflowid: `4b3f7e5c-9a1d-4c8e-b6a2-5f9d8c7b6a5e`<br>runtime: `embedded` |
| `msdyn_CopilotForEmployeeSelfServiceHR` | `SAP SuccessFactors` | `msdyn_EssHRSuccessFactors` | Name: `SAP OData`<br>Logical name: `new_sharedsapodata_b7454` | title: `SuccessFactors Check User Permissions`<br>workflowid: `d86f46b5-bd1f-4e85-bb13-60b4da317d22`<br>runtime: `embedded` |
|  |  |  |  | title: `SuccessFactors Get Active UserId`<br>workflowid: `dab82937-ccdf-45b6-9406-322aa3782b18`<br>runtime: `embedded` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `msdyn_sharedcommondataserviceforapps_241f6` | title: `SuccessFactors Get User Context`<br>workflowid: `7e728b04-1cdc-453f-966d-186258532203`<br>runtime: `embedded` |
|  |  |  | Name: `SAP OData`<br>Logical name: `new_sharedsapodata_b7454` | title: `SuccessFactors Get User Context`<br>workflowid: `7e728b04-1cdc-453f-966d-186258532203`<br>runtime: `embedded` |
|  |  |  |  | title: `SuccessFactors Role Based Permission Orchestrator`<br>workflowid: `2c6e7a1f-8b2a-4b76-9d3f-42c9e16f5b8e`<br>runtime: `embedded` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `msdyn_sharedcommondataserviceforapps_241f6` | title: `SuccessFactors Run Common Orchestrator`<br>workflowid: `5a4c9f8d-3b77-4e12-9a3f-91f0e8d6c2ab`<br>runtime: `embedded` |
|  |  |  | Name: `SAP OData`<br>Logical name: `new_sharedsapodata_b7454` | title: `SuccessFactors Run Common Orchestrator`<br>workflowid: `5a4c9f8d-3b77-4e12-9a3f-91f0e8d6c2ab`<br>runtime: `invoker` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `msdyn_sharedcommondataserviceforapps_241f6` | title: `SuccessFactors Run Update Orchestrator`<br>workflowid: `f8e2735a-2c41-4f79-9b14-1e4e7c3a90d6`<br>runtime: `embedded` |
|  |  |  | Name: `SAP OData`<br>Logical name: `new_sharedsapodata_b7454` | title: `SuccessFactors Run Update Orchestrator`<br>workflowid: `f8e2735a-2c41-4f79-9b14-1e4e7c3a90d6`<br>runtime: `invoker` |
| `msdyn_CopilotForEmployeeSelfServiceHR` | `Workday` | `msdyn_EssHRWorkday` | Name: `Microsoft Dataverse`<br>Logical name: `msdyn_sharedcommondataserviceforapps_92b66` | title: `ESS HR Workday`<br>workflowid: `9f1b2c3d-4e5f-6789-abcd-1234567890ab`<br>runtime: `embedded` |
|  |  |  | Name: `Workday`<br>Logical name: `new_sharedworkdaysoap_ff0df` | title: `ESS HR Workday`<br>workflowid: `9f1b2c3d-4e5f-6789-abcd-1234567890ab`<br>runtime: `invoker` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `msdyn_sharedcommondataserviceforapps_92b66` | title: `ESS HR Workday References`<br>workflowid: `6e70ebc7-0461-f111-a826-000d3a37207f`<br>runtime: `embedded` |
|  |  |  | Name: `Workday`<br>Logical name: `new_sharedworkdaysoap_ff0df` | title: `WorkdayRESTExecution`<br>workflowid: `9248c265-3050-4aeb-834a-8d90fedf9df5`<br>runtime: `invoker` |
| `msdyn_CopilotForEmployeeSelfServiceIT` | `ServiceNow HR` | `msdyn_EssITServiceNowHRSD` | Name: `Microsoft Dataverse`<br>Logical name: `new_sharedcommondataserviceforapps_41c83` | title: `ESS IT ServiceNow HRSD Common Orchestrator`<br>workflowid: `c3d5c4e2-5f11-4a7e-9f3b-9c57e1d78265`<br>runtime: `embedded` |
|  |  |  | Name: `ServiceNow`<br>Logical name: `msdyn_copilotforemployeeselfserviceit.c3d5c4e2-5f11-4a7e-9f3b-9c57e1d78265.shared_service-now` | title: `ESS IT ServiceNow HRSD Common Orchestrator`<br>workflowid: `c3d5c4e2-5f11-4a7e-9f3b-9c57e1d78265`<br>runtime: `invoker` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `new_sharedcommondataserviceforapps_41c83` | title: `ESS IT ServiceNow HRSD Get HR Services With COEs for User`<br>workflowid: `7d92a3f4-1b4f-42e9-9d52-6a1c3eae0b98`<br>runtime: `embedded` |
| `msdyn_CopilotForEmployeeSelfServiceIT` | `ServiceNow IT` | `msdyn_EssITServiceNowITSM` | Name: `ServiceNow`<br>Logical name: `msdyn_copilotforemployeeselfserviceit.cr.w2LCWZTZ` | title: `    ESS IT ServiceNow ITSM Common Orchestrator`<br>workflowid: `3f7a2b1c-8d6e-4a5b-9c0d-2e3f4a5b6c7d`<br>runtime: `invoker` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `new_sharedcommondataserviceforapps_41c83` | title: `    ESS IT ServiceNow ITSM Common Orchestrator`<br>workflowid: `3f7a2b1c-8d6e-4a5b-9c0d-2e3f4a5b6c7d`<br>runtime: `embedded` |
|  |  |  |  | title: `ESS IT ServiceNow ITSM Get Tickets List`<br>workflowid: `4b2c3d1e-5f6a-7b8c-9d0e-1f2a3b4c5d6e`<br>runtime: `embedded` |
|  |  |  |  | title: `ESS IT ServiceNow ITSM Request Body Generator`<br>workflowid: `8c7b6a5d-4e3f-2b1a-0c9d-7e6f5a4b3c2d`<br>runtime: `embedded` |
| `msdyn_CopilotForEmployeeSelfServiceIT` | `ServiceNow Live Agent` | `msdyn_EssITServiceNowLiveAgent` | Name: `ServiceNow`<br>Logical name: `new_sharedservicenow_4ef05` | title: `ESS IT ServiceNow Live Agent Save Summary`<br>workflowid: `324108e4-1f40-f011-b4cb-6045bd04a751`<br>runtime: `invoker` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `new_sharedcommondataserviceforapps_09a8b` | title: `ESS IT ServiceNow Live Agent Save Summary`<br>workflowid: `324108e4-1f40-f011-b4cb-6045bd04a751`<br>runtime: `embedded` |
| `msdyn_CopilotForEmployeeSelfServiceIT` | `SAP SuccessFactors` | `msdyn_EssITSuccessFactors` | Name: `SAP OData`<br>Logical name: `new_sharedsapodata_b7454` | title: `ESS IT SuccessFactors Check User Permissions`<br>workflowid: `03c24504-d765-45f7-b9db-cc50e8b9439c`<br>runtime: `embedded` |
|  |  |  |  | title: `ESS IT SuccessFactors Get Active UserId`<br>workflowid: `022a5b46-188a-455d-90c2-30d09b07f3f9`<br>runtime: `embedded` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `msdyn_sharedcommondataserviceforapps_241f6` | title: `ESS IT SuccessFactors Get User Context`<br>workflowid: `023c7886-0d29-42bc-8a92-6962e35caf94`<br>runtime: `embedded` |
|  |  |  | Name: `SAP OData`<br>Logical name: `new_sharedsapodata_b7454` | title: `ESS IT SuccessFactors Get User Context`<br>workflowid: `023c7886-0d29-42bc-8a92-6962e35caf94`<br>runtime: `embedded` |
|  |  |  |  | title: `ESS IT SuccessFactors Role Based Permission Orchestrator`<br>workflowid: `3491c2a8-d0c2-4f21-9de4-a86dbcb109d0`<br>runtime: `embedded` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `msdyn_sharedcommondataserviceforapps_241f6` | title: `ESS IT SuccessFactors Run Common Orchestrator`<br>workflowid: `3675542c-3d9c-42b7-85b7-d425ebbacdb4`<br>runtime: `embedded` |
|  |  |  | Name: `SAP OData`<br>Logical name: `new_sharedsapodata_b7454` | title: `ESS IT SuccessFactors Run Common Orchestrator`<br>workflowid: `3675542c-3d9c-42b7-85b7-d425ebbacdb4`<br>runtime: `invoker` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `msdyn_sharedcommondataserviceforapps_241f6` | title: `ESS IT SuccessFactors Run Update Orchestrator`<br>workflowid: `62a2f392-ec98-47e3-8821-754cefa60c2b`<br>runtime: `embedded` |
|  |  |  | Name: `SAP OData`<br>Logical name: `new_sharedsapodata_b7454` | title: `ESS IT SuccessFactors Run Update Orchestrator`<br>workflowid: `62a2f392-ec98-47e3-8821-754cefa60c2b`<br>runtime: `invoker` |
| `msdyn_CopilotForEmployeeSelfServiceIT` | `Workday` | `msdyn_EssITWorkday` | Name: `Microsoft Dataverse`<br>Logical name: `msdyn_sharedcommondataserviceforapps_92b66` | title: `ESS IT Workday`<br>workflowid: `84d6a7c2-5f91-43e8-b3c7-9a21f0d4e6b5`<br>runtime: `embedded` |
|  |  |  | Name: `Workday`<br>Logical name: `new_sharedworkdaysoap_ff0df` | title: `ESS IT Workday`<br>workflowid: `84d6a7c2-5f91-43e8-b3c7-9a21f0d4e6b5`<br>runtime: `invoker` |
|  |  |  | Name: `Microsoft Dataverse`<br>Logical name: `msdyn_sharedcommondataserviceforapps_92b66` | title: `ESS IT Workday References`<br>workflowid: `8a2bd039-81a5-4cfd-9bad-7878a216dad5`<br>runtime: `embedded` |
|  |  |  | Name: `Workday`<br>Logical name: `new_sharedworkdaysoap_ff0df` | title: `WorkdayRESTExecution`<br>workflowid: `c5afa366-eaa3-435f-823e-3c188ebd03a2`<br>runtime: `invoker` |
