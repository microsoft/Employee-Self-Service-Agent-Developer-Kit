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
| `contractRevision` | positive integer | no (default `1`) | Increment when an existing provider changes its ordered plan in a way the Maker must see. The runner records `acceptedContractRevision` and re-shows the complete plan on mismatch without discarding progress. |
| `provider` | string | yes | Short key, lower-case, no spaces (e.g. `"workday"`). Must match the folder name under `src/skills/connect/{provider}/` and the state folder under `.local/connect/{provider}/`. |
| `displayName` | string | yes | Human name shown to the user (e.g. `"Workday"`). |
| `detect` | object | yes | How the runner's caller decides this lifecycle applies at all — see "Detect block" below. |
| `connectConfig` | string | no | Provider-specific config JSON to pass to FlightCheck as `--connect-config`. Use this when provider state intentionally lives outside `.local/config.json`; the explicit file prevents architecture-specific state from being guessed or merged. |
| `stateMigrationCommand` | string | no | Exact checked-in command that upgrades provider state before the runner reads it. It must be idempotent, atomic, identity-safe, and non-secret. Failure blocks the lifecycle; the runner never replaces the file with blank state. |
| `attestedRoleScope` | string | no (default `"phase"`) | Controls reuse of successful `gateMode: "attested"` role gates. `"phase"` preserves the historical behavior: each mutating phase asks separately. `"lifecycle"` persists one attestation per required role for this exact provider + agent lifecycle and reuses it across later mutating phases and resumes. Programmatic gates are never reused through this field. |
| `planRoles` | array of strings | no | Additional human/admin roles shown in the up-front plan for guided non-mutating phases. Display-only: it does not create a role gate or authorize an action. Providers without this field retain the historical mutating-role-only plan. |
| `phases` | array | yes | Ordered list of phase objects — see "Phase fields" below. Executed strictly in array order; a phase never starts until every phase before it is `done` (or `skipped`, see below). |

### Detect block

```json
"detect": {
  "checkpoint": "WD-PKG-001",
  "meansInstalled": "Passed",
  "meansNotInstalled": "NotConfigured"
}
```

- `checkpoint` — a FlightCheck checkpoint ID whose result tells the caller
  whether the external package/extension already exists in the environment.
- `meansInstalled` — the `status` value (from `flightcheck/runner.Status`)
  that permits installed-package routing. Providers with multiple installed
  flavors must also inspect the checkpoint result and select only a compatible
  lifecycle.
- `meansNotInstalled` — the sole status that permits a from-scratch setup
  route. `Failed`, `Warning`, `Skipped`, `Error`, and unknown statuses are
  remediation/stop outcomes, not evidence that the package is absent.

### Phase fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Stable, internal only — never shown to the user. |
| `label` | string | yes | Plain-language description shown in the up-front plan and the resume checklist (e.g. `"Confirm the Workday extension and its connections are healthy"`). No internal IDs, checkpoint names, or file paths. |
| `checkpoints` | array of strings | yes | One or more FlightCheck checkpoint IDs (or family wildcards, e.g. `"WD-FLOW-*"`) that gate this phase. The phase is `done` only when every listed checkpoint returns a status allowed by `completionStatuses`. |
| `completionStatuses` | array of strings | no | Statuses allowed to complete this phase. Defaults to `["Passed"]`. Add `Manual`, `Warning`, `NotConfigured`, or `Skipped` only when that outcome is genuinely sufficient for this specific phase; acknowledgement alone must not turn missing evidence into a healthy result. |
| `mutates` | boolean | no (default `false`) | `true` if completing this phase changes the live agent (edits a file, pushes a change). Drives the role gate below. |
| `requiredRole` | string | required when `mutates` is `true` | Human-readable role name passed to `permission-gate.md` as `REQUIRED_ROLE` before the phase's action runs. |
| `gateMode` | string | no (default `"attested"`) | `"programmatic"` or `"attested"` — passed to `permission-gate.md` as `GATE_MODE`. Use `"programmatic"` only when `roleQuery` names a real, working query. |
| `roleQuery` | array of strings | required when `gateMode` is `"programmatic"` | The exact command(s) `permission-gate.md` runs as `ROLE_QUERY`. Reuse a checked-in, tested provider query rather than inventing an unverified permission check. |
| `roleQueryPassNames` | array of strings | required when `gateMode` is `"programmatic"` | Role names in the query's result that count as holding `requiredRole` (include the role itself and any role that supersedes it, e.g. `System Administrator`). |
| `actionDoc` | string (path) | no | Path to a provider-owned markdown fragment containing the bespoke steps needed to make the phase's checkpoint(s) pass. It is required whenever the phase needs an action before verification, including non-mutating maker evidence collection. |
| `actionExecution` | string | no (default `"once"`) | `"once"` runs the action until it returns a successful result and then relies on live checkpoint verification. `"every-invocation"` reruns the action before verification on every lifecycle invocation, including a previously completed phase. Use this only for current maker evidence that no supported API can verify. |
| `manualAcknowledgementEvidence` | object | no | Explicit opt-in for a current action's structured evidence to acknowledge a matching `Manual` checkpoint row from the same phase and invocation. Requires `path`, `evidenceObjectPath`, `acceptedRecordStatuses`, and `requiredEvidenceKind`; optional `requiredValues` and `bindings` further bind the exact observation to current provider state. `evidenceObjectPath` is `"evidence"` for a handoff wrapper or `""` when `path` already names the evidence record. Without this field, historical acknowledgement behavior is unchanged. |
| `rollbackLabel` | string | no | Passed to `scripts/checkpoint.py` before a mutating action runs, so the operator has a named restore point. |
| `rollbackPushGlob` | string | no | Static path used when the action always pushes the same local file. The runner restores only this path from the named checkpoint and uses the same exact `push.py --only` value when publishing the rollback. |
| `rollbackPushGlobFromAction` | boolean | no | Set to `true` when the action resolves the pushed path dynamically. The action must return `ACTION_ROLLBACK_PUSH_GLOB`; the runner validates and persists it before checkpoint verification. Do not combine this with `rollbackPushGlob`. |

For an admin-owned high-level phase, one `actionDoc` represents one complete
handoff and one pause boundary. It must bundle every internal checklist item,
the responsible admin role, completion criteria, and requested non-secret
evidence. Internal checklist items are not separate lifecycle phases,
persisted questions, or sequential pause turns.

`manualAcknowledgementEvidence` is valid only when:

- the action returned `applied` or `recorded` in the current invocation;
- the emitted checkpoint status is exactly `Manual`;
- `path` is a safe dot path containing only identifiers and `{phaseId}`, with
  no array indexing, `..`, file path, or external lookup, and resolves to a
  provider-owned object for the current
  `{phaseId}`;
- that object's `status` appears in `acceptedRecordStatuses`;
- `evidenceObjectPath` safely resolves beneath that record (or `""` selects
  the record itself);
- that evidence object has `kind` exactly equal to `requiredEvidenceKind`; and
- that evidence object contains a non-empty `recordedAt`.
- every `requiredValues` entry exactly matches the evidence record; and
- every `bindings` entry resolves a safe relative `evidencePath` beneath the
  evidence record and a safe provider-state `statePath`, and their values are
  equal.

The runner may then persist the normal `checkpointAcknowledgements` entry with
source `matching-action-evidence` without asking a second generic question. It must not
infer acknowledgement from an older action, unrelated evidence, a different
phase, `Warning`, or mismatched evidence. Providers without this field,
including existing Workday contracts, retain the historical prompt.

All configured paths use dot-separated object keys only. Reject arrays,
slashes, `..`, unresolved placeholders, missing values, and non-scalar
comparisons. Bindings are comparisons within the already loaded provider state;
they never read a file, environment variable, or external service.

### Evolving a phase's checkpoint list

When several checkpoint rows share one registered FlightCheck family, put the
family wildcard (for example `SN-DA-HRSD-ENTRA-*`) in `checkpoints`. The
runner invokes the family once, consumes every matching emitted row, and
persists each row under its actual checkpoint ID. A family that emits zero
matching rows is blocking, never an empty success. Pin the intended member IDs
in tests so a future prefix expansion requires an explicit contract review.

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
| `Manual` | Counts toward `done` only when listed in `completionStatuses` and the user explicitly attests, either through the normal acknowledgement prompt or a matching current action acknowledgement contract. |
| `NotConfigured` / `Skipped` | Counts toward `done` only when explicitly listed in `completionStatuses`. |
| `Warning` | Counts toward `done` only when explicitly listed in `completionStatuses` and the user chooses to continue. Matching action evidence never auto-acknowledges a warning. |
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
  "acceptedContractRevision": 1,
  "roleAttestations": {},
  "currentPhase": "agent-wiring",
  "phases": {
    "discovery": {
      "status": "done",
      "lastVerifiedAt": "2026-09-15T14:03:10Z",
      "checkpointResults": { "WD-PKG-001": "Passed", "DV-CONN-001": "Passed", "WD-CONN-012": "Passed" },
      "checkpointAcknowledgements": {}
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
  This plan attestation is not itself a role attestation.
- `acceptedContractRevision` — the provider contract revision whose complete
  plan the Maker accepted. A mismatch re-shows the plan and updates this value
  after acceptance while preserving existing progress and provider evidence.
- `roleAttestations.{requiredRole}` — used only when the contract opts into
  `attestedRoleScope: "lifecycle"`. A valid entry records
  `{verifiedBy: "attested", provider, agentSlug, attestedAt, note}`. It is
  reusable only when `provider`, `agentSlug`, and `requiredRole` still match
  the current lifecycle. A different provider or agent uses a different state
  path and cannot inherit it.
- `phases.{id}.status` ∈ `pending` \| `in-progress` \| `done` \| `blocked`.
- `phases.{id}.lastVerifiedAt` — timestamp of the most recent **live**
  checkpoint run that produced the current `status`. The runner never trusts
  a `done` status without a `lastVerifiedAt` from *this* resume — see
  "Live re-verification on resume" in `lifecycle-runner.md`.
- `phases.{id}.actionApplied` — `true` once the action doc has returned
  `applied` or `recorded`. For `actionExecution: "once"` this prevents an
  idempotent-unsafe action from being repeated; `every-invocation` actions
  still rerun before live verification.
- `phases.{id}.lastActionAt` — timestamp of the most recent successful
  `applied` or `recorded` action.
- `phases.{id}.rollbackPushGlob` — exact action-resolved local path persisted
  when the contract uses `rollbackPushGlobFromAction: true`.
- `phases.{id}.checkpointAcknowledgements` — map keyed by checkpoint ID for
  accepted `Manual`/`Warning` results. Each value records the acknowledged
  status and UTC `acknowledgedAt`. A resume may reuse the acknowledgement only
  when the live status still matches; a changed status requires a new decision.
  Entries sourced from matching action evidence also record `evidencePath`,
  `evidenceKind`, and `evidenceRecordedAt`; all three must still match current
  provider evidence on resume.
- Providers may add `phaseHandoffs.{phaseId}` (or an equivalently named
  provider-owned object) for one bundled admin return per high-level phase.
  Do not model each internal checklist item as a separate persisted question
  or phase. The shared runner preserves these provider-owned records but does
  not mark phases complete from them.

The `agentSlug` and state-file path are mandatory isolation boundaries. A
provider may be connected to multiple agents in one workspace; no agent may
reuse another agent's progress or checkpoint results.

### Lifecycle-scoped attested roles

`attestedRoleScope: "lifecycle"` is an explicit provider opt-in for UX role
confirmation only:

- The first mutating phase requiring a role runs the normal attested
  `permission-gate.md` flow.
- On pass, the runner persists the returned evidence under
  `roleAttestations.{requiredRole}` with the exact provider and agent slug.
- Later mutating phases requiring the same role, and later resumes of the same
  lifecycle state, reuse that evidence without asking again.
- A missing, malformed, non-attested, wrong-provider, wrong-agent, or
  wrong-role entry is invalid and the gate must ask again.
- Explicit lifecycle reset/reinitialization must remove `roleAttestations`
  together with the lifecycle state. Plan reset alone must not leave a role
  attestation behind.
- `gateMode: "programmatic"` always executes its role query. A stored attested
  role never bypasses a programmatic gate or its fallback behavior.

This reuse does not authorize a mutation by itself, complete a phase, replace
the phase's explicit mutation confirmation, or replace maker evidence and
checkpoint acknowledgement.

### Action result vocabulary

Provider action documents return one explicit result:

- `ACTION_RESULT = "applied"` — a mutation or verified no-op completed.
- `ACTION_RESULT = "recorded"` — non-mutating evidence was captured.
- `ACTION_RESULT = "waiting"` — a delegated admin operation or question is
  still pending. The phase remains resumable `in-progress`, provider-owned
  evidence is preserved, and checkpoints do not run.
- `ACTION_RESULT = "cancelled"` — the maker declined or is unavailable.

Neither `applied` nor `recorded` completes a phase by itself. The phase's live
checkpoints and `completionStatuses` remain authoritative.

---

## Round-trip contract

Any file that touches the state file must:

1. **Read** the existing file first (it may hold progress from an earlier
   turn or an earlier `/connect` session).
2. **Merge** — update only the phase(s) it just ran; never drop other phases'
   recorded state.
3. **Write** the merged object back immediately (not batched) — the same
   durability rule `checklist-updater.md` applies to the setup checklist.
