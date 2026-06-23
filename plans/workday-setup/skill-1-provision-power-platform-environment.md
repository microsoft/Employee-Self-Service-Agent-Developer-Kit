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

- **Automatable:** discover existing environments (reuse `discover.py`); verify Dataverse
  is enabled and Copilot Studio capacity is available.
- **Manual (gated):** environment creation + capacity allocation in the Power Platform
  admin portal (guided, with explicit user action and a verification gate afterward).

## Permission gating

- Not a **Power Platform Administrator** → emit the specific named error (via the shared
  permission-gate helper) and **stop**.

## Verification

- Flightcheck `ENV-*` checkpoints, run individually via `--checkpoint <ID>` right after the
  step. Updates its own rows in the master checklist.

## Acceptance criteria

- Skill confirms (programmatically) a usable environment with Dataverse + Copilot Studio
  capacity, or stops with a precise remediation if not.
- Manual creation step is clearly gated and re-verified, never assumed "done".
