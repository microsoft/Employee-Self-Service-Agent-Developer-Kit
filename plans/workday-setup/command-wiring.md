# Plan: Command wiring (retire the monolith)

Route `/connect workday` to the new atomic skills once they exist. Part of
[Workday Setup](./README.md).
**Depends on:** skills 1–6.

## Current routing surface (what exists today)

- **`src/skills/connect/step1.md` is the actual `/connect workday` dispatcher.** It branches on
  checklist state and routes to `connect/workday/{step1,step2,step3}.md`, and on first run copies
  the template **`src/skills/connect/workday/tasks.md`** → working copy
  **`my/connect/workday/tasks.md`** (state files live under `my/connect/workday/`).
- `src/skills/connect/SKILL.md` holds the **dual-path** (simplified vs legacy ISU/RaaS)
  principles.

## Changes

- **Introduce the `setup` orchestrator** at **`src/skills/setup/SKILL.md`** + **`src/skills/setup/
  workday/`**, sequencing the 6 skills using the [master checklist](./master-checklist.md) as a
  **resume-aware spine** (skip steps already verified; resume where the user left off). It **must
  not advance past a `MANUAL`/attestation row on a flightcheck pass alone** — those require
  explicit user acknowledgement first. Its checklist template is
  **`src/skills/setup/workday/tasks.md`** rendered to **`my/setup/workday/tasks.md`** (mirrors the
  existing `my/connect/workday/` convention).
- **Re-point the dispatcher:** change the Workday branch of **`src/skills/connect/step1.md`** to
  invoke the `setup` orchestrator instead of `connect/workday/step1-3`.
- **Retire** `src/skills/connect/workday/{step1,step2,step3}.md` and the dual-path principles in
  `connect/SKILL.md` (simplified-only). Migrate any still-needed derivations (e.g. the SOAP
  host-pattern mapping in `step1.md`) into the relevant skill before deleting.
- Keep **`/connect workday`** as the user-facing entry point (routes through the re-pointed
  dispatcher to the orchestrator).

## Validity fix (called out for challenge)

- `connect/workday/step2.md` conflates SSO-app creation, Workday-tenant admin tasks, and
  connector config into one block — the opposite of atomic. Retiring it removes the
  conflation; the concerns now live in skills 3, 4, and 5 respectively.

## Acceptance criteria

- `/connect workday` drives the new `setup` orchestrator end-to-end (via the re-pointed
  `connect/step1.md` dispatcher).
- The old `connect/workday/step1/step2/step3` monolith is removed; no references remain in
  `connect/step1.md` or `connect/SKILL.md`; needed derivations were migrated first.
- Re-running the command resumes from the first unverified checklist step (`my/setup/workday/
  tasks.md`) rather than restarting from scratch.

## Out of scope

- Legacy ISU/RaaS path (existing legacy installs keep working via the old reference docs).
