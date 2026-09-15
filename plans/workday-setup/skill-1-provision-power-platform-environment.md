# Plan: Skill 1 — `provision-power-platform-environment`

**Role:** Power Platform Administrator · **Net-new skill** · Part of
[Workday Setup](./README.md).
**Depends on:** [`shared-building-blocks`](./shared-building-blocks.md),
[`flightcheck-single-checkpoint`](./flightcheck-single-checkpoint.md),
[`master-checklist`](./master-checklist.md).

## Purpose

Create/configure the Power Platform environment (with Dataverse and the required Copilot
Studio capacity) that hosts the ESS agent — the foundation the Workday extension pack is
later installed into.

## Phases

- **Automatable:** discover existing environments via **`scripts/discover.py`** + the existing
  **`scripts/flightcheck/pp_admin_client.py`** (`get_environments()` / `get_environment(env_id)`,
  BAP admin API). Verify Dataverse is enabled by reading the environment's
  `properties.linkedEnvironmentMetadata` (a Dataverse-linked environment exposes it). Check
  Copilot Studio capacity from the environment's capacity/licensing properties where the
  pp_admin API exposes them.
- **Manual (gated):** environment creation + capacity allocation in the Power Platform
  admin portal (guided, with explicit user action and a verification gate afterward). If Copilot
  Studio capacity is **not** queryable via pp_admin, this is an **attestation** row, not a silent
  pass.

## Permission gating

- Not a **Power Platform Administrator** → emit the specific named error (via the shared
  permission-gate helper) and **stop**.

## Verification

- **Reuse the two existing fixed checkpoint IDs** already emitted by
  `checks/environment.py`'s `run_environment_checks` — **`ENV-001`** (Power Platform environment
  exists) and **`ENV-002`** (Dataverse database provisioned). Do **not** re-mint them or redefine
  their meaning; this skill drives both to green from `pp_admin_client`
  `linkedEnvironmentMetadata`. Then emit **one** new fixed ID, **`ENV-CAPACITY-001`** — Copilot
  Studio / Copilot capacity available (pp_admin capacity property, else `MANUAL` attestation),
  added to `checks/environment.py`. Run each individually via `--checkpoint <ID>` right after the
  step. Updates its own rows in the master checklist.

## Acceptance criteria

- Skill confirms (programmatically) a usable environment with Dataverse + Copilot Studio
  capacity, or stops with a precise remediation if not.
- Manual creation step is clearly gated and re-verified, never assumed "done".
