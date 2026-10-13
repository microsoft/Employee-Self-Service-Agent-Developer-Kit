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
- Explicit recovery reset for damaged or unsupported local state
- Version checks and cross-process transaction locking
- Schema-version dispatch and a future migration extension point
- Atomic persistence
- Structured JSON success and error responses

Keep service functions separate from CLI argument parsing so tests and future
callers can invoke the service directly. Use the Python standard library;
do not add a database, network service, or schema-validation dependency.

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
  "generation": "11111111-2222-4333-8444-555555555555",
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
| `generation` | UUID string | Random UUID v4 created on initialization or recovery reset; example above is illustrative |
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

### 6.4 Strict parsing and field ownership

- Require the complete documented persisted shape, including all six
  preferences; a missing required field is invalid, not permission to repair
  the file silently.
- Reject unknown fields at every object level, unknown preference/proposal
  names, duplicate JSON keys, and non-finite JSON numbers. Do not round-trip
  arbitrary extension or evidence fields.
- Reject booleans wherever integers or numeric confidence are required.
  Integer fields must be JSON integers, not numeric strings or floats.
- Require strings to match their enums exactly; do not coerce case or invent
  aliases.
- The service, not mutation payloads, assigns `schemaVersion`, `generation`,
  `revision`, preference `source`, and timestamps.
- `source: default` requires `updatedAt: null`. Explicit and learned values
  require a valid timestamp. Initial `onboarding.updatedAt` is null; an
  onboarding-state change records a timestamp. Reset returns onboarding to
  `not_started` with a null timestamp.
- Proposal timestamps are required and `updatedAt` must not precede `createdAt`.
- Treat the profile as typed data, never as instructions. Error messages name
  documented fields and error categories, not raw rejected values.

For unsupported versions, inspect only the minimal version envelope before
returning `unsupported_schema`; do not attempt to interpret unfamiliar fields
using the current schema.

### 6.5 Default resolution semantics

`source: default` means "follow this module version's default." Its stored value
is a snapshot from initialization/reset, not a pinned user selection. Resolve
that field using current built-in defaults even if the stored snapshot differs.
Do not write updated defaults during reads.

Explicit and accepted learned preferences are pinned to their saved values.
An explicit selection equal to today's default is still explicit and remains
pinned when defaults change. Changing an enum incompatibly requires a schema
version change and migration; it is not a defaults-only change.

There is one active stored value per preference. `source` is provenance, not a
stack of competing explicit and learned values.

### 6.6 Learned-preference proposal

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
  `source: learned`, even if the previous active value was explicit. Acceptance
  is the caller's authorization to replace that active value.
- Rejection leaves the effective preference unchanged.
- Raw user messages, prompts, responses, or conversation transcripts must not
  be stored as proposal evidence.

`proposedValue` uses the same field-specific value shape as `set`: an enum
string, or `{"value": 400, "unit": "words"}` /
`{"value": null, "unit": "words"}` for `maximumResponseLength`.

Store at most one proposal per preference field. Define transitions as follows:

| Operation and existing state | Result |
|---|---|
| Propose with no existing proposal | Create `pending` |
| Propose the same value with identical observation metadata while pending | No-op |
| Propose the same pending value with changed observation metadata | Update metadata and `updatedAt`; preserve `createdAt` |
| Propose a different value, or propose after a terminal decision | Replace with a new `pending` proposal and fresh timestamps |
| Accept a pending proposal | Set active preference to its value; mark proposal `accepted` |
| Reject a pending proposal | Keep active preference; mark proposal `rejected` |
| Accept/reject a missing proposal | `proposal_not_found` |
| Accept/reject an accepted or rejected proposal | `proposal_not_pending`; no write |
| Explicitly set a preference with a proposal | Remove that field's proposal, including terminal metadata |

All proposal writes require the exact observed profile version (generation and
revision). Acceptance/rejection therefore cannot act on a proposal replaced
after the caller reviewed it. Check the expected version before looking up
the proposal. Repeating accept/reject with an old version returns
`profile_conflict`, not success.

The module does not infer consent or authenticate a conversational decision.
Future callers must obtain acceptance before invoking `accept`. Observation
generation and deciding whether or when to re-propose a rejected value remain
outside this module; it retains the latest rejection metadata for those callers.

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
before applying business logic. Use a frozen `ProfileVersion` containing
`generation: str | None` and `revision: int` for concurrency tokens.

The CLI encodes an existing version as `<generation>:<revision>` and missing
state as `none:0`. Generation identifies a local document lifetime, not a
user. Validate UUID and integer components; `none:0` is the only token with
a null generation or zero revision. Never infer identity from a generation
or emit it through telemetry.

### 7.2 Service functions

Implement these functions independently of CLI parsing:

```python
default_effective_profile() -> EffectiveProfile
default_profile(*, generation: str, revision: int) -> StoredProfile
load_profile(path: Path) -> StoredProfile
validate_profile(document: object) -> StoredProfile
migrate_profile(document: object) -> StoredProfile
resolve_profile(path: Path) -> EffectiveProfileResult
initialize_profile(path: Path) -> MutationResult
set_preferences(
    path: Path,
    updates: Mapping[str, object],
    *,
    expected_version: ProfileVersion,
) -> MutationResult
set_onboarding_status(
    path: Path,
    status: OnboardingStatus,
    *,
    expected_version: ProfileVersion,
) -> MutationResult
propose_preference(
    path: Path,
    field: str,
    value: object,
    observation_count: int,
    confidence: float,
    *,
    expected_version: ProfileVersion,
) -> MutationResult
accept_proposal(
    path: Path,
    field: str,
    *,
    expected_version: ProfileVersion,
) -> MutationResult
reject_proposal(
    path: Path,
    field: str,
    *,
    expected_version: ProfileVersion,
) -> MutationResult
reset_profile(
    path: Path,
    *,
    expected_version: ProfileVersion,
    confirmed: bool = False,
) -> MutationResult
recover_profile(
    path: Path,
    *,
    expected_content_hash: str,
    confirmed: bool = False,
) -> MutationResult
```

Use specific exception types:

```python
UserProfileError
UserProfileNotFoundError
UserProfileValidationError
UserProfileSchemaVersionError
UserProfileConflictError
UserProfileReadError
UserProfilePersistenceError
UserProfileProposalError
UserProfileLockTimeoutError
UserProfileConfirmationError
```

Do not catch broad exceptions and convert them into success-shaped defaults.

### 7.3 Effective-profile resolution

Resolution is deterministic:

1. If the profile does not exist, return complete built-in defaults with
   `profileExists: false`, version `none:0`, `onboardingStatus: not_started`,
   and no proposals. Do not create the profile, parent directory, or lock file.
2. If it exists, read one complete byte snapshot and strictly parse the JSON.
3. Inspect the minimal `schemaVersion` envelope. A missing or ill-typed version
   is `invalid_profile`; an integer version without support is
   `unsupported_schema`.
4. Validate against that version's schema. If a supported migration exists,
   migrate in memory and validate the resulting current-version document.
5. Build the complete effective profile using current module defaults for
   `source: default` and saved values for `explicit` or `learned`.
6. Do not apply any proposal directly, regardless of its status. Acceptance
   already copied its value to the active preference.
7. Return the effective fields, onboarding status, version, and pending
   proposals from that same snapshot.

An existing malformed profile must not silently resolve as if it were missing.
Expose `default_effective_profile()` and a `defaults` CLI operation so error
recovery never depends on consumers copying default values.

Version 1 accepts only schema version `1`; there is no supported earlier schema
and no migration to implement now. `migrate_profile` is version dispatch plus
current-schema validation in v1. Future versions may add explicit
source-schema validators and migration functions. Do not invent a v0 schema
or coerce an unknown version. Resolution and validation never persist
migrations; a future supported mutation writes the current schema.

### 7.4 Mutation semantics

Ordinary mutations (`set`, `onboarding`, `propose`, `accept`, `reject`, and
valid-profile `reset`) require an existing valid document and a caller-supplied
expected version. Initialization and recovery are explicit exceptions described
below.

1. Validate CLI/service arguments without echoing their contents.
2. Acquire the cross-process lock described in section 7.6.
3. Load and validate the complete existing document inside the lock.
4. Compare both generation and revision to `expected_version`.
5. Validate the requested transition; a stale version fails even if the change
   would otherwise be a no-op.
6. Apply the operation to a private copy, preserving unrelated known fields.
7. If there is no semantic change, return `changed: false` with the existing
   version and timestamps; do not write.
8. Otherwise increment revision exactly once, set affected timestamps, validate
   the resulting document, and persist it atomically while holding the lock.
9. Capture the committed result before releasing the lock. Return that exact
   validated snapshot, not a later unlocked read that could belong to another
   writer.

A multi-field update is all-or-nothing. One invalid field rejects the entire
operation. Empty update objects are invalid. A real mutation preserves the
generation except for explicit recovery reset.

An explicit preference update:

- Sets `source` to `explicit`.
- Updates `updatedAt` when the value or source changes.
- Removes any proposal for the same field.
- Leaves other preferences unchanged.

Selecting the same value as a default or learned preference is a semantic
change because it pins the source as explicit. Repeating an already explicit
value with no proposal is a no-op. Clearing a proposal alone increments the
document revision but does not alter the unchanged preference timestamp.

Onboarding may move between its three documented statuses through an explicit
call; setting the current status is a no-op. It does not modify preferences
or start an onboarding interaction.

### 7.5 Atomic persistence

Use the repository's temporary-file plus `os.replace` pattern inside the
locked transaction:

1. Create the parent `.local` directory when necessary.
2. Create a temporary sibling file.
3. Write UTF-8 JSON with two-space indentation and a trailing newline.
4. Flush the stream.
5. Call `fsync`; tolerate only a documented platform/filesystem
   "unsupported" error. Treat actual I/O failures as persistence failures.
6. Replace the destination with `os.replace`.
7. Remove the temporary file if persistence fails.

Use ASCII-safe JSON and stable key ordering.

`os.replace` is the commit point. Before it succeeds, a failure leaves the
existing profile unchanged. After it succeeds, the mutation is committed even
if reporting the result fails. Any handled post-commit failure must report
`committed: true` and the committed version; callers must reload rather than
blindly repeat a mutation. Do not roll back after commit or add an unnecessary
post-commit read.

### 7.6 Transaction locking and stale decisions

A version comparison followed by `os.replace` is not a compare-and-swap:
two processes can both compare the same old revision before either writes.
Serialize every read-compare-mutate-replace transaction with an OS-backed,
cross-process exclusive lock on the stable sibling
`.local/user-profile.lock`.

- Use standard-library OS locking (`msvcrt.locking` on Windows or `fcntl.flock`
  on POSIX), with one shared wrapper and the same protocol for every writer.
- Writer calls may create the parent directory and stable lock file before
  acquiring the lock; this does not initialize a profile. On Windows, lock
  the same fixed byte range from offset zero with a nonblocking attempt.
  Never truncate the lock file when opening it.
- Keep the lock file in place; do not lock the profile itself, which is
  replaced, and do not delete/recreate the lock file on each transaction.
  An OS lock releases on process termination and is not a stale PID sentinel.
- Use a five-second acquisition timeout measured with a monotonic clock and
  bounded retry intervals. Return `lock_timeout` without a profile write.
- Initialization, normal mutations, reset, and recovery all hold the same lock.
  Ordinary reads need no lock because they consume one atomically replaced
  snapshot; they must not combine metadata from separate reads.
- Under the lock, compare both generation and revision. On mismatch return
  `profile_conflict`, including `expectedVersion` and `actualVersion`, and do
  not write. Required version arguments cannot be bypassed with `--yes`.
- Never silently refresh a stale token and retry acceptance or reset. The
  caller must re-read and reconsider the changed state.

The lock coordinates cooperating module processes. It is not user isolation,
an authorization mechanism, or protection against manual external file edits.

### 7.7 Initialization, reset, and recovery

**Initialize:** under the lock, create a missing profile at revision `1` with a
new random generation. Return an existing valid profile unchanged. Reject an
existing invalid or unsupported profile. Competing initializers must create
one generation, not overwrite each other.

**Normal reset:** require `confirmed: true` and the exact current version.
Restore all default preference snapshots, empty proposals, and initial
onboarding state. Preserve generation and increment revision once if anything
changes. A profile already in exactly that state is a no-op. Normal reset does
not accept malformed or unsupported state.

**Recovery reset:** provide a separate `recover_profile` operation exposed by
`reset --recover`. It requires explicit confirmation and the SHA-256 hash of
the exact damaged bytes previously inspected by `get`, `resolve`, or `validate`.
Do not trust generation/revision values from an invalid document.

1. Acquire the same transaction lock and read the current raw bytes.
2. Compare their SHA-256 hash to `expected_content_hash`; mismatches return
   `profile_conflict`. A missing file returns `profile_not_found`.
3. Confirm that the file is still invalid or unsupported. Reject valid state
   with `recovery_not_required`; use normal reset for a valid profile.
4. Write an exclusive, uniquely named local backup
   `.local/user-profile.recovery.<random-uuid>.bak` with the exact original
   bytes. Complete and flush the backup, using the same `fsync` policy as
   active-state persistence, before replacing the active file. If backup
   persistence fails, do not replace the original.
5. Atomically write a default profile with a new generation and revision `1`.
   A new generation invalidates all prior version tokens, even if an integer
   revision is reused.
6. Return the committed version and backup path, never backup contents.

Recovery explicitly discards active interpretation of the old document; it is
not a migration. Backups remain local and Git-ignored and are removed manually,
not silently purged. Normal commands must never enter recovery automatically.

## 8. Command-line interface

All operations print exactly one JSON document to standard output; no progress
prose or raw tracebacks. Argument-parser errors use the same JSON error
contract, not the parser's default text output. `--help` is the sole exception:
it may print human-readable help and exit successfully.

Commands below run in PowerShell from the solution root. Resolve the default
path using the module location, not the process working directory; invoking
the script from the repo root or `scripts` must reach the same profile. Tests
pass a path to service functions rather than changing a real user's profile.

### 8.1 Operation/state matrix

| Operation | Missing profile | Valid v1 profile | Invalid profile | Unsupported version |
|---|---|---|---|---|
| `defaults` | Ignore disk state | Ignore disk state | Ignore disk state | Ignore disk state |
| `resolve` | Success with defaults, version `none:0`; no write | Success with effective snapshot | `invalid_profile` | `unsupported_schema` |
| `get`, `validate` | `profile_not_found` | Return snapshot or validation metadata; no write | `invalid_profile` | `unsupported_schema` |
| `initialize` | Create generation at revision `1` | Success, `changed: false` | `invalid_profile` | `unsupported_schema` |
| `set`, `onboarding`, `propose`, `accept`, `reject` | `profile_not_found`; initialize explicitly | Apply version and transition rules | `invalid_profile` | `unsupported_schema` |
| `reset --yes` | `profile_not_found` | Apply normal reset rules | `invalid_profile` | `unsupported_schema` |
| `reset --recover --yes` | `profile_not_found` | `recovery_not_required` after matching hash | Recover only with matching content hash | Recover only with matching content hash |

Missing confirmation returns `confirmation_required` before any reset write.
Missing required arguments return `invalid_arguments`. An unreadable file
returns `read_failed`, never "missing."

### 8.2 Success envelopes

Every success includes `status: "ok"` and `operation`. State-based successes
also include `schemaVersion: 1`, `profileExists`, and the opaque `version`.
Do not expose separate generation/revision fields outside the stored `profile`
object; callers must carry the entire version token.

| Operation | Additional required success fields |
|---|---|
| `resolve` | `effectiveProfile`, `onboardingStatus`, `pendingProposals` |
| `defaults` | `schemaVersion: 1`, `effectiveProfile`; no disk identity or onboarding state |
| `get` | Complete validated `profile` |
| `validate` | No profile contents; shared state/version fields suffice |
| All mutation operations | `changed`, `committed`, complete resulting `profile` |

Mutation `committed` equals `changed` on success. No-op responses return the
unchanged snapshot. Recovery success additionally includes `backupPath`.
Pending proposals are an array of pending records in canonical preference
order, each with `field` plus the properties documented in section 6.6.

### 8.3 Resolve and defaults

```text
python scripts\user_profile.py resolve
```

Success:

```json
{
  "status": "ok",
  "operation": "resolve",
  "profileExists": true,
  "schemaVersion": 1,
  "version": "11111111-2222-4333-8444-555555555555:4",
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

For an absent profile, return the same shape with `profileExists: false`,
`version: "none:0"`, module defaults, `onboardingStatus: "not_started"`, and
`pendingProposals: []`.

To obtain canonical defaults without reading or creating any state:

```text
python scripts\user_profile.py defaults
```

It returns `status`, `operation: "defaults"`, `schemaVersion`, and a complete
`effectiveProfile` using the same types as `resolve`.

### 8.4 Get persisted state

```text
python scripts\user_profile.py get
```

Return the validated persisted representation, including metadata and proposals.

### 8.5 Initialize

```text
python scripts\user_profile.py initialize
```

Initialization is idempotent. An existing valid profile is returned unchanged.

### 8.6 Set preferences and typed JSON inputs

`set` accepts exactly one of `--values-json <JSON>` or `--values-stdin`.
Both parse the same nonempty JSON object. `propose` similarly accepts exactly
one of `--value-json <JSON>` or `--value-stdin`, with the same field value
shape as a `set` entry. Do not provide an untyped `--value` flag.

The stdin forms avoid PowerShell native-argument quoting differences. Examples
below use `$version` captured from a successful `resolve`. These commands
illustrate separate actions, not an automatic consent workflow.

```powershell
$resolved = python scripts\user_profile.py resolve | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $resolved.status -ne 'ok') { throw 'Profile resolution failed.' }
$version = $resolved.version
@'
{
  "responseFormat": "bullets",
  "detailLevel": "concise",
  "toneOfVoice": "direct",
  "confirmationFrequency": "minimal",
  "maximumResponseLength": { "value": 400, "unit": "words" },
  "proactiveSuggestions": "off"
}
'@ | python scripts\user_profile.py set --values-stdin --expected-version $version
```

Use `initialize` first if the profile is absent. To remove the preferred word
limit, submit this value with the newly observed version:

```powershell
'{"maximumResponseLength":{"value":null,"unit":"words"}}' | python scripts\user_profile.py set --values-stdin --expected-version $version
```

JSON `null` is distinct from the string `"null"`. All fields are validated
before any write, and payloads cannot set metadata.

### 8.7 Set onboarding status

```powershell
python scripts\user_profile.py onboarding --status completed --expected-version $version
```

### 8.8 Propose a learned preference

```powershell
'"concise"' | python scripts\user_profile.py propose --field detailLevel --value-stdin --observation-count 3 --confidence 0.86 --expected-version $version
```

A maximum-length proposal uses the same object as an explicit update:

```powershell
'{"value":null,"unit":"words"}' | python scripts\user_profile.py propose --field maximumResponseLength --value-stdin --observation-count 3 --confidence 0.86 --expected-version $version
```

The caller produces observation metadata; the module validates it but does not
calculate confidence, prove consent, or start learning. Counters and confidence
are not a permission to apply a preference.

### 8.9 Accept or reject a proposal

Use the version of the proposal snapshot the caller actually reviewed, not a
fresh token obtained solely to bypass a conflict:

```powershell
python scripts\user_profile.py accept --field detailLevel --expected-version $version
python scripts\user_profile.py reject --field detailLevel --expected-version $version
```

These are alternative actions. Accept/reject are allowed only from `pending`;
their results use the common mutation envelope.

### 8.10 Validate

```text
python scripts\user_profile.py validate
```

Validation performs no mutation. It reads the same complete snapshot used to
produce its returned version.

### 8.11 Reset and recovery

After explicit approval of the observed valid state:

```powershell
python scripts\user_profile.py reset --expected-version $version --yes
```

For damaged or unsupported state, obtain `contentHash` from the failed read
result and explicitly authorize recovery of those exact bytes:

```powershell
python scripts\user_profile.py reset --recover --expected-content-hash $contentHash --yes
```

`--recover` and `--expected-content-hash` are used together and cannot be
combined with `--expected-version`. Without `--yes`, both reset variants return
`confirmation_required`. The direct service methods also require
`confirmed: true`; CLI confirmation is not an authentication boundary.

### 8.12 Error envelope and exit codes

Example (the content hash below is illustrative):

```json
{
  "status": "invalid_profile",
  "operation": "resolve",
  "error": "Preference 'detailLevel' has an unsupported value.",
  "path": ".local/user-profile.json",
  "contentHash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "committed": false
}
```

Every error has `status`, `operation`, a sanitized `error`, and `committed`.
Use `operation: null` if parsing failed before a supported command was known.
Include `path` only for file-related errors. Errors carry no `effectiveProfile`
or success-shaped `profile` fallback.

Additional error fields:

- A raw-byte read that detects `invalid_profile` or `unsupported_schema`
  includes `contentHash`, a lowercase SHA-256 hex digest of exactly those bytes.
  A hash is unavailable for an unreadable file or invalid CLI payload.
- `profile_conflict` includes `expectedVersion` and `actualVersion` for normal
  mutations, or `expectedContentHash` and `actualContentHash` for recovery.
- A handled post-commit error includes `committed: true` and `version`.
- Do not include raw values, JSON snippets, decoder excerpts, or profile
  contents. Map parser/I/O exceptions to bounded, sanitized categories.

| Exit code | Status values |
|---|---|
| `0` | `ok` |
| `2` | `invalid_arguments`, `confirmation_required` |
| `3` | `profile_not_found`, `invalid_profile`, `unsupported_schema`, `proposal_not_found`, `proposal_not_pending`, `recovery_not_required` |
| `4` | `profile_conflict`, `lock_timeout` |
| `5` | `read_failed`, `persistence_failed` |

An invalid update payload is `invalid_arguments`, not `invalid_profile`.
If a consumer chooses to continue an unrelated task after a load error, it
must surface that error and call `defaults` for an explicitly temporary
fallback. A profile-management operation must not claim success using defaults.
If the module cannot run even `defaults`, the consumer reports personalization
unavailable and follows its own existing behavior; it must not invent a profile.

## 9. Shared skill behavior contract

### 9.1 Contract inputs

`user-profile-contract.md` defines these logical inputs:

- `EFFECTIVE_PROFILE`: successful `resolve` result
- Current explicit task instructions, used only when interpreting flexible
  communication; these are not stored in the profile
- For each output section, `SECTION_CLASS`: `flexible`, `contractual`,
  `machine_readable`, or `safety_critical`
- For each section, whether completeness or confirmation is mandatory under
  the owning skill's rules

These are reasoning inputs for a future caller, not new CLI flags, a renderer,
or a structured response-generation framework. A caller cannot mark a section
flexible to relax an existing required warning or confirmation.

### 9.2 Precedence

Skills apply rules in this order:

1. Security and privacy requirements
2. Authorization and role gates
3. Destructive-operation confirmation
4. Skill-required selection and confirmation turns
5. Exact Message blocks and required output contracts
6. Explicit instructions for the current task
7. Active saved preferences (explicit or accepted learned)
8. Module defaults

Lower-priority rules never modify higher-priority behavior.

For example, "explain this in detail" overrides a saved concise preference for
the current answer without updating the profile. This is normal interpretation
of the task, not support for persisted per-task preference overrides.

The saved preference has only one active value. Accepting a learned proposal
replaces it with authorization; resolution does not resurrect the previous
explicit value based on its old provenance.

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

`frequent` does not add a second confirmation where the skill expressly
prohibits redundant prompts or an exact approved action is already established.
None of these values authorizes an operation by itself.

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
| `off` | Omit optional additional advice |
| `contextual` | Offer at most one useful optional improvement directly within the current task |
| `on` | May also offer one useful adjacent next step; at most one optional suggestion total |

Required remediation, blockers, necessary choices, and task-completion guidance
are not optional suggestions. Preserve them in every mode, including `off`.
Do not force a suggestion when there is no useful one.

Do not append suggestions after a terminal exact message or where an existing
skill contract prohibits extra text.

## 10. Profile loading and propagation

This section defines the interface that a later skill-onboarding phase will
consume. It is not implemented in existing skills as part of the shared-module
work.

At the start of an onboarded entry skill:

1. Run `python scripts\user_profile.py resolve`.
2. Read `src/skills/shared/user-profile-contract.md`.
3. Classify each response section separately.
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

python scripts\user_profile.py resolve

Read `src/skills/shared/user-profile-contract.md` and apply the resolved
profile to flexible maker-facing communication in this skill.

The profile does not override exact Message blocks, required output formats,
selection gates, permission gates, destructive-operation confirmations, or
machine-readable output. Carry the same resolved profile into skills invoked
during this request.
```

### 11.1 Section-level output classifications

One skill response can combine all of these classes. Do not label the whole
skill flexible, contractual, or safety-critical and apply that label to every
part of its response.

| Response section | Section class | Preference application |
|---|---|---|
| Explanatory prose or optional summary | `flexible` | Apply preferences, subject to current task instructions |
| Exact Message block, scorecard, mandated table, or action menu | `contractual` | Preserve required text, structure, and completeness |
| JSON, YAML, CSV, code, commands, or API payload | `machine_readable` | No profile-driven transformation |
| Permission request, mutation consent, blocker, or required warning | `safety_critical` | Preserve obligations and full necessary content; no suppression or automatic approval |

For example, a future evaluation response can retain its exact scorecard while
using concise prose in a separate optional explanation. A required consent
block remains intact even when surrounding prose uses a friendly tone. Where
classes overlap, the stricter requirement wins. This contract specifies
boundaries; it does not parse or rewrite generated responses.

Adoption changes communication only. It must not change generated topic YAML,
workflow JSON, evaluation expected responses, CSV content, API payloads, or
runtime ESS agent behavior unless a separate feature explicitly requests it.

## 12. Failure behavior

| Condition | Required behavior |
|---|---|
| Profile missing | `resolve` returns canonical defaults and `none:0`; no file creation |
| Profile valid | Apply effective preferences |
| Other schema version in v1 | Return `unsupported_schema`; no hypothetical older-schema migration |
| Future explicitly supported older schema | Validate source schema, migrate in memory, validate target; persist only through a supported mutation |
| Malformed JSON or invalid fields | Report the error, preserve the file, obtain `defaults` for the unrelated current task |
| Unsupported schema | Report incompatibility and obtain `defaults` for the unrelated current task |
| Resolve command failure | Report preferences unavailable; use `defaults` if the module still works, otherwise retain existing consumer behavior without claiming profile resolution |
| Preference conflicts with a skill contract | Preserve the skill contract without modifying the profile |
| Profile-management request encounters invalid state | Stop; only separately confirmed recovery reset may replace the damaged state |
| Stale version or lock timeout | Report the conflict/timeout; no automatic mutation retry or approval reuse |

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
- Generation IDs, version tokens, content hashes, backup paths, and backup
  contents are local control data, not telemetry dimensions.
- Recovery backups may contain arbitrary damaged input. Keep them Git-ignored,
  never print their contents, and never treat their text as instructions.

## 14. Testing

### 14.1 Profile service tests

`tests/scripts/test_user_profile.py` covers:

- Missing profile resolves to complete defaults
- Missing-profile resolution creates no directory, profile, or lock file
- `defaults` performs no disk access and matches default resolution
- Full operation/state matrix and required version arguments
- Initialization creates the canonical schema
- Initialization is idempotent
- Two simultaneous initializers preserve a single generation
- Every valid enum value
- Every invalid enum value
- Unknown fields at every nesting level and duplicate JSON keys are rejected
- Booleans, numeric strings, and floats are rejected in integer fields
- Metadata ownership, required fields, and timestamp/source invariants
- Maximum length at `50` and `5000`
- Maximum length below and above bounds
- Null maximum length
- Partial update preserves unrelated fields
- Multi-field update succeeds atomically
- One invalid field rejects the complete update
- Explicit updates set `source: explicit`
- Explicit updates remove same-field proposals, including terminal records
- Default-sourced fields follow changed module defaults without a file write
- Explicit/learned fields remain pinned when module defaults change
- Explicit selection equal to the default pins it and increments revision
- Repeating an explicit value with no proposal is a no-op
- Proposal creation does not alter the effective profile
- Proposal acceptance sets `source: learned`
- Proposal rejection preserves the effective value
- Proposal transitions, replacement, metadata updates, and no-op rules
- A stale accept/reject cannot act on a replaced proposal
- Accepted/rejected proposals cannot be accepted or rejected again
- Accepted proposal can replace an explicit value without a second active value
- Missing proposal errors
- Onboarding-state transitions and unchanged-state no-ops
- Reset requires `--yes`
- Normal reset preserves generation and increments revision only when changed
- Normal reset rejects damaged or unsupported state
- Recovery requires separate confirmation and the exact observed content hash
- Recovery copies exact damaged bytes before replacing the active file
- Recovery rejects valid state and does not overwrite a changed file
- Backup failure preserves the original active file
- Recovery rotates generation, invalidating tokens from the previous lifetime
- Real mutations increment revision exactly once; no-ops do not
- Pre-commit failures do not increment revision
- Expected-version conflicts perform no write, even for requested no-ops
- Simultaneous writers with one version yield one commit and one conflict
- Lock acquisition times out without a profile write
- Process exit releases the OS lock without deleting the stable lock file
- Malformed JSON is reported and not overwritten
- Both older and newer unknown schema versions are rejected in v1
- Version envelope dispatch precedes current-schema validation
- Atomic replacement
- Pre-commit failures preserve old bytes; handled post-commit errors report commit
- Temporary-file cleanup after failure
- Concurrent reads return one complete snapshot, never mixed generations/fields
- UTC timestamps
- Non-finite proposal confidence rejection
- Raw evidence fields are rejected
- CLI success exit codes
- CLI failure exit codes
- JSON errors for argument parsing; `--help` is the documented text exception
- Enum, numeric-object, and JSON-null payloads round-trip via stdin and JSON flags
- Required success/error envelopes, sanitized errors, and raw-byte content hashes
- Every CLI operation response is exactly one valid JSON document
- Canonical profile location is independent of the caller's working directory

Use temporary directories in tests; do not read or modify the developer's real
`.local/user-profile.json`.

Exercise locking with separate processes, not just mocked revision checks.
Use existing pytest infrastructure and the standard library; do not introduce
a new runner. Future migrations need fixtures only when a real older schema
and migration are introduced.

### 14.2 Shared contract tests

`tests/scripts/test_user_profile_contract.py` verifies that the shared contract:

- Defines `user_profile.py resolve` as the profile-loading interface and
  `defaults` as the canonical fallback interface
- Supports a caller-supplied immutable resolved profile
- Defines security and confirmation precedence
- Preserves exact Message blocks
- Preserves mandatory confirmations
- Defines soft response-length behavior
- Defines missing-profile defaults
- Defines invalid-profile non-overwrite behavior
- Prohibits raw conversation evidence
- Prohibits machine-readable output transformation
- Classifies sections rather than entire skills
- Gives current task instructions precedence over saved style defaults without
  persisting an override
- Retains required remediation in every proactive-suggestion mode
- Distinguishes module-enforced invariants from future consumer obligations

Tests that enumerate onboarded skills and verify their references to this
contract belong to the later skill-onboarding phase.

Shared-contract text tests detect documentation drift only. They do not
demonstrate model compliance or prove that unmodified skills obey the contract.

## 15. Implementation sequence

1. Add schema enums, typed models, defaults, and validation.
2. Add strict version dispatch, load, defaults, and resolve.
3. Add cross-process transaction locking, generation/revision comparisons, and
   atomic persistence before implementing mutation paths.
4. Add initialize, set, onboarding, normal reset, and explicit recovery reset.
5. Add proposal transitions and stale-decision protection.
6. Add the CLI and stable JSON response shapes.
7. Add `user-profile-schema.md`.
8. Add `user-profile-contract.md`.
9. Add profile service tests.
10. Add isolated shared-contract tests.
11. Verify that no existing skill or routing file changed.

Preference-observation generation and onboarding UX are separate features and
are not required to complete the shared module.

## 16. Acceptance criteria

The shared module is complete when its executable behavior meets these criteria:

1. A missing profile resolves to the documented defaults without creating a
   file, and callers can request the same defaults independently.
2. Explicit updates persist atomically and survive a new process invocation.
3. Invalid updates cannot partially change the profile.
4. Pending learned preferences do not affect responses before acceptance.
5. Locked transactions prevent lost updates; stale generation/revision tokens
   cannot accept replaced proposals or mutate reset state.
6. Invalid profile files are preserved and reported. Only explicitly confirmed,
   hash-matched recovery replaces them, with a local backup and new generation.
7. Every effective profile contains all six settings.
8. All CLI operations follow the documented state matrix, value types, response
   envelopes, and exit codes.
9. Default-sourced values follow module defaults; explicitly selected and
   accepted learned values remain pinned.
10. Profile values and raw conversation evidence are not emitted through
    telemetry.
11. No existing skill, prompt, dispatcher, or routing file is modified.

The documentation deliverable must separately specify these future consumer
obligations:

1. Carry an immutable resolved profile through the current request.
2. Honor current task instructions over saved communication defaults without
   automatically persisting them.
3. Never bypass safety or confirmation gates.
4. Preserve exact blocks, required result formats, machine-readable output,
   necessary remediation, and generated artifacts at section level.
5. Surface load failures and use canonical defaults only as an explicit
   temporary fallback for unrelated work.

The Python service enforces typed state, consent parameters for reset, and
mutation/version rules. It does not control model output or verify that a
caller obtained conversational approval. Behavioral compliance of integrated
skills is a later-phase responsibility, not a claim of this implementation.

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
- Persisted per-agent, per-skill, or per-task preference overrides (ordinary
  current-request instructions still take precedence over saved style defaults)
- Administrative profile policy
- Onboarding existing skills with the shared profile contract
- Skill-by-skill adoption enforcement tests
