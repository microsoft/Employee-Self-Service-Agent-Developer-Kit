# Connect Lifecycle — Provider Contract Schema (Shared)

This file documents the **canonical shape** of a provider's connect-lifecycle
contract, read by the generic runner (`lifecycle-runner.md`). It is a
*reference doc*, not an executable fragment — there are no Message blocks here.

A **provider contract** is what makes the runner reusable across integrations:
Workday, ServiceNow, SuccessFactors, or any future ISV each supply their own
contract file plus their own action fragments for steps that change the
agent. The runner itself contains no integration-specific logic — it only
reads a contract, runs the checkpoints it names, and renders results.

**Canonical contract file:** `src/skills/connect/{provider}/contract.json`
**Canonical state file (per agent):**
`.local/connect/{provider}/agents/{agentSlug}/lifecycle.json`

---

## Contract fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `provider` | string | yes | Short key, lower-case, no spaces (e.g. `"workday"`). Must match the folder name under `src/skills/connect/{provider}/` and the state folder under `.local/connect/{provider}/`. |
| `displayName` | string | yes | Human name shown to the user (e.g. `"Workday"`). |
| `detect` | object | yes | How the runner's caller decides this lifecycle applies at all — see "Detect block" below. |
| `phases` | array | yes | Ordered list of phase objects — see "Phase fields" below. Executed strictly in array order; a phase never starts until every phase before it is `done` (or `skipped`, see below). |

### Detect block

```json
"detect": {
  "checkpoint": "WD-PKG-001",
  "meansInstalled": "Passed"
}
```

- `checkpoint` — a FlightCheck checkpoint ID whose result tells the caller
  whether the external package/extension already exists in the environment.
- `meansInstalled` — the `status` value (from `flightcheck/runner.Status`)
  that counts as "installed." Any other status (including `Failed` or
  `NotConfigured`) means "not installed" — the caller should not invoke this
  lifecycle and should fall back to its own from-scratch setup flow.

### Phase fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `connectConfig` | string | no | Provider-specific config JSON to pass to FlightCheck as `--connect-config`. Use this when provider state intentionally lives outside `.local/config.json`; the explicit file prevents architecture-specific state from being guessed or merged. |
| `id` | string | yes | Stable, internal only — never shown to the user. |
| `label` | string | yes | Plain-language description shown in the up-front plan and the resume checklist (e.g. `"Confirm the Workday extension and its connections are healthy"`). No internal IDs, checkpoint names, or file paths. |
| `checkpoints` | array of strings | yes | One or more FlightCheck checkpoint IDs (or family wildcards, e.g. `"WD-FLOW-*"`) that gate this phase. The phase is `done` only when every listed checkpoint returns a status allowed by `completionStatuses`. |
| `completionStatuses` | array of strings | no | Statuses allowed to complete this phase. Defaults to `["Passed"]`. Add `Manual`, `Warning`, `NotConfigured`, or `Skipped` only when that outcome is genuinely sufficient for this specific phase; acknowledgement alone must not turn missing evidence into a healthy result. |
| `mutates` | boolean | no (default `false`) | `true` if completing this phase changes the live agent (edits a file, pushes a change). Drives the role gate below. |
| `requiredRole` | string | required when `mutates` is `true` | Human-readable role name passed to `permission-gate.md` as `REQUIRED_ROLE` before the phase's action runs. |
| `gateMode` | string | no (default `"attested"`) | `"programmatic"` or `"attested"` — passed to `permission-gate.md` as `GATE_MODE`. Use `"programmatic"` only when `roleQuery` names a real, working query. |
| `roleQuery` | array of strings | required when `gateMode` is `"programmatic"` | The exact command(s) `permission-gate.md` runs as `ROLE_QUERY`, and the role name(s) that count as a pass. Copy an existing, already-proven query rather than inventing a new one (e.g. the Dataverse security-role check `src/skills/setup/workday/install-workday-extension-pack.md` section P5.0 uses for "Environment Maker"). |
| `roleQueryPassNames` | array of strings | required when `gateMode` is `"programmatic"` | Role names in the query's result that count as holding `requiredRole` (include the role itself and any role that supersedes it, e.g. `System Administrator`). |
| `actionDoc` | string (path) | required when `mutates` is `true` | Path to a provider-owned markdown fragment containing the bespoke steps needed to make the phase's checkpoint(s) pass (e.g. editing a topic file and pushing it). The runner reads and follows this file; it contains its own Message blocks and is written by the provider, not the runner. |
| `rollbackLabel` | string | no | Passed to `scripts/checkpoint.py` before a mutating action runs, so the operator has a named restore point. |
| `rollbackPushGlob` | string | no | Required with `rollbackLabel` when the action pushes a local file. The runner restores only this path from the named checkpoint and uses the same exact `push.py --only` glob when publishing the rollback. |

### Evolving a phase's checkpoint list

FlightCheck may later ship purpose-built "connect lifecycle" scoped profiles
that replace a phase's individual checkpoint list with one pre-composed
check. Until a profile exists, a contract simply lists the individual
checkpoints that cover the same ground today — there's no separate field for
this; it's just how `checkpoints` is populated in the meantime. When a
consolidated profile ships, update the phase's `checkpoints` list to use it.

Never mark a phase `done` because a future profile is "assumed" to pass —
only a real checkpoint run (or a real, attested manual step) advances a
phase.

---

## Phase status rules

Reuses the exact `Status` values `flightcheck/runner.py` already defines —
this schema does not invent a parallel status vocabulary:

| Checkpoint status | Phase effect |
|---|---|
| `Passed` | Counts toward `done`. |
| `Manual` | Counts toward `done` only when listed in `completionStatuses` and the user explicitly attests. |
| `NotConfigured` / `Skipped` | Counts toward `done` only when explicitly listed in `completionStatuses`. |
| `Warning` | Counts toward `done` only when explicitly listed in `completionStatuses` and the user chooses to continue. |
| `Failed` / `Error` | Blocks the phase. The runner shows the remediation and stops advancing; the user retries after fixing it, or exits and resumes later. |

A phase is `done` only when **every** checkpoint's current status appears in
that phase's `completionStatuses` (default `Passed`) and any required
acknowledgement is complete. Partial or unavailable evidence leaves the phase
`in-progress`; `Failed`/`Error` blocks it.

---

## State file shape

```json
{
  "provider": "workday",
  "agentSlug": "employee-self-service-hr",
  "attested": true,
  "attestedAt": "2026-09-15T14:02:00Z",
  "currentPhase": "agent-wiring",
  "phases": {
    "discovery": {
      "status": "done",
      "lastVerifiedAt": "2026-09-15T14:03:10Z",
      "checkpointResults": { "WD-PKG-001": "Passed", "DV-CONN-001": "Passed", "WD-CONN-012": "Passed" }
    },
    "agent-wiring": {
      "status": "pending",
      "actionApplied": false,
      "checkpointResults": {}
    },
    "validation": { "status": "pending", "checkpointResults": {} }
  }
}
```

- `attested` — `true` once the user has seen the up-front plan (phase labels +
  required roles) and agreed to proceed. Set once; never reset by a resume.
- `phases.{id}.status` ∈ `pending` \| `in-progress` \| `done` \| `blocked`.
- `phases.{id}.lastVerifiedAt` — timestamp of the most recent **live**
  checkpoint run that produced the current `status`. The runner never trusts
  a `done` status without a `lastVerifiedAt` from *this* resume — see
  "Live re-verification on resume" in `lifecycle-runner.md`.
- `phases.{id}.actionApplied` — mutating phases only; `true` once the
  action doc has been followed at least once (so a resume doesn't re-apply an
  idempotent-unsafe action; it re-verifies instead).

The `agentSlug` and state-file path are mandatory isolation boundaries. A
provider may be connected to multiple agents in one workspace; no agent may
reuse another agent's progress or checkpoint results.

---

## Round-trip contract

Any file that touches the state file must:

1. **Read** the existing file first (it may hold progress from an earlier
   turn or an earlier `/connect` session).
2. **Merge** — update only the phase(s) it just ran; never drop other phases'
   recorded state.
3. **Write** the merged object back immediately (not batched) — the same
   durability rule `checklist-updater.md` applies to the setup checklist.
