# User profile persisted schema

The user profile is local typed data owned exclusively by
`scripts/user_profile.py`. It is stored at `.local/user-profile.json` relative
to the ESS Maker Kit solution root. It is never an instruction source, an agent
workspace file, an identity record, or a cloud-synchronized artifact.

## Version 1 shape

The complete persisted object contains:

- `schemaVersion`: integer `1`.
- `generation`: canonical random UUID v4. It changes only during initialization
  or an explicitly confirmed recovery reset.
- `revision`: positive integer incremented exactly once per semantic mutation.
- `onboarding`: `{ "status", "updatedAt" }`.
- `preferences`: exactly the six preference records below.
- `proposals`: zero or one proposal per documented preference.

Every object is closed: unknown fields, duplicate JSON keys, missing required
fields, non-finite numbers, numeric strings, and booleans used as numbers are
invalid. Strings are case-sensitive and are never coerced.

| Preference | Value | Default |
|---|---|---|
| `responseFormat` | `auto`, `prose`, `bullets`, `steps`, `table_first` | `auto` |
| `detailLevel` | `concise`, `balanced`, `detailed` | `balanced` |
| `toneOfVoice` | `direct`, `friendly_professional`, `formal`, `empathetic` | `friendly_professional` |
| `confirmationFrequency` | `minimal`, `standard`, `frequent` | `standard` |
| `maximumResponseLength` | `{ "value": null or 50..5000, "unit": "words" }` | null words |
| `proactiveSuggestions` | `off`, `contextual`, `on` | `contextual` |

Each preference also has `source`, one of `default`, `explicit`, or `learned`,
and `updatedAt`. A default source requires a null timestamp. Explicit and
learned sources require a UTC ISO 8601 timestamp ending in `Z`.

`onboarding.status` is `not_started`, `deferred`, or `completed`.
`not_started` uses a null timestamp; explicit state changes use a UTC timestamp.

## Default and revision semantics

A stored default value is a snapshot, not a pinned selection. Resolution uses
the current module default whenever `source` is `default`, without rewriting
the file. Explicit and accepted learned values remain pinned. A mutation checks
both generation and revision, increments revision once when state changes, and
does not write for a semantic no-op.

## Proposal shape and transitions

A proposal contains `proposedValue`, positive integer `observationCount`,
finite `confidence` from `0.0` through `1.0`, `status`, `createdAt`, and
`updatedAt`. Status is `pending`, `accepted`, or `rejected`; updated time cannot
precede created time. `proposedValue` uses the matching preference value shape.
Raw prompts, responses, transcripts, evidence text, and arbitrary extensions
are prohibited.

A pending proposal never changes the effective profile. Acceptance copies its
value to the active preference with source `learned`; rejection leaves the
active preference unchanged. Re-proposing the same pending value updates only
changed observation metadata and preserves `createdAt`. A different value or a
proposal after a terminal decision creates a fresh pending record. An explicit
set removes the proposal for that field.

## Migration and round trips

Version 1 supports only schema version `1`; no version 0 schema or migration is
defined. Version dispatch inspects the minimal `schemaVersion` envelope before
current-schema validation. Unsupported versions are preserved and reported.
Future migrations must validate their source schema, migrate in memory, then
validate the current target schema. Reads never persist migrations.

A valid document round-trips all owned fields without adding extension data.
Malformed or unsupported bytes are never repaired automatically. Recovery
requires explicit confirmation, the SHA-256 hash of the exact observed bytes,
an exact local backup, and a new generation.

## Separate experience state

The service also owns `.local/user-profile-experience.json`. It is a separate
schema version 1 document, not an extension to the profile schema above. Its
complete root contains only `schemaVersion`, `generation`, `revision`,
`profileGeneration`, `eligibleRunCount`, `onboardingPrompt`,
`proposalPrompts`, `requestReceipts`, and `pendingProfileChange`.

Experience generations and revisions form an independent opaque token. Missing
state is `none:0`; missing-state defaults are in memory only and never invent
a persisted generation. The state stores only bounded reminder counts,
suppression, proposal-created-at control tokens, request UUID receipts, and
transition hashes. It never stores preference values, raw answers, messages,
persona labels, user identifiers, or skill names.

Every experience object is closed and strictly validated. It rejects duplicate
JSON keys, unknown or missing fields, unsupported schema versions, invalid
UUID v4 tokens, non-integer counts, invalid UTC timestamps, receipts out of run
order, and malformed hashes. Keep at most 64 unique receipts. Proposal prompt
state is keyed only by the six preference fields and is discarded when its
proposal identity no longer matches the profile.

Profile and experience files are siblings protected by the existing stable
`user-profile.lock`. First profile binding, reset, and recovery use a durable
pending intent embedded in experience state; no third journal is permitted.
Writers reconcile only by comparing exact profile bytes/hash and version to
the intent's before/after image. A mismatch blocks writes until explicit
hash-confirmed repair. Profile-only saves remain possible when experience
state is damaged and return a cadence-unavailable warning. See the
user-profile-experience implementation specification for the complete
transaction and repair contract.
