<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Workday Setup — Role / Permission Gating

How each step of the Workday simplified-setup flow is gated by role, and the
mechanism used to enforce it. This is the documentation cross-walk for the master
setup checklist ([`tasks.md`](../../../skills/setup/workday/tasks.md)); the
operational enforcement lives in the shared
[`permission-gate.md`](../../../skills/setup/shared/permission-gate.md)
building block, and per-row status transitions are written by
[`checklist-updater.md`](../../../skills/setup/shared/checklist-updater.md).

## Gate mechanisms

Roles in a queryable directory (Entra / Power Platform / Dataverse) are checked
**programmatically**. **Workday Administrator** and **InfoSec/IT** have no
directory we can query here, so their steps are gated by **attestation + captured
evidence** — a flightcheck pass alone never completes them.

| Gate | Meaning | Completion requires |
|------|---------|---------------------|
| `prog` | Programmatic flightcheck check | The checkpoint returns `PASSED`. |
| `manual` | Explicit user action (often portal-only) | User acknowledgement **and** re-verify; a checkpoint pass alone is insufficient. |
| `attest` | Attestation (no queryable directory) | User acknowledgement **and** captured evidence artifact. |

## Role × gated-step matrix

| Role | Gated step(s) | How gated |
|------|---------------|-----------|
| Power Platform Administrator | provision-power-platform-environment (skill-1) | programmatic |
| Environment Maker | install-ess (skill-2), install-workday-extension-pack (skill-5), create-new-topic (skill-6) | programmatic |
| Environment Maker | install-workday-ootb-topics (optional, between skill-5 and skill-6) | programmatic |
| App / Cloud App Admin or App Owner | SSO gallery app + connector config (skill-3) | programmatic |
| App Admin / Cloud App Admin / Priv Role Admin / Global Admin | admin consent (skill-3) | programmatic — attempt; escalate to **manual** if blocked |
| Workday Administrator | configure-workday-tenant (skill-4) | attestation |
| InfoSec/IT | firewall allowlisting (REST + SOAP, skill-5) | attestation |

## The MANUAL / attestation rule (load-bearing)

A `manual`- or `attest`-gated row is **never** auto-completed by a flightcheck
pass. Even when its checkpoint reports `PASSED` or `MANUAL`, the row stays
`in-progress` until the user explicitly acknowledges the step and (for `attest`)
the evidence is captured. This rule is implemented once, in
[`checklist-updater.md`](../../../skills/setup/shared/checklist-updater.md) §U.2,
so every skill records it identically.
