# Plan: Skill 2 — `install-ess`

**Role:** Environment Maker · **Net-new skill** · Part of
[Workday Setup](./README.md).
**Depends on:** [`skill-1-provision-power-platform-environment`](./skill-1-provision-power-platform-environment.md).

## Purpose

Install/deploy the base **Employee Self-Service agent** from AppSource into the provisioned
environment — the prerequisite foundation that must exist before the Workday extension pack
can be added.

## Phases

- **Automatable:** post-install verification — confirm the agent + its solution are present,
  reusing the onboarding discovery logic in **`src/skills/onboarding`** + **`scripts/discover.py`**.
  The base ESS solution **unique name is `msdyn_copilotforemployeeselfservice`** (the IT/HR
  packaged variants are `msdyn_copilotforemployeeselfserviceit` /
  `msdyn_copilotforemployeeselfservicehr` — accept whichever the tenant deployed; this is also the
  topic namespace skill-6 references).
- **Manual (gated):** the AppSource install itself (guided; explicit user action), followed
  by a verification gate.

## Permission gating

- Not an **Environment Maker** → specific named error (shared helper) and **stop**.

## Verification

- Concretize to an **`ESS-SOLN-001`** checkpoint — the ESS solution
  (`msdyn_copilotforemployeeselfservice*`) is installed in the target environment — run
  individually via `--checkpoint`. Updates its own master checklist rows.

## Acceptance criteria

- Skill confirms the base ESS agent + solution exist in the target environment, or stops
  with precise remediation.
- The AppSource install is gated and re-verified, never assumed.
