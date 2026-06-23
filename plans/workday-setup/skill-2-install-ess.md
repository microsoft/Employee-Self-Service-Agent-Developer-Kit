# Plan: Skill 2 — `install-ess`

**Role:** Environment Maker · **Net-new skill** · Part of
[Workday Setup](./README.md).
**Depends on:** [`skill-1-provision-power-platform-environment`](./skill-1-provision-power-platform-environment.md).

## Purpose

Install/deploy the base **Employee Self-Service agent** from AppSource into the provisioned
environment — the prerequisite foundation that must exist before the Workday extension pack
can be added.

## Phases

- **Automatable:** post-install verification — confirm the agent + its solution are present
  (reuse onboarding discover/extract logic).
- **Manual (gated):** the AppSource install itself (guided; explicit user action), followed
  by a verification gate.

## Permission gating

- Not an **Environment Maker** → specific named error (shared helper) and **stop**.

## Verification

- Flightcheck ESS solution-installed checkpoint(s), run individually. Updates its own master
  checklist rows.

## Acceptance criteria

- Skill confirms the base ESS agent + solution exist in the target environment, or stops
  with precise remediation.
- The AppSource install is gated and re-verified, never assumed.
