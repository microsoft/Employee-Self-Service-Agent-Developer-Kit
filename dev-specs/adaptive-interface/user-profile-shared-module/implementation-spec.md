# User Profile Shared Module - Implementation Specification

## 1. Purpose

Implement a reusable user-profile module for the ESS Maker Kit that allows
existing and future skills to adapt their maker-facing responses using these
preferences:

- Response format
- Detail level
- Tone of voice
- Confirmation frequency
- Maximum response length
- Proactive suggestions

The module centralizes profile storage, validation, resolution, and behavior
rules. This implementation delivers the shared module and its future
integration contract only. Existing skills will consume the resolved profile
in a later onboarding phase; they are not modified by this implementation.

## 2. Scope decision

The initial implementation uses a local profile for the maker using the current
kit checkout.

- The profile is stored under `.local/`.
- It applies across all agents and all onboarded skills in the checkout.
- It is not stored inside an agent workspace and is not agent-specific.
- It is not committed to Git.
- It is not synchronized across machines, repository clones, Codespaces, or
  other development environments.
- It is not uploaded to Copilot Studio or any customer service.
- It does not contain a UPN, email address, employee ID, or other raw user
  identifier.
- The initial implementation assumes that a local checkout is used by one maker.
  Multiple operating-system users sharing the same checkout are not isolated
  from one another.

Cloud synchronization, shared-workstation identity isolation, and runtime ESS
employee personalization are out of scope.

Skill onboarding is also out of scope for this implementation. No existing
`SKILL.md`, prompt, dispatcher, or routing instruction will be changed.

## 3. Design principles

1. **One persistence owner:** only the Python profile service reads and writes
   the persisted profile representation.
2. **One behavior contract:** all onboarded skills use the same rules for
   interpreting preferences.
3. **Safe precedence:** preferences cannot override security requirements,
   permission gates, mandatory confirmations, exact message blocks, or required
   output formats.
4. **Non-blocking defaults:** a missing profile does not prevent another skill
   from running.
5. **No silent data loss:** malformed or unsupported profile data is reported
   and preserved, not reset automatically.
6. **Explicit learning:** inferred preferences remain proposals until the maker
   accepts them.
7. **Request consistency:** a profile is resolved once for a request and remains
   immutable through that request's complete skill chain.
8. **Privacy by default:** raw conversation content and preference values are
   not emitted through telemetry.

## 4. Repository structure

Add the following files:

```text
solutions/ess-maker-skills/
|-- scripts/
|   `-- user_profile.py
|-- src/skills/shared/
|   |-- user-profile-contract.md
|   `-- user-profile-schema.md
`-- .local/
    `-- user-profile.json                 # Runtime-generated; Git-ignored

tests/scripts/
|-- test_user_profile.py
`-- test_user_profile_contract.py
```

The existing `solutions/ess-maker-skills/.gitignore` already ignores `.local/**`.
Do not add an exception for the profile.

Do not store these fields in `.local/config.json`. That file owns active agent
and environment configuration and has a different lifecycle.

## 5. Component responsibilities

### 5.1 `scripts/user_profile.py`

This is the deterministic profile service and command-line interface. It owns:

- Default profile creation
- JSON parsing and schema validation
- Preference-value validation
- Effective-profile resolution
- Explicit preference updates
- Learned-preference proposals
- Proposal acceptance and rejection
- Onboarding-state updates
- Profile reset
- Revision checks
- Schema migration
- Atomic persistence
- Structured JSON success and error responses

Keep service functions separate from CLI argument parsing so tests and future
callers can invoke the service directly.

### 5.2 `src/skills/shared/user-profile-schema.md`

This documents:

- The persisted JSON shape
- Field ownership
- Allowed values
- Defaults
- Migration rules
- Revision semantics
- Proposal semantics
- Round-trip requirements

It is a reference document, not an independently routed skill.

### 5.3 `src/skills/shared/user-profile-contract.md`

This is the reusable behavioral contract followed by onboarded skills. It
defines:

- How to obtain the effective profile
- How every preference affects flexible user-facing output
- Preference precedence
- Output classifications
- Required exceptions
- Missing, invalid, and unsupported-profile behavior
- Rules for carrying one resolved profile through nested skill calls

It must not contain profile persistence logic.

## 6. Persisted profile

### 6.1 Canonical path

```text
.local/user-profile.json
```

All commands resolve this path relative to the
`solutions/ess-maker-skills/` solution root unless an explicit path is supplied
for tests.

### 6.2 Initial schema

```json
{
  "schemaVersion": 1,
  "revision": 1,
  "onboarding": {
    "status": "not_started",
    "updatedAt": null
  },
  "preferences": {
    "responseFormat": {
      "value": "auto",
      "source": "default",
      "updatedAt": null
    },
    "detailLevel": {
      "value": "balanced",
      "source": "default",
      "updatedAt": null
    },
    "toneOfVoice": {
      "value": "friendly_professional",
      "source": "default",
      "updatedAt": null
    },
    "confirmationFrequency": {
      "value": "standard",
      "source": "default",
      "updatedAt": null
    },
    "maximumResponseLength": {
      "value": null,
      "unit": "words",
      "source": "default",
      "updatedAt": null
    },
    "proactiveSuggestions": {
      "value": "contextual",
      "source": "default",
      "updatedAt": null
    }
  },
  "proposals": {}
}
```

### 6.3 Allowed values

| Field | Type | Allowed values |
|---|---|---|
| `schemaVersion` | Integer | `1` |
| `revision` | Integer | Positive integer |
| `onboarding.status` | Enum | `not_started`, `deferred`, `completed` |
| `responseFormat.value` | Enum | `auto`, `prose`, `bullets`, `steps`, `table_first` |
| `detailLevel.value` | Enum | `concise`, `balanced`, `detailed` |
| `toneOfVoice.value` | Enum | `direct`, `friendly_professional`, `formal`, `empathetic` |
| `confirmationFrequency.value` | Enum | `minimal`, `standard`, `frequent` |
| `maximumResponseLength.value` | Integer or null | `50` through `5000`, or `null` |
| `maximumResponseLength.unit` | Enum | `words` |
| `proactiveSuggestions.value` | Enum | `off`, `contextual`, `on` |
| Preference `source` | Enum | `default`, `explicit`, `learned` |
| Proposal `status` | Enum | `pending`, `accepted`, `rejected` |

All timestamps use UTC ISO 8601 with a `Z` suffix. `null` is permitted only
where explicitly documented.

Arbitrary tone instructions or arbitrary behavioral prompt text are not
accepted in version 1.

### 6.4 Learned-preference proposal

```json
{
  "proposals": {
    "detailLevel": {
      "proposedValue": "concise",
      "observationCount": 3,
      "confidence": 0.86,
      "status": "pending",
      "createdAt": "2026-10-13T22:00:00Z",
      "updatedAt": "2026-10-13T22:00:00Z"
    }
  }
}
```

Rules:

- `confidence` is a finite number from `0.0` through `1.0`.
- `observationCount` is a positive integer.
- A proposal never changes the effective profile.
- Acceptance copies the value into the matching preference with
  `source: learned`.
- Rejection leaves the effective preference unchanged.
- Raw user messages, prompts, responses, or conversation transcripts must not
  be stored as proposal evidence.

## 7. Python service design

### 7.1 Internal types

Use `Enum` and `dataclass` types for validated state:

```python
class ResponseFormat(str, Enum): ...
class DetailLevel(str, Enum): ...
class ToneOfVoice(str, Enum): ...
class ConfirmationFrequency(str, Enum): ...
class ProactiveSuggestions(str, Enum): ...
class PreferenceSource(str, Enum): ...
class OnboardingStatus(str, Enum): ...
class ProposalStatus(str, Enum): ...

@dataclass(frozen=True)
class EffectiveProfile:
    response_format: ResponseFormat
    detail_level: DetailLevel
    tone_of_voice: ToneOfVoice
    confirmation_frequency: ConfirmationFrequency
    maximum_response_length: int | None
    proactive_suggestions: ProactiveSuggestions
```

The persisted model may use additional typed dataclasses for preference
metadata, onboarding state, and proposals. Parse raw JSON into validated types
before applying business logic.

### 7.2 Service functions

Implement these functions independently of CLI parsing:

```python
default_profile() -> StoredProfile
load_profile(path: Path) -> StoredProfile
validate_profile(document: object) -> StoredProfile
migrate_profile(document: object) -> StoredProfile
resolve_profile(path: Path) -> EffectiveProfileResult
initialize_profile(path: Path) -> StoredProfile
set_preferences(
    path: Path,
    updates: Mapping[str, object],
    expected_revision: int | None = None,
) -> StoredProfile
set_onboarding_status(
    path: Path,
    status: OnboardingStatus,
    expected_revision: int | None = None,
) -> StoredProfile
propose_preference(
    path: Path,
    field: str,
    value: object,
    observation_count: int,
    confidence: float,
    expected_revision: int | None = None,
) -> StoredProfile
accept_proposal(
    path: Path,
    field: str,
    expected_revision: int | None = None,
) -> StoredProfile
reject_proposal(
    path: Path,
    field: str,
    expected_revision: int | None = None,
) -> StoredProfile
reset_profile(
    path: Path,
    expected_revision: int | None = None,
) -> StoredProfile
```

Use specific exception types:

```python
UserProfileError
UserProfileNotFoundError
UserProfileValidationError
UserProfileSchemaVersionError
UserProfileConflictError
UserProfilePersistenceError
UserProfileProposalError
```

Do not catch broad exceptions and convert them into success-shaped defaults.

### 7.3 Effective-profile resolution

Resolution is deterministic:

1. If the profile does not exist, return complete built-in defaults with
   `profileExists: false`.
2. If it exists, parse the JSON.
3. Validate its structure and values.
4. Migrate supported older schemas in memory.
5. Overlay stored preference values onto the complete defaults.
6. Ignore pending and rejected proposals.
7. Return every effective field, onboarding status, current revision, and a
   summary of pending proposals.

An existing malformed profile must not silently resolve as if it were missing.

### 7.4 Mutation semantics

Every mutation must:

1. Load and validate the complete existing document.
2. Validate every requested change before writing.
3. Check `expected_revision` when provided.
4. Change only fields owned by the operation.
5. Preserve unrelated fields.
6. Increment `revision` exactly once.
7. Set affected timestamps to the current UTC time.
8. Persist the complete updated document atomically.
9. Return the saved and re-read result.

A multi-field update is all-or-nothing. One invalid field rejects the entire
operation.

An explicit preference update:

- Sets `source` to `explicit`.
- Updates `updatedAt`.
- Removes a pending proposal for the same field.
- Leaves other preferences unchanged.

### 7.5 Atomic persistence

Use the repository's existing temporary-file plus `os.replace` pattern:

1. Create the parent `.local` directory when necessary.
2. Create a temporary sibling file.
3. Write UTF-8 JSON with two-space indentation and a trailing newline.
4. Flush the stream.
5. Attempt `fsync`.
6. Replace the destination with `os.replace`.
7. Remove the temporary file if persistence fails.

Use ASCII-safe JSON and stable key ordering.

### 7.6 Revision conflicts

Support optimistic concurrency through `expected_revision`.

If the expected revision does not match the current revision:

- Do not write.
- Return a `profile_conflict` result.
- Include expected and actual revisions.
- Require the caller to resolve the profile again before retrying.

Do not automatically merge two concurrent mutations.

## 8. Command-line interface

All commands print one JSON document to standard output. Errors use a nonzero
exit code and a stable `status`.

### 8.1 Resolve

```text
python scripts/user_profile.py resolve
```

Success:

```json
{
  "status": "ok",
  "profileExists": true,
  "schemaVersion": 1,
  "revision": 4,
  "onboardingStatus": "completed",
  "effectiveProfile": {
    "responseFormat": "bullets",
    "detailLevel": "concise",
    "toneOfVoice": "friendly_professional",
    "confirmationFrequency": "standard",
    "maximumResponseLength": {
      "value": 500,
      "unit": "words"
    },
    "proactiveSuggestions": "contextual"
  },
  "pendingProposals": []
}
```

This is the primary interface consumed by onboarded skills.

### 8.2 Get persisted state

```text
python scripts/user_profile.py get
```

Return the validated persisted representation, including metadata and proposals.

### 8.3 Initialize

```text
python scripts/user_profile.py initialize
```

Initialization is idempotent. An existing valid profile is returned unchanged.

### 8.4 Set preferences

```text
python scripts/user_profile.py set \
  --values-json "{...}" \
  --expected-revision 4
```

The JSON object may contain one or more preference fields. All fields are
validated before any write.

### 8.5 Set onboarding status

```text
python scripts/user_profile.py onboarding \
  --status completed \
  --expected-revision 4
```

### 8.6 Propose a learned preference

```text
python scripts/user_profile.py propose \
  --field detailLevel \
  --value concise \
  --observation-count 3 \
  --confidence 0.86 \
  --expected-revision 4
```

The shared module accepts a proposal from an approved caller but does not
generate observations or decide when learning should occur.

### 8.7 Accept or reject a proposal

```text
python scripts/user_profile.py accept \
  --field detailLevel \
  --expected-revision 5

python scripts/user_profile.py reject \
  --field detailLevel \
  --expected-revision 5
```

### 8.8 Validate

```text
python scripts/user_profile.py validate
```

Validation performs no mutation.

### 8.9 Reset

```text
python scripts/user_profile.py reset \
  --expected-revision 5 \
  --yes
```

Reset writes a fresh default document. It does not merely delete the file.
Without `--yes`, the command returns `confirmation_required` and performs no
mutation.

### 8.10 Error shape

Example:

```json
{
  "status": "invalid_profile",
  "error": "Preference 'detailLevel' has unsupported value 'extreme'.",
  "path": ".local/user-profile.json"
}
```

Stable status values:

- `ok`
- `invalid_arguments`
- `invalid_profile`
- `unsupported_schema`
- `profile_conflict`
- `proposal_not_found`
- `confirmation_required`
- `persistence_failed`

Do not include profile contents in an error response.

## 9. Shared skill behavior contract

### 9.1 Contract inputs

`user-profile-contract.md` defines these logical inputs:

- `EFFECTIVE_PROFILE`: successful `resolve` result
- `OUTPUT_CLASS`: one of `flexible`, `contractual`, `machine_readable`, or
  `safety_critical`
- `TASK_REQUIRES_COMPLETE_OUTPUT`: boolean
- `TASK_REQUIRES_CONFIRMATION`: boolean

### 9.2 Precedence

Skills apply rules in this order:

1. Security and privacy requirements
2. Authorization and role gates
3. Destructive-operation confirmation
4. Skill-required selection and confirmation turns
5. Exact Message blocks and required output contracts
6. Explicit profile preferences
7. Accepted learned preferences
8. Module defaults

Lower-priority rules never modify higher-priority behavior.

### 9.3 Response format

| Value | Skill behavior |
|---|---|
| `auto` | Select the shortest clear format appropriate to the task |
| `prose` | Prefer short paragraphs |
| `bullets` | Prefer flat lists for distinct items |
| `steps` | Prefer numbered steps for ordered actions |
| `table_first` | Prefer tables for comparable structured information |

Response format does not change:

- Exact Message blocks
- Required tables or scorecards
- JSON, YAML, CSV, code, or commands
- API payloads
- Downloadable or persisted artifacts

### 9.4 Detail level

| Value | Skill behavior |
|---|---|
| `concise` | Outcome, essential context, and required action |
| `balanced` | Outcome, decision-relevant reasoning, and required action |
| `detailed` | Implementation context, edge cases, and limitations |

Detail preferences cannot remove blockers, warnings, diagnostic evidence,
required remediation, or required choices.

### 9.5 Tone of voice

| Value | Skill behavior |
|---|---|
| `direct` | Neutral, brief, and action-oriented |
| `friendly_professional` | Collaborative and professional |
| `formal` | Reserved and precise |
| `empathetic` | Acknowledge difficulty or impact when supported by context |

Tone changes phrasing only. It cannot change facts, outcomes, or exact copy.

### 9.6 Confirmation frequency

| Value | Skill behavior |
|---|---|
| `minimal` | Ask only mandatory or decision-blocking questions |
| `standard` | Ask mandatory questions and clarify material ambiguity |
| `frequent` | Confirm significant scope or behavioral choices |

This preference never removes:

- Destructive-operation confirmation
- Remote mutation consent
- Evaluation-set selection
- Connection, environment, or agent selection
- Role attestation
- Replacement approval
- Separate-turn requirements
- Any confirmation explicitly required by a skill

### 9.7 Maximum response length

The maximum is a soft word budget. When the preferred length is insufficient,
preserve content in this order:

1. Outcome
2. Blockers and safety information
3. Required action
4. Exact contract output
5. Required evidence and remediation
6. Background explanation
7. Optional suggestions

Never truncate a response in the middle of a message block, table, command,
error, or required result. Exceed the preferred limit when complete output is
required.

### 9.8 Proactive suggestions

| Value | Skill behavior |
|---|---|
| `off` | Do not add unrequested suggestions |
| `contextual` | Suggest something only when required to complete or unblock the task |
| `on` | Add at most one directly relevant next step |

Do not append suggestions after a terminal exact message or where an existing
skill contract prohibits extra text.

## 10. Profile loading and propagation

This section defines the interface that a later skill-onboarding phase will
consume. It is not implemented in existing skills as part of the shared-module
work.

At the start of an onboarded entry skill:

1. Run `python scripts/user_profile.py resolve`.
2. Read `src/skills/shared/user-profile-contract.md`.
3. Classify the skill output.
4. Apply the returned effective profile only to flexible maker-facing content.
5. Carry the same immutable resolved profile into any nested skills invoked
   during the request.

Do not resolve the profile again during the same request. A profile change made
while a workflow is in progress takes effect on the next request.

If a skill is invoked directly and no profile context was supplied, it performs
the resolution itself.

## 11. Skill adoption requirement

The requirements in this section are reserved for the later skill-onboarding
phase. The shared-module implementation must provide a stable contract that
supports this pattern, but must not modify existing skills.

Each onboarded skill adds an equivalent entry section:

```markdown
## User profile

If an effective user profile was not supplied by the current caller, run:

python scripts/user_profile.py resolve

Read `src/skills/shared/user-profile-contract.md` and apply the resolved
profile to flexible maker-facing communication in this skill.

The profile does not override exact Message blocks, required output formats,
selection gates, permission gates, destructive-operation confirmations, or
machine-readable output. Carry the same resolved profile into skills invoked
during this request.
```

### 11.1 Output classifications

| Skill category | Output class |
|---|---|
| Topic and workflow guidance | `flexible` |
| Troubleshooting explanations | `flexible` |
| Landing-page explanations | `flexible` |
| Evaluation skills with exact scorecards and menus | `contractual` |
| FlightCheck result rendering | `contractual` |
| Setup, connect, run, push, and delete operations | `safety_critical` |
| Landing-page mutations and deletion | `safety_critical` |
| Script JSON and generated artifacts | `machine_readable` |

Adoption changes communication only. It must not change generated topic YAML,
workflow JSON, evaluation expected responses, CSV content, API payloads, or
runtime ESS agent behavior unless a separate feature explicitly requests it.

## 12. Failure behavior

| Condition | Required behavior |
|---|---|
| Profile missing | Use defaults and continue |
| Profile valid | Apply effective preferences |
| Supported older schema | Migrate in memory; persist only through an explicit mutation or migration operation |
| Malformed JSON or invalid fields | Report the error, preserve the file, and use defaults for the unrelated current task |
| Newer unsupported schema | Report incompatibility and use defaults for the unrelated current task |
| Resolve command failure | Report that preferences could not be loaded and continue with defaults when safe |
| Preference conflicts with a skill contract | Preserve the skill contract without modifying the profile |
| Profile-management request encounters invalid state | Stop and require repair or explicit reset; do not claim the requested profile change succeeded |

## 13. Privacy and telemetry

- Keep the profile in `.local/`.
- Never commit or upload it.
- Do not store raw conversation content.
- Do not store a maker email, UPN, employee ID, or account name.
- Do not include preference values in telemetry.
- Do not include profile contents in exceptions or telemetry.
- If measurement is required, emit only coarse outcomes:
  `resolved`, `defaults_used`, `invalid_profile`, or `resolution_failed`.
- Proposal confidence and observation counts remain local and are not emitted.

## 14. Testing

### 14.1 Profile service tests

`tests/scripts/test_user_profile.py` covers:

- Missing profile resolves to complete defaults
- Initialization creates the canonical schema
- Initialization is idempotent
- Every valid enum value
- Every invalid enum value
- Maximum length at `50` and `5000`
- Maximum length below and above bounds
- Null maximum length
- Partial update preserves unrelated fields
- Multi-field update succeeds atomically
- One invalid field rejects the complete update
- Explicit updates set `source: explicit`
- Explicit updates remove same-field pending proposals
- Proposal creation does not alter the effective profile
- Proposal acceptance sets `source: learned`
- Proposal rejection preserves the effective value
- Missing proposal errors
- Onboarding-state transitions
- Reset requires `--yes`
- Reset writes canonical defaults
- Successful mutations increment revision exactly once
- Failed mutations do not increment revision
- Expected-revision conflicts perform no write
- Malformed JSON is reported and not overwritten
- Unsupported future schema is rejected
- Supported older schema migration
- Atomic replacement
- Temporary-file cleanup after failure
- UTC timestamps
- Non-finite proposal confidence rejection
- Raw evidence fields are rejected
- CLI success exit codes
- CLI failure exit codes
- Every CLI response is valid JSON

Use temporary directories in tests; do not read or modify the developer's real
`.local/user-profile.json`.

### 14.2 Shared contract tests

`tests/scripts/test_user_profile_contract.py` verifies that the shared contract:

- Defines `user_profile.py resolve` as the profile-loading interface
- Supports a caller-supplied immutable resolved profile
- Defines security and confirmation precedence
- Preserves exact Message blocks
- Preserves mandatory confirmations
- Defines soft response-length behavior
- Defines missing-profile defaults
- Defines invalid-profile non-overwrite behavior
- Prohibits raw conversation evidence
- Prohibits machine-readable output transformation

Tests that enumerate onboarded skills and verify their references to this
contract belong to the later skill-onboarding phase.

## 15. Implementation sequence

1. Add schema enums, typed models, defaults, and validation.
2. Add load, resolve, and atomic persistence.
3. Add initialize, set, onboarding, and reset operations.
4. Add proposal creation, acceptance, and rejection.
5. Add revision-conflict handling.
6. Add the CLI and stable JSON response shapes.
7. Add `user-profile-schema.md`.
8. Add `user-profile-contract.md`.
9. Add profile service tests.
10. Add isolated shared-contract tests.
11. Verify that no existing skill or routing file changed.

Preference-observation generation and onboarding UX are separate features and
are not required to complete the shared module.

## 16. Acceptance criteria

The shared module is complete when:

1. A missing profile resolves to the documented defaults without creating a
   file or blocking another skill.
2. Explicit updates persist atomically and survive a new process invocation.
3. Invalid updates cannot partially change the profile.
4. Pending learned preferences do not affect responses before acceptance.
5. Concurrent stale updates are rejected by revision checks.
6. Invalid profile files are preserved and reported.
7. Every effective profile contains all six settings.
8. The shared contract defines immutable per-request profile propagation for
   the later onboarding phase.
9. The shared contract prevents preferences from bypassing security or
   confirmation gates.
10. The shared contract preserves exact messages, required result formats,
    machine-readable output, and generated artifacts.
11. Profile values and raw conversation evidence are not emitted through
    telemetry.
12. No existing skill, prompt, dispatcher, or routing file is modified.

## 17. Deferred work

The following are explicitly deferred:

- Cross-device profile synchronization
- Cloud or Copilot Studio profile storage
- Profiles shared across repository clones
- Multiple-user isolation within one shared checkout
- Runtime ESS employee personalization
- Automatic observation generation
- Automatic activation of inferred preferences
- Free-form custom tone or response instructions
- Per-agent, per-skill, or per-task preference overrides
- Administrative profile policy
- Onboarding existing skills with the shared profile contract
- Skill-by-skill adoption enforcement tests
