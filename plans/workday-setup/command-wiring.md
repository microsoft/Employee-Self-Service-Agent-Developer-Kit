# Plan: Command wiring (retire the monolith)

Route `/connect workday` to the new atomic skills once they exist. Part of
[Workday Setup](./README.md).
**Depends on:** skills 1–6.

## Changes

- **Retire** `src/skills/connect/workday/{step1,step2,step3}.md` and the dual-path
  principles in `connect/SKILL.md` (simplified-only).
- Add a new **orchestrator** that sequences the 6 skills using the
  [master checklist](./master-checklist.md) as a **resume-aware spine** (skip steps already
  verified; resume where the user left off). It **must not advance past a `MANUAL`/attestation
  row on a flightcheck pass alone** — those require explicit user acknowledgement first.
- Route `/connect workday` to the orchestrator.

## Validity fix (called out for challenge)

- `connect/workday/step2.md` conflates SSO-app creation, Workday-tenant admin tasks, and
  connector config into one block — the opposite of atomic. Retiring it removes the
  conflation; the concerns now live in skills 3, 4, and 5 respectively.

## Acceptance criteria

- `/connect workday` drives the new orchestrator end-to-end.
- The old `step1/step2/step3` monolith is removed; no references remain in `connect/SKILL.md`.
- Re-running the command resumes from the first unverified checklist step rather than
  restarting from scratch.

## Out of scope

- Legacy ISU/RaaS path (existing legacy installs keep working via the old reference docs).
