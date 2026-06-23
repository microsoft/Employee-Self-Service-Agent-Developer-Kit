# Plan: Master setup checklist + Workday flightcheck checkpoints

The single, trackable checklist spanning all 6 skills, plus the new Workday-specific
flightcheck checkpoints and the role-gating matrix. Part of
[Workday Setup](./README.md).
**Depends on:** [`shared-building-blocks`](./shared-building-blocks.md) (checklist updater),
[`flightcheck-single-checkpoint`](./flightcheck-single-checkpoint.md) (atomic verification).

## Master checklist

One `tasks.md` spanning all 6 skills + manual prerequisites. Columns:
**Step | Role | Skill | Automatable? | Flightcheck checkpoint | Status**.

- Each skill updates **its own rows** via the shared checklist-updater.
- Each row links to a checkpoint runnable in isolation (`--checkpoint <ID>`).
- Explicit gated/manual rows for: SSO gallery app, admin consent (consent-capable role;
  escalate if blocked), all Workday-admin tenant tasks, AppSource install, firewall
  allowlisting **(REST + SOAP, InfoSec/IT — gates skill-5 functional check)**.

## New Workday flightcheck checkpoints

Add to `scripts/flightcheck/runner.py` (+ the checkpoint registry from
[`flightcheck-single-checkpoint`](./flightcheck-single-checkpoint.md)) +
`src/reference/ess-docs/flightcheck/validation-matrix.md`, aligned to the skills:

| Skill | Checkpoints |
|-------|-------------|
| skill-1 | `ENV-*` |
| skill-2 | ESS solution-installed |
| skill-3 | `AUTH-*` / new `WD-AUTH-*` + `WD-ASSIGN-*` (enterprise-app assignment) |
| skill-4 | new `WD-TENANT-*` / `WD-API-CLIENT-*` |
| skill-5 | new `WD-PKG-*`, `WD-CONN-*`, `WD-CONN-AUTH-*`, `WD-REST-*`, `WD-FLOW-*`, `WD-NET-*` |
| skill-6 | `TOPIC-*` |

- **Do NOT reuse the legacy `WD-ENV-*` / `WD-WF-*` checkpoints for the simplified path** —
  they test ISU/RaaS artifacts that simplified setup removes and are skipped on simplified
  installs (reusing them yields false failures / N/A noise). Define the new simplified-only IDs
  above instead.
- Preserve `MANUAL` status for non-automatable Workday-admin steps (reports what it can, does
  not fail readiness). **A `MANUAL`/attestation checkpoint never auto-completes its checklist
  row** — the row needs an explicit user acknowledgement (+ captured artifact) to reach *done*.

## Permission / role gating (named error + stop)

Gating mechanism differs: Entra / Power Platform / Dataverse roles are checked
**programmatically**; **Workday Administrator** and **InfoSec/IT** have no queryable directory
here → **attestation + captured evidence**.

| Role | Gated step | How gated |
|------|-----------|-----------|
| Power Platform Administrator | provision-power-platform-environment | programmatic |
| Environment Maker | install-ess, install-workday-extension-pack, create-new-topic | programmatic |
| App / Cloud App Admin or App Owner | SSO gallery app + connector config (entra-app) | programmatic |
| App Admin / Cloud App Admin / Priv Role Admin / Global Admin | admin consent (attempt; escalate to manual if blocked) | programmatic |
| Workday Administrator | configure-workday-tenant | attestation |
| InfoSec/IT | firewall allowlisting (REST + SOAP; manual row) | attestation |

## Acceptance criteria

- The checklist renders every step with its role, skill, automatable flag, checkpoint, and
  live status; skills update only their own rows.
- Every non-manual row maps to a checkpoint that runs in isolation; manual rows are clearly
  marked and never auto-completed.
