<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# DA Workday Connect - Roles and evidence

Agent installation belongs to
[`foundation-setup`](../../../skills/foundation-setup/SKILL.md). The active
Workday lifecycle belongs to
[`connect/workday`](../../../skills/connect/workday/SKILL.md).
This branch is DA-only; CEA guidance is maintained on `main-ca`.

## Responsibilities

| Operator | Work | Evidence |
| --- | --- | --- |
| Maker | Verify the selected agent/environment, approve supported package/runtime changes, create connector connections, configure flow attachment and parameter sharing, and run the maker smoke test | Controller verification against the exact target, explicit scoped approval, and the required maker confirmations |
| Microsoft Entra application administrator | Identify and configure the exact Workday enterprise application, SAML settings, certificate, and related application settings | Completed Entra administrator workbook validated by the controller |
| Workday administrator | Configure the tenant's federation, API client, authentication policy, and required access | Completed Workday administrator workbook validated by the controller |

Follow the detailed
[`Entra handoff`](../../../skills/connect/workday/provision-entra-app.md) and
[`Workday handoff`](../../../skills/connect/workday/configure-tenant.md) for the
required portal actions and exact accepted answers. The maker does not need to
sign in to Microsoft Graph to deliver the Entra administrator handoff.

## Approval and completion

- Explain authentication prompts and reuse the recorded maker and tenant.
- Show the exact target and supported changes before mutation. Changed scope
  invalidates the previous approval.
- Do not infer permissions from a display name or from an administrator's role
  claim. Diagnose a blocked operation using its actual API, CLI, or script
  evidence and provide the applicable recovery guidance.
- A role claim, a generic "done", or an uploaded workbook alone does not
  complete a phase. Parse and validate the required evidence, and reread the
  target after automated changes.
- Portal confirmations and manual validation remain manual evidence; do not
  describe them as independently API-verified or as published-employee sign-off.

The controller owns the sole lifecycle state at
`.local/connect/workday-da/config.json`. See its
[`state contract`](../../../skills/connect/workday/shared/config-schema.md).
There is no master setup checklist or Markdown state mirror.
