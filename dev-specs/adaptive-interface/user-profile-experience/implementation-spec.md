# User Profile Experience and Skill Adoption - Implementation Specification

## 1. Purpose

Implement the maker-facing experience that populates, reviews, edits, and
applies the shared user profile defined by
`../user-profile-shared-module/implementation-spec.md`.

This phase turns the existing profile service into an end-to-end experience:

- A first-use invitation that never blocks the requested skill.
- A five-question working-style quiz that captures all six preferences.
- A review step with a derived persona, plain-language summary, and preview.
- Explicit save, defer, retake, edit, reset, and recovery experiences.
- Natural-language profile changes with typed mapping and confirmation.
- Presentation and decisions for pending learned-preference proposals.
- Adoption of one immutable resolved profile across onboarded skills.
- A chat-only style indicator and `/profile` management entry point.

The profile continues to personalize maker-facing ESS Maker Kit communication.
It does not personalize runtime ESS employee experiences.

## 2. Product decisions

The following decisions are fixed for this implementation:

1. **Chat-only surface.** Use the current GitHub Copilot and VS Code chat
   experience. Do not build a companion VS Code extension, persistent header
   pill, custom webview, or sidebar.
2. **Separate experience state.** Keep persisted preference schema version 1.
   Store onboarding re-prompt cadence and proposal-presentation cadence in a
   separate local file owned by `scripts/user_profile.py`.
3. **Confirmed free-text mapping.** A skill may interpret a natural-language
   answer as one or more typed profile values, but it must show the mapping and
   receive confirmation before treating it as the user's answer.
4. **Derived personas.** Persona names are deterministic presentation metadata.
   They are never persisted.
5. **Proposal UI only.** Present, accept, reject, and snooze pending proposals.
   Automatic observation generation and deciding when to call `propose` remain
   deferred.
6. **Skipped questions remain defaults.** Initial-onboarding questions that the
   maker skips retain `source: default` when no saved preference exists.
   Existing values and sources are always preserved for skipped fields. Only
   answered preferences are saved with `source: explicit`.
7. **Proposals follow task completion.** Automatic preference proposals appear
   only after the requested task completes and only when its output contract
   permits additional content. They never interrupt the task.
8. **Count-based reminders.** Onboarding re-offers and proposal snoozes use
   eligible top-level skill-run counts, not elapsed time. Returning after a
   long absence does not reset counts or trigger a reminder by itself.
9. **Optional tips and onboarding are separate.** `proactiveSuggestions: off`
   suppresses automatic learned-preference proposals, but not the one final
   onboarding reminder after three eligible requests. `Not again` suppresses
   that onboarding reminder. Pending proposals remain accessible through
   `/profile` regardless of the optional-tips setting.
10. **Abandoned quiz.** Discard unsaved answers, but retain the invitation
    claim. Continue future tasks with existing preferences or defaults. After
    three later eligible requests, permit only the one final invitation.
11. **Independent detail and length.** A detail answer never implicitly saves
    a word limit. A prefilled limit is saved only when explicitly accepted.
12. **Shared presentation.** A deterministic service helper derives persona
    names. A common, clearly labeled example supplies previews; previews never
    claim that a real task ran.
13. **Profile management before setup.** `/profile` and unambiguous maker-style
    requests work without an agent, environment, authentication, or completed
    foundation setup. They do not grant access to other gated operations.

These are checkout-local choices, not authenticated-user tracking. One maker
per checkout is still assumed. Other clones start independently.

## 3. Scope

### 3.1 In scope

- Shared chat orchestration for profile resolution and onboarding eligibility.
- `/profile` prompt and profile-management skill.
- Five-question onboarding flow.
- Draft profile review and explicit completion.
- Chat-compatible style indicator.
- Natural-language current-request overrides and persistent change requests.
- Composite service operations required for atomic onboarding completion.
- Local experience-state persistence and cadence decisions.
- Pending proposal presentation and decision handling.
- Skill adoption and immutable profile propagation.
- Tests for service behavior, prompt/skill contracts, and adoption coverage.

### 3.2 Out of scope

- A custom VS Code extension or graphical profile editor.
- Clickable persistent pills or after-response chips.
- Cloud synchronization or profile upload.
- Profiles scoped per agent, skill, repository branch, or task.
- Multiple operating-system users sharing one checkout.
- Runtime employee personalization.
- Automatic preference observation or confidence calculation.
- Storing raw prompts, responses, transcripts, or free-text answers.
- Free-form custom tone or behavioral instructions.
- Model-compliance claims beyond deterministic contract tests.

## 4. Repository changes

Add:

```text
dev-specs/adaptive-interface/user-profile-experience/
`-- implementation-spec.md

solutions/ess-maker-skills/
|-- .github/prompts/
|   `-- profile.prompt.md
|-- scripts/
|   `-- user_profile.py                    # Extend existing service and CLI
|-- src/skills/
|   |-- user-profile/
|   |   |-- SKILL.md
|   |   |-- onboarding.md
|   |   |-- editor.md
|   |   `-- proposals.md
|   `-- shared/
|       |-- user-profile-entry.md
|       |-- user-profile-contract.md       # Extend consumer obligations
|       `-- user-profile-schema.md         # Reference experience state separately
`-- .local/
    |-- user-profile.json                  # Existing, runtime-generated
    `-- user-profile-experience.json       # New, runtime-generated

tests/scripts/
|-- test_user_profile.py                   # Extend service coverage
|-- test_user_profile_experience.py
|-- test_user_profile_contract.py          # Extend behavior coverage
|-- test_user_profile_onboarding_contract.py
|-- test_user_profile_adoption.py
`-- user_profile_adoption_manifest.json    # Exact paths/modes/protected anchors
```

Modify:

- `solutions/ess-maker-skills/.github/copilot-instructions.md`
- Every routable top-level prompt or entry skill covered by section 15.

Do not add Git exceptions. `solutions/ess-maker-skills/.gitignore` already
ignores `.local/**`.

## 5. Architecture

### 5.1 Persistence owner

`scripts/user_profile.py` remains the only owner of both:

- `.local/user-profile.json`
- `.local/user-profile-experience.json`

Skills and prompts must not read, parse, or write either file directly. They
invoke the service and consume its structured JSON output.

### 5.2 Authority boundaries

The persisted profile is authoritative for:

- Active preference values and sources.
- Onboarding status.
- Profile generation and revision.
- Learned-preference proposal state.

The experience-state file is advisory and authoritative only for:

- Deferred-onboarding re-prompt cadence.
- Permanent suppression of automatic onboarding invitations.
- Pending-proposal presentation and snooze cadence.

Experience-state damage must never prevent a skill from using a valid profile.
Profile damage must continue to follow the shared-module recovery contract.
Extend all existing profile-writing paths to honor the transition protocol in
section 6.5; introducing new entry commands without updating old writers would
leave reset/recovery races unresolved.

### 5.3 Request orchestration

At each top-level eligible request:

1. Route intent and apply the branch's existing admission/capability gates.
   Select the mode in the section 15 manifest. Do not universally require
   completed setup for branches that already work before setup.
2. The entry owner obtains one combined profile/experience snapshot through
   `experience resolve`, not separate unrelated reads. Profile-management
   requests use the same read interface but never count as skill runs.
3. For an eligible entry, create one random request UUID in conversation
   context and call `experience begin` using both observed version tokens.
   This operation counts the request and atomically claims any onboarding
   invitation. It never claims a learned-preference proposal.
4. If onboarding is accepted, retain the original request, target selections,
   and draft answers in conversation context. Do not start domain mutations
   until the maker saves or cancels the quiz.
5. Save, defer, or cancel returns to the same original request UUID. Never call
   `begin` again or count confirmation answers/nested calls as new runs.
6. After a successful profile save or deferral, resolve a fresh snapshot for
   the domain execution phase. This is the one allowed pre-execution snapshot
   replacement. Cancel without saving keeps the original snapshot.
7. Freeze that execution snapshot through the complete nested skill chain.
   Persistence checks may read current versions, but must not silently replace
   communication context.
8. At successful task completion, the entry owner may call `experience finish`
   to claim one eligible proposal, subject to optional-tips and output rules.
   A proposal decision affects only future domain requests.

No nested skill re-resolves the profile when the caller supplied one.
Section 8 defines the context fields, ownership, and replay behavior.

## 6. Experience-state schema

### 6.1 Canonical path

```text
.local/user-profile-experience.json
```

Resolve it relative to the ESS Maker Kit solution root unless tests pass an
explicit path. Profile and experience paths must be siblings sharing one lock
directory; reject mismatched parents rather than accidentally acquiring
different locks.

### 6.2 Version 1 shape

Example after the first invitation is claimed, before a profile is saved:

```json
{
  "schemaVersion": 1,
  "generation": "11111111-2222-4333-8444-555555555555",
  "revision": 1,
  "profileGeneration": null,
  "eligibleRunCount": 1,
  "onboardingPrompt": {
    "promptCount": 1,
    "lastPromptRun": 1,
    "suppressed": false,
    "lastPromptedAt": "2026-10-15T16:00:00Z"
  },
  "proposalPrompts": {},
  "requestReceipts": [
    {
      "requestId": "22222222-3333-4444-8555-666666666666",
      "beginProfileVersion": "none:0",
      "runNumber": 1,
      "onboardingOffer": "initial",
      "finished": false,
      "proposalField": null
    }
  ],
  "pendingProfileChange": null
}
```

Experience has its own random generation and positive revision. Its opaque
token is `<experience-generation>:<revision>`; missing state is `none:0`.
This is independent of the profile token. Never use revision alone as a
concurrency token.

Each `proposalPrompts` value has exactly:

```json
{
  "proposalCreatedAt": "2026-10-15T15:00:00Z",
  "promptCount": 1,
  "lastPromptRun": 4,
  "snoozedAtRun": null,
  "suppressed": false,
  "lastPromptedAt": "2026-10-15T16:00:00Z"
}
```

`lastPromptRun` is the global `eligibleRunCount` when the prompt was claimed.
Do not maintain separate incrementing counters for every pending proposal.
`createdAt` is the proposal identity within a profile generation; proposal
replacement must assign a strictly later `createdAt` for that field, even when
the clock repeats or moves backwards. Existing `propose` must enforce this
without adding a field to profile schema v1.

### 6.3 Validation

- Require the complete documented shape.
- Reject unknown fields and duplicate JSON keys at every level.
- `schemaVersion` is integer `1`.
- Persisted `revision` is positive. `eligibleRunCount` is nonnegative.
  `promptCount` is an integer from zero through two. Booleans, floats, numeric
  strings, and non-finite numbers are invalid in numeric fields.
- `generation` and request IDs are canonical UUID v4 strings.
- `profileGeneration` is a canonical UUID v4 string, or null while no valid
  associated profile exists. This includes the explicitly hash-authorized
  experience-repair case when the profile is damaged. It never makes a damaged
  profile valid or eligible for automatic prompting.
- `suppressed` and `finished` require JSON booleans.
- `lastPromptRun` and `lastPromptedAt` are both null for a never-claimed prompt
  (`promptCount: 0`); both are required after a claim. Run numbers are positive
  and cannot exceed `eligibleRunCount`. Timestamps are UTC ISO 8601 with a `Z`
  suffix; they are not used to calculate reminder eligibility.
- Missing-state defaults use zero runs/counts, null prompt markers, false
  suppression, empty maps/receipts, and no pending change. Missing defaults
  have no invented persisted generation.
- `proposalPrompts` keys are limited to the six preference fields.
- `proposalCreatedAt` is a control token copied from proposal metadata, not
  user content.
- `snoozedAtRun` is required on proposal-prompt records: null or an integer
  from zero through `eligibleRunCount`. Explicit review can snooze before any
  automatic claim; it must not invent a nonzero prompt count.
- Do not store preference values, free-text answers, persona labels, raw
  messages, or skill names in experience state.
- Receipts have unique request IDs and increasing run numbers. Keep the latest
  64 receipts, removing only the oldest when appending. Receipt enum values
  and version tokens must validate strictly. `proposalField` is null or one of
  the six fields; `onboardingOffer` is `none`, `initial`, or `deferred_reoffer`.
- `pendingProfileChange` is null or the closed object specified in section 6.5.
- Inspect the minimal experience `schemaVersion` envelope before validating
  current fields. Unsupported versions are preserved, not migrated implicitly.

### 6.4 Lifecycle and reconciliation

- Missing experience state resolves to in-memory defaults and does not create a
  file.
- The first `experience begin` may create experience state while the profile
  is still missing. This records invitation claims, not quiz answers.
- Missing profile plus `profileGeneration: null` is a valid association. Keep
  its prompt counts across abandoned quizzes and new chat sessions.
- First profile creation binds existing unbound experience state to the new
  profile generation and preserves invitation history.
- A mismatched profile generation invalidates all old cadence, receipts, and
  decisions. Fresh experience state gets a new experience generation.
  Resolution retains the old physical experience token for comparison and
  marks the association stale; it does not invent a new token during a read.
  The next locked experience write compares that old token, creates the fresh
  lifetime, and returns its new token.
- An externally deleted profile with a non-null old association is treated as
  an invalidated lifetime, not as the old maker's unbound history.
- If onboarding is `completed`, onboarding cadence fields are ignored.
- If a proposal record no longer exists or its `createdAt` differs from
  `proposalCreatedAt`, its old presentation state is ignored and removed on the
  next experience mutation.
- Normal reset also resets experience state and rotates its generation even
  though the profile generation stays unchanged. A default profile may be a
  profile no-op while experience reset is still a real change.
- Recovery rotates the profile generation and invalidates experience state.
- Reads never overwrite damaged state. If a pending change is found, combined
  resolution returns a cadence warning and no automatic prompt. A separate
  `experience reconcile` command settles it before a subsequent entry attempt.
- Completing onboarding suppresses automatic invitations through profile
  status, without requiring a second write to clear historical prompt counts.
  Removing/deciding a proposal makes its cadence record irrelevant immediately;
  prune obsolete records during the next experience write.

### 6.5 Persistence and locking

Use the existing stable `user-profile.lock` and the same five-second lock
protocol. Serialize every profile/experience read-compare-write sequence under
that lock.

Write experience state with the same temporary sibling, UTF-8 JSON, flush,
supported `fsync`, and `os.replace` pattern.

Ordinary preference saves, proposal decisions, and onboarding-status updates
do not need to rewrite experience state. Derived rules above make completion
and terminal decisions effective immediately.

First profile creation (when unbound experience state exists), normal reset,
and recovery cross a file/lifetime boundary. Use a small durable intent inside
the existing experience file; do not add a third journal file:

```json
{
  "operation": "reset",
  "beforeVersion": "11111111-2222-4333-8444-555555555555:5",
  "beforeContentHash": "<SHA-256 of original bytes, null when missing>",
  "afterVersion": "11111111-2222-4333-8444-555555555555:6",
  "afterContentHash": "<SHA-256 of exact serialized candidate bytes>",
  "experienceEffect": "reset"
}
```

Allowed operations are `initialize`, `onboarding-complete`, `profile-save`,
`onboarding-defer`, `reset`, and `recover`. Effects are `bind` and `reset`.
Hash strings are lowercase 64-character SHA-256 digests, never raw content.
`beforeVersion` is null only for damaged/unsupported profile recovery, whose
hash is required; use `none:0` for an absent profile. The after version is
always a valid persisted-profile token.

Under one lock:

1. Validate input, observed tokens, the candidate profile, and the intended
   experience effect. Compute the candidate's exact bytes and hash.
2. Persist the intent, incrementing experience revision. If this fails, do not
   write the profile.
3. Atomically replace the profile. This is the profile commit point.
4. Finalize experience state: `bind` preserves cadence/receipts and associates
   the new profile generation; `reset` creates fresh counters/receipts and a
   new experience generation. Remove the intent.
5. A failure after step 3 reports `committed: true`, the committed profile
   version, and `experienceCommitted: false`; never report an ordinary
   retry-safe failure or roll the profile back.

Every writer, including existing `initialize`, `set`, `onboarding`, `propose`,
`accept`, `reject`, and reset variants, checks pending intent before writing:

- Current bytes match `afterContentHash` and after version: finalize the effect.
- Otherwise they match `beforeContentHash` and before version (or are still
  missing): remove the uncommitted intent, preserving old cadence.
- Neither matches: report `experience_reconciliation_required`, suppress
  automatic prompting, and require explicit experience repair. Do not guess
  whether an external edit committed the intended operation.
- Check the after case first. For a profile-no-op reset, before and after can
  match; the confirmed intent still authorizes the experience reset.
  Use the original bytes/hash as the after image for such a no-op; do not
  reserialize or replace an unchanged profile merely to finalize reminder state.

Reconciliation never rewrites the profile or replays the mutation. It is
idempotent and completes under the same lock. If reconciliation changes the
observed experience token, a subsequent consent-based experience mutation must
return a conflict rather than reuse an old decision. A new profile read after
pre-entry reconciliation is allowed before freezing domain execution context.

When no experience file exists, there is no old reminder state to invalidate:
profile creation/reset can commit alone and missing experience defaults remain
correct. Do not manufacture an experience file for a plain `initialize`.

Malformed, unsupported, or unreadable experience state must not prevent a
valid profile-only save, reset, or recovery. In that case leave it untouched,
perform the independently authorized profile mutation, and return an explicit
cadence-unavailable warning. Automatic invitations remain disabled until
experience repair succeeds. A valid but unresolved intent is different: block
further writers until reconciliation or explicit repair, so no writer hides an
unfinished transaction.

### 6.6 Experience repair and reset

Experience repair is separate from profile recovery. `/profile` offers
`Repair reminder history` when only experience state is damaged.

- Require confirmation, the observed experience byte hash, and the observed
  profile token, including `none:0` when missing. If the profile is damaged,
  require its exact observed content hash instead; never trust its version.
  These two profile preconditions are mutually exclusive.
- Under the lock, compare hashes/tokens before writing.
- Preserve exact experience bytes in an exclusive
  `user-profile-experience.recovery.<uuid>.bak`, flushing it with the existing
  persistence policy before replacement.
- Replace only experience state. Never reset preferences as a side effect.
- Use a new experience generation. If past invitation history is unavailable,
  start with onboarding `suppressed: true` and `promptCount: 0` to avoid
  unwanted re-invitation; `/profile` still permits explicit onboarding.
- For pending proposals without trusted history, default to automatic prompt
  suppression for those proposals, with explicit review still available.
- With a damaged profile, set `profileGeneration: null` and keep automatic
  prompting disabled by the profile error. Repair profile separately afterward.
  This path also breaks the deadlock where an unmatched valid pending intent
  blocks profile recovery: back up the intent-bearing experience bytes before
  explicitly resetting them. Never silently discard the intent.
- An explicit normal `Reset my style` resets both healthy states and permits a
  fresh onboarding invitation. Explain this difference in confirmation copy.
- Backup failure leaves the original unchanged. Unreadable bytes cannot be
  safely repaired by hash; report the I/O problem rather than overwriting.
- A healthy experience-only reset requires both current version tokens and
  confirmation; never resets its revision without rotating its generation.

## 7. Service extensions

### 7.1 New internal types

Add frozen typed models:

```python
@dataclass(frozen=True)
class OnboardingPromptState:
    prompt_count: int
    last_prompt_run: int | None
    suppressed: bool
    last_prompted_at: str | None

@dataclass(frozen=True)
class ProposalPromptState:
    proposal_created_at: str
    prompt_count: int
    last_prompt_run: int | None
    snoozed_at_run: int | None
    suppressed: bool
    last_prompted_at: str | None

@dataclass(frozen=True)
class ExperienceState:
    schema_version: int
    generation: str
    revision: int
    profile_generation: str | None
    eligible_run_count: int
    onboarding_prompt: OnboardingPromptState
    proposal_prompts: Mapping[str, ProposalPromptState]
    request_receipts: tuple[RequestReceipt, ...]
    pending_profile_change: PendingProfileChange | None

@dataclass(frozen=True)
class ExperienceResolution:
    profile: EffectiveProfileResult
    state_exists: bool
    experience_version: ExperienceVersion | None
    cadence_available: bool
    warnings: tuple[ExperienceWarning, ...]
```

Define frozen `RequestReceipt`, `PendingProfileChange`, `ExperienceWarning`,
and `ExperienceVersion` models from section 6's closed shapes. Use enums for
action/status values. `ExperienceVersion` validates the same token grammar as
`ProfileVersion`, but tokens refer to different documents and cannot be
substituted for each other.

Read resolution does not grant permission to display an automatic prompt.
Only a successful locked claim returns an actionable `onboardingOffer` or
`proposalField`.

### 7.2 New service functions

Implement independently of CLI parsing:

```python
load_experience_state(path: Path) -> ExperienceState
validate_experience_state(document: object) -> ExperienceState
resolve_experience(
    profile_path: Path,
    experience_path: Path,
) -> ExperienceResolution
begin_profile_request(
    profile_path: Path,
    experience_path: Path,
    request_id: str,
    *,
    expected_profile_version: ProfileVersion,
    expected_experience_version: ExperienceVersion,
) -> ExperienceMutationResult
finish_profile_request(
    profile_path: Path,
    experience_path: Path,
    request_id: str,
    *,
    expected_profile_version: ProfileVersion,
    expected_experience_version: ExperienceVersion,
    outcome: TaskOutcome,
    allows_extra_content: bool,
    optional_suggestion_used: bool,
) -> ExperienceMutationResult
complete_onboarding(
    profile_path: Path,
    experience_path: Path,
    updates: Mapping[str, object],
    *,
    expected_profile_version: ProfileVersion,
    confirmed: bool = False,
) -> CompositeMutationResult
defer_onboarding(
    profile_path: Path,
    experience_path: Path,
    request_id: str,
    *,
    expected_profile_version: ProfileVersion,
) -> CompositeMutationResult
suppress_onboarding_offer(
    profile_path: Path,
    experience_path: Path,
    *,
    expected_profile_version: ProfileVersion,
    expected_experience_version: ExperienceVersion,
    confirmed: bool = False,
) -> ExperienceMutationResult
snooze_proposal_prompt(
    profile_path: Path,
    experience_path: Path,
    field: str,
    proposal_created_at: str,
    *,
    expected_profile_version: ProfileVersion,
    expected_experience_version: ExperienceVersion,
    origin: PromptOrigin,
) -> ExperienceMutationResult
reset_experience_state(
    profile_path: Path,
    experience_path: Path,
    *,
    expected_profile_version: ProfileVersion,
    expected_experience_version: ExperienceVersion,
    confirmed: bool = False,
) -> ExperienceMutationResult
```

Also expose `reconcile_experience_state` and `recover_experience_state` with
the tokens/hashes and confirmations in sections 6.5-6.6, plus
`describe_profile(effective: EffectiveProfile) -> ProfilePresentation` for
section 11.2. Keep their implementation in the existing service.

`TaskOutcome` is `completed`, `failed`, `cancelled`, or `blocked`. The caller
reports the actual task outcome; the service does not infer task success.
`PromptOrigin` is `automatic` or `explicit`.

`resolve_experience` reads the profile and experience under one lock and builds
the effective profile from that single profile snapshot. Expose the existing
resolution logic internally rather than calling a function that re-reads the
file. A missing parent directory returns defaults without creating anything.
For an existing parent, lock creation is allowed for the combined read. The
original `resolve` and `defaults` retain their original no-write contracts.

Profile-only saves compare only the profile token. Do not reject an approved
quiz save merely because another chat incremented experience counts.
Experience decisions compare both tokens. All current-state validation and
pending-intent checks still happen inside the shared lock.

### 7.2.1 Request receipts and prompt claims

`begin_profile_request` validates a random request UUID and observed tokens.
Under the lock:

1. If a matching receipt exists with the same observed starting profile
   version and that profile version is still current, return `replayed: true`,
   `changed: false`, and no display action. Do not count or show a prompt again.
2. Otherwise compare both tokens before making any change. On mismatch return
   conflict; do not silently refresh and retry a count or claim. A known ID
   with a different profile version is a conflict, not a new request.
3. Increment `eligibleRunCount` once, append one receipt, and prune beyond 64.
4. If onboarding is incomplete and cadence permits, claim the invitation in
   this same experience replacement: increment prompt count, assign the
   timestamp/run baseline, and record the offer on the receipt.
5. Return the claim action only to the successful caller. Never initialize or
   change the profile just to show an invitation.

If a receipt was evicted, its old expected experience token cannot match:
return conflict, not a fresh run. A caller must never refresh tokens and reuse
an old request ID. `finish` on an evicted ID returns `request_expired`.
This bounded guarantee is adequate for conversational requests; it is not an
unbounded event history.

`finish_profile_request` requires a retained receipt, checks both current
tokens, and marks the request finished once. A second finish is an actionless
replay. It does not increment run count. For completed allowed output, it
claims one eligible proposal in the same write as the finish receipt and
returns the exact proposal/profile version reviewed under the lock.
For replay, check profile freshness first, then return no action for the known
finished receipt without requiring its old experience revision to remain
current. This is a read-only replay exception, not refreshed mutation consent.

Claims are **at-most-once issuance**, not proof of visible delivery. The service
cannot atomically commit a file and display chat text. A process crash after
claiming may lose an invitation, but must not cause unlimited repeats. A known
claim response is rendered once by its request owner; retries return no action.
Explicit `/profile` remains the recovery path for a missed invitation.

### 7.3 Composite onboarding completion

`complete_onboarding` provides the atomic profile mutation that the current
service does not expose.

Rules:

- Accept expected version `none:0` when no profile exists.
- Accept a nonempty or empty update mapping. Empty is valid when all questions
  were skipped.
- Require `confirmed: true`, including from the CLI. This is a consent
  parameter, not proof of conversational authorization.
- Validate all supplied values before locking.
- Under the lock, compare the exact reviewed profile token. Use current healthy
  experience state for bookkeeping without treating unrelated count changes
  as a preference conflict.
- If the profile is missing and expected version is `none:0`, create a default
  profile with a new generation and revision `1`.
- Apply only supplied updates as `source: explicit`.
- Omitted preferences keep their current value, source, and timestamp. Only a
  newly initialized profile supplies defaults for omitted fields.
- Set onboarding status to `completed` with the same mutation timestamp when
  it changes. Preserve the timestamp when it is already completed.
- Remove proposals for explicitly updated fields.
- Increment an existing profile revision exactly once for a semantic change.
  A repeated save of already-explicit values on an already-completed profile,
  with no same-field proposals to clear, is a no-op after version validation.
- Persist one complete profile document.
- Completed status alone prevents further automatic onboarding. Preserve
  invitation receipts rather than rewriting them just to zero the counts.
- For missing profile creation with healthy unbound experience state, use the
  `bind` intent protocol. Otherwise this is a single profile write.
- Return the complete committed profile, fresh effective values, and current
  experience token or an explicit cadence-unavailable warning.

This operation is all-or-nothing within the profile document. It must never
perform six independent `set` calls followed by an onboarding call.

The `/profile` editor and confirmed natural-language persistent saves use this
same function via `profile-save`, not legacy `set`. Saving deliberately marks
onboarding completed even if the maker chose only one field; unanswered fields
remain unchanged. Retaking the quiz uses the same preservation rule.
Legacy `set` remains an existing-profile-only API and does not change
onboarding status.

### 7.4 Deferral

`defer_onboarding`:

- Accepts `none:0` for missing profile state.
- Creates a complete default profile at revision `1` when missing.
- Sets onboarding status to `deferred`.
- Preserves all existing preference values, sources, timestamps, and proposals.
  Defaults are used only when creating a missing profile.
- Requires the current request's invitation receipt. Does not increment or
  reset its already-recorded prompt count/run baseline.
  An evicted receipt returns `request_expired`; do not create a new invitation
  to satisfy the precondition. The task still continues without saving a
  deferral, with the persisted old claim limiting future invitations.
- Does not turn a completed profile back into deferred; a stale approval
  conflicts first. With a current token, returns `onboarding_not_required`.
  Repeated deferral of an already-deferred state is a no-op.
- Returns the current effective profile so the task can continue; it is not
  necessarily all defaults.
- Explicit skip/cancel may defer immediately. An abandoned chat cannot execute
  a command on close; its earlier experience claim is sufficient to enforce
  the same count-based re-offer behavior without mutating profile status.

### 7.5 Deferred re-offer cadence

After the first invitation claim, whether answered, skipped, or abandoned:

- Count only eligible top-level skill requests.
- Do not count `/profile`, setup admission, exact terminal errors, recovery,
  profile-management operations, or nested skill calls.
- The triggering request is not one of the three later requests. Confirmation
  answers, returning from onboarding, aliases, and nested skills are not runs.
- When `eligibleRunCount - lastPromptRun >= 3`, atomically claim one re-offer by:
  - incrementing `promptCount` from `1` to `2`;
  - assigning the current count to `lastPromptRun`;
  - returning `onboardingOffer: deferred_reoffer`.
- Never automatically offer onboarding more than twice.
- The second invitation offers `Tune now` and `Not again`.
- `Not again` sets `suppressed: true`.
- A maker can always run `/profile` or ask to change their style regardless of
  suppression.
- `proactiveSuggestions: off` does not suppress this onboarding re-offer.
  Completed onboarding is never re-offered.
- Counts persist across sessions in the same checkout. Time away does not
  increment or reset them. Stored timestamps do not establish a cooldown.

### 7.6 Proposal presentation cadence

This phase does not create observations. It reacts only to a pending proposal
already returned by `resolve`.

- Present at most one proposal after a top-level task completes, never before
  or during task execution. A failed, cancelled, or blocked task does not
  trigger an automatic proposal.
- When the request's effective `proactiveSuggestions` is `off`, do not
  automatically present a proposal. This does not reject, accept, or remove it.
- A proposal counts toward the one optional-suggestion budget for the entire
  response. Do not add it if the completed response already includes an
  optional suggestion.
- Do not append a proposal to exact terminal output or any output contract
  that prohibits additional text.
- Use canonical preference order when more than one proposal is pending.
- A proposal with no matching prompt state is eligible for presentation.
- Claiming a proposal increments its prompt count and records the current
  global run count and timestamp before rendering. An unanswered/dismissed
  proposal follows the same later cadence as `Ask me later`.
- `Ask me later` leaves the proposal pending and acknowledges the existing
  claim; it does not increment prompt count or restart the run baseline.
- Re-present after three later eligible top-level runs, calculated from the
  later of the non-null `lastPromptRun` and `snoozedAtRun` baselines.
  For a never-claimed, never-snoozed proposal there is no waiting period.
  This is count-based eligibility, not an instruction to display it during
  the third run. Wait for an allowed post-completion opportunity.
- Present the same proposal at most twice automatically.
- After the second `Ask me later`, set its prompt state `suppressed: true`.
- `/profile` still shows suppressed pending proposals.
- `/profile` also shows pending proposals when optional tips are off, because
  the maker is explicitly requesting profile management.
- When automatic presentation is disallowed, do not consume a presentation
  attempt or record a new snooze.
- Accept uses the exact profile version and proposal snapshot reviewed.
- Reject uses the exact profile version and retains terminal rejection metadata.
- A stale version returns `profile_conflict`; do not refresh and silently apply.
- Canonical ordering is applied to the eligible subset, skipping suppressed,
  terminal, or not-yet-due records so one snoozed field cannot starve others.
- Explicit `/profile` review does not increment automatic prompt counts. An
  explicit snooze can set a fresh baseline without consuming an automatic
  presentation attempt; repeated identical snooze is a no-op. Its explicit
  review version must still match.

### 7.7 CLI additions

Extend the JSON-only CLI:

```text
python scripts\user_profile.py experience resolve
python scripts\user_profile.py experience begin --request-id <uuid> --expected-version <profile-token> --expected-experience-version <experience-token>
python scripts\user_profile.py experience finish --request-id <uuid> --expected-version <profile-token> --expected-experience-version <experience-token> --outcome completed --allows-extra-content
python scripts\user_profile.py onboarding-complete --values-stdin --expected-version <profile-token> --yes
python scripts\user_profile.py profile-save --values-stdin --expected-version <profile-token> --yes
python scripts\user_profile.py onboarding-defer --request-id <uuid> --expected-version <profile-token>
python scripts\user_profile.py onboarding-suppress --expected-version <profile-token> --expected-experience-version <experience-token> --yes
python scripts\user_profile.py proposal-snooze --field <field> --proposal-created-at <timestamp> --expected-version <profile-token> --expected-experience-version <experience-token> --origin automatic
python scripts\user_profile.py experience reconcile --expected-experience-version <experience-token>
python scripts\user_profile.py experience reset --expected-version <profile-token> --expected-experience-version <experience-token> --yes
python scripts\user_profile.py experience recover --expected-content-hash <experience-hash> --expected-version <profile-token> --yes
python scripts\user_profile.py preview --values-stdin
```

`onboarding-complete --values-stdin` accepts a JSON object containing only
answered fields. It may be `{}`. `profile-save` has identical atomic save
semantics but requires a nonempty map. Both support mutually exclusive
`--values-json` and `--values-stdin`.

`preview` accepts a complete six-value draft with the same field shapes as
`set`, returns presentation metadata, and never accesses disk. The caller
combines answered values with the resolved defaults/current values first.

`finish` defaults `allowsExtraContent` to false and accepts
`--optional-suggestion-used`; both flags can only restrict the service's
decision. A stored `proactiveSuggestions: off` cannot be bypassed by a flag.
`proposal-snooze --origin` is `automatic` or `explicit`; automatic requires a
matching prior claim. Explicit review may establish a zero-count record with
its own `snoozedAtRun` baseline as described below.

For explicit snooze without a prior automatic claim, store the current run
count in `snoozedAtRun`, including zero. Eligibility uses the larger non-null
baseline of `lastPromptRun` and `snoozedAtRun`. Every automatic claim clears
`snoozedAtRun`. This separates explicit postponement from presentation history.

`experience recover` also accepts `--expected-profile-content-hash` instead
of `--expected-version` when the profile is invalid/unsupported. Reject both
together and compare the raw profile hash under lock. Prefer repairing profile
first, except when an unmatched pending intent requires experience repair
first. Never automatically recover both files.

### 7.8 Results, errors, and no-op semantics

All commands retain the JSON-only parser/error behavior of the original CLI.
Operations use stable names such as `experience.resolve` and
`experience.begin`. State responses expose opaque tokens, never bare revisions.

| Result | Required fields beyond `status`, `operation` |
|---|---|
| Combined resolution | `schemaVersion: 1`, `profileExists`, profile `version`, `effectiveProfile`, validated stored `profile` (null if missing), `onboardingStatus`, `pendingProposals`, `experienceStateExists`, `experienceVersion`, `cadenceAvailable`, `warnings` |
| Experience mutation | Shared state/token fields, `changed`, `committed`, `experienceCommitted`, `replayed`, `onboardingOffer`, `proposalField`, `warnings`; no profile fallback |
| Composite/profile save | Shared fields, `changed`, `committed`, `profileChanged`, `experienceCommitted`, complete resulting `profile`, `effectiveProfile`, `warnings` |
| Claimed proposal | Experience mutation fields plus the exact pending `proposal` record and `reviewedVersion` |
| Preview | `personaId`, `personaName`, ordered six-setting `labels`, `summary`, `example`, `exampleLabel: "Example response - no action performed"`; no disk identity |

The stored profile in combined resolution lets the editor display provenance
without a second read. It remains local service output, never telemetry.
Every state-based result also includes `experienceSchemaVersion: 1`;
`experienceStateExists` indicates physical presence even when its contents are
damaged. In warnings-only resolution, `experienceVersion` is null when the
existing bytes could not yield a trusted token, not the missing-state `none:0`.
Experience mutations return the current profile token and do not invent a
profile snapshot. Composite results include `profileExists: true`.
On actionless responses, `onboardingOffer` is `none` and `proposalField` null.

Define `ExperienceMutationResult` and `CompositeMutationResult` dataclasses
from this table. `committed` means any requested persistent change committed;
`profileChanged` and `experienceCommitted` identify which document changed.
For a no-op all change/commit flags are false. An experience reset can be a
real change even if the corresponding profile reset is a no-op. A staged
intent alone is not the requested profile change; report
`reconciliationRequired: true` on failure after staging but before commit.
Existing commands retain their original envelopes except additive warnings
and the mandatory committed-error fields.

Warnings are bounded objects `{ "status", "error", "path", "contentHash" }`;
omit `contentHash` when bytes were unavailable. Never include raw exceptions,
rejected field values, messages, or document contents. An experience warning
may accompany `status: ok` only when valid profile resolution or an authorized
profile save actually succeeded. It is not an experience success.

| Exit | Additional status | Meaning |
|---|---|---|
| 0 | `ok` | Success, possibly with explicit cadence-unavailable warning |
| 2 | `invalid_arguments`, `confirmation_required` | Wrong/missing inputs or required consent |
| 3 | `invalid_experience_state`, `unsupported_experience_schema`, `request_expired`, `experience_reconciliation_required`, `onboarding_not_required` | State cannot safely support the requested experience operation, or onboarding is already completed |
| 4 | `experience_conflict`, existing `profile_conflict`, `lock_timeout` | Stale token or unavailable lock; no automatic retry with refreshed consent |
| 5 | existing `read_failed`, `persistence_failed` | Sanitized I/O failure, with commit fields where applicable |

`experience_conflict` includes `expectedExperienceVersion` and
`actualExperienceVersion`. Hash conflicts include expected/actual content
hashes with an explicit `resource: "experience"` discriminator. Invalid raw
experience reads include the hash of those exact bytes. All errors include
`committed`; handled post-profile-commit failures additionally include profile
`version`, `profileChanged`, `experienceCommitted`, and
`reconciliationRequired`. Do not issue a second write to retry a successful
profile save.

### 7.9 Operation/state matrix

Apply argument and confirmation validation before disk mutation. For every
consent-based operation, compare the relevant observed version/hash before
checking transition/no-op conditions.

| Operation | Missing profile | Valid profile | Invalid/unsupported profile | Invalid/unsupported experience |
|---|---|---|---|---|
| `experience resolve` | Complete defaults plus valid unbound cadence | Combined snapshot | Original profile error; caller may explicitly call `defaults` | Valid profile/default snapshot plus warning; cadence disabled |
| `experience begin` | Claim/count in unbound experience only | Claim/count without changing preferences | Original profile error | Experience error; continue domain task without automatic prompts |
| `experience finish` | Allowed with retained unbound receipt; no proposals | Claim only when all rules allow | Original profile error | Experience error; completed domain task remains completed |
| `onboarding-complete`, `profile-save` | Create atomically from `none:0` | Update supplied values and complete onboarding | Original profile error; preserve bytes | Save profile independently with explicit warning |
| `onboarding-defer` | Create deferred defaults with a retained claim | Preserve values; defer incomplete onboarding; completed returns `onboarding_not_required` | Original profile error | Do not fabricate a claim; report warning/error and continue with existing context |
| `onboarding-suppress` | Valid with unbound history | Set suppression only | Original profile error | Requires explicit experience repair |
| `proposal-snooze` | `profile_not_found` | Pending matching proposal required | Original profile error | Requires explicit experience repair |
| Normal profile reset | `profile_not_found` | Reset via transition protocol | Original profile error | Profile reset may proceed with warning; reminder state stays disabled |
| Profile recovery | `profile_not_found` | `recovery_not_required` | Hash-matched, confirmed backup/reset | Preserve experience damage and warn |
| `experience reset` | Reset healthy unbound history | Reset healthy history only | Profile error | Reject; use experience recovery |
| `experience recover` | Valid with observed `none:0` | Valid with observed profile version | Require exact profile content hash; no profile write | Hash-matched confirmed backup/replacement |
| `experience reconcile` | Compare intent with missing-state marker | Compare exact profile bytes/token | Compare exact hash for recovery intent | Reject; requires experience repair |
| `preview` | Ignore disk | Ignore disk | Ignore disk | Ignore disk |

Missing experience state is normal for reads. First counting/claiming writes
create it. Healthy experience reset of missing state is a no-op.
Reconcile with no pending change is a token-checked no-op.
Experience recovery of valid state returns `recovery_not_required`, except
when an unmatched pending intent explicitly requires repair. Repeated
suppression/snooze of the same state is a no-op; automatic claim counts never
increase on replay. Direct save never implicitly repairs a damaged profile.

## 8. Shared request-entry contract

Add `src/skills/shared/user-profile-entry.md`.

The contract defines:

1. Route and apply branch-specific gates before optional profile work.
2. Obtain one combined snapshot and claim/count through the entry owner.
3. Persist only reminder metadata before explicit profile save.
4. Retain the original request and target choices while collecting answers.
5. Return to the same request without counting it again.
6. Freeze one execution profile and pass it to every child.
7. Claim proposals only after allowed successful completion.

### 8.0 Request context and ownership

Pass the following logical context between prompts, entry skills, and nested
skills. It is conversation context, not additional persisted profile data:

| Field | Meaning |
|---|---|
| `requestId` | One random UUID per independent user task |
| `entryMode` | `eligible`, `resolve_only`, `excluded`, or `management` |
| `entryOwner` | Prompt/skill that owns entry and completion handling |
| `entryHandled`, `runCounted` | Prevent nested/alias/continuation re-entry |
| `phase` | `admission`, `onboarding`, `executing`, or `completed` |
| `executionProfile` | Frozen successful resolution or explicitly marked temporary defaults |
| `profileVersion`, `experienceVersion` | Control tokens returned by the service |
| `automaticPromptsAvailable` | False on cadence error or stale-token conflict |
| `originalRequest`, `selectedTargets` | Conversation-only continuation context |
| `draftValues`, `answeredFields` | Conversation-only quiz/editor state |

A prompt that routes into a skill remains the entry owner. A directly invoked
skill without context becomes the owner, applies its own gates, and follows
the same contract. Central instructions are a routing policy, not another
owner. Delegated evaluators and nested helpers always inherit context.

Replies to questions, safety confirmations, and `Back` are continuation turns,
not new user tasks. A distinct user request gets a new UUID. If conversation
context is lost, do not guess which previous request should resume or replay a
mutation; treat a new user task as new and leave old unfinished receipts alone.

Use only the entry owner's approved commands. `begin`/`finish` conflicts
disable automatic prompts for that request rather than forcing a new version
and retrying. The task can still use its original profile snapshot.
Surface cadence errors once in an allowed flexible section or profile editor,
never by changing an exact terminal response.

### 8.1 Eligibility order

For eligible branches, profile experience runs after:

- The branch's foundation setup admission, including existing exceptions.
- Explicit capability gates.
- Permission and role gates that must stop the request.
- Required target or environment resolution needed to know whether the request
  can proceed.

It runs before:

- Flexible explanatory output.
- Optional discovery questions.
- Local authoring work.

It does not interrupt:

- `/setup`.
- `/profile`.
- Profile recovery or reset.
- Exact terminal unsupported-capability messages.
- Safety-critical confirmation already awaiting an answer.
- Argument errors or malformed commands.
- Nested skills with supplied profile context.

`/profile` and unambiguous requests to manage maker communication style are a
new explicit exception to the central setup-required stop. They do not require
authentication, an agent, or an environment. Keep the existing mandatory setup
state read, but route these requests before its stop message. Add the exception
to both the gate and routing table; adding a prompt alone is insufficient.

Evaluation creation/update and other currently permitted pre-setup branches
retain their own admission rules. Profile work must not introduce a new setup
requirement. Setup itself remains excluded, including style indicators.

For a mixed request such as "use short answers and deploy this," permit the
profile-management part but apply all existing setup/permission/confirmation
gates independently to deployment. Profile consent never authorizes the task.

Branches with only exact messages use `resolve_only` or `excluded` as specified
in section 15. Do not weaken their no-extra-text rule to insert an invitation.
For no-script skills adopted as eligible, explicitly allow only the profile
service calls required by this contract; preserve their ban on other scripts.

### 8.2 Original-request continuation

The onboarding skill receives the original user request as immutable context.
It must not rewrite or reinterpret that request while asking profile questions.

After save, explicit defer, or cancel:

- Return to the original owner with `entryHandled: true` and the same request
  UUID; route to the selected skill without a second count/claim.
- Re-run only routing and non-mutating admission checks as needed.
- If profile state was saved before domain work, obtain the execution snapshot
  once from the new committed state. If nothing was saved, keep the entry
  snapshot. A concurrently changed profile may cause review conflicts, never
  approval reuse.
- Do not ask the user to repeat the request.
- Do not reuse stale approval for a mutation that occurred before onboarding.

A profile change requested during domain execution is a separate management
action. It does not replace the executing task's profile or rerun completed
domain work. A one-off rephrasing request may change flexible wording without
re-executing tools or persisting an override.

If the chat is abandoned, discard draft values and continuation context when
the host no longer retains them. Do not claim to resume a lost original task
in a different session. Only reminder history persists.

## 9. First-use invitation

### 9.1 Trigger

Offer the initial invitation when:

- The request is eligible.
- `resolve` returns `profileExists: false`, or an existing valid profile has
  onboarding `not_started`.
- Experience state is valid, unsuppressed, and has `promptCount: 0`.
- `experience begin` successfully returns `onboardingOffer: initial`.

Profile `not_started` alone is not permission to repeat an invitation. A
previous claim with no save follows the same later-request cadence as a skip.

### 9.2 Chat presentation

Use concise chat content rather than imitating a graphical card.

Required content:

- Welcome and value statement.
- Five questions, approximately 60 seconds.
- Replies will adapt across all ESS Maker Kit skills in this checkout.
- The user can change the profile later with `/profile` or natural language.
- Local-only privacy statement:
  - preferences are saved in `.local/user-profile.json` only after approval;
  - local reminder history records that the invitation was offered, without
    saving quiz answers;
  - no name, email, UPN, employee ID, or transcript;
  - not sent to Copilot Studio.
- The original skill runs either way.

Offer two choices:

1. `Tune my style`
2. `Skip and continue` (label `Skip and use defaults` only when all active
   preferences are defaults)

Use the runtime's structured question tool when available. Otherwise render a
numbered choice and wait for the answer.

### 9.3 Skip behavior

On skip:

- Call `defer_onboarding`.
- Continue with the existing effective preferences, using defaults only where
  no saved values exist.
- State once that the request will continue and the quiz can be opened later.
- Do not append optional profile advice after an exact terminal skill response.

## 10. Five-question onboarding flow

The quiz is conversational state only. Do not persist partial drafts, selected
labels, free-text answers, or persona names.

Each question supports:

- One structured choice.
- `Back`.
- `Skip this question`.
- Free-text input mapped to a typed candidate and confirmed.

The draft begins with resolved current preferences. Missing profiles use
module defaults. Existing `not_started`/`deferred` profiles may contain explicit
or learned preferences; never replace them merely because onboarding is
incomplete.

Maintain `answeredFields` independently of displayed values. `Back` restores
the previous draft answer for editing. Skipping a previously answered question
removes that answer from the draft and restores its entry value/source. A
skip never calls a persistence method.

### 10.1 Question 1 - response format

Prompt intent:

> It is Monday at 9 AM. You open an ESS skill you have never used. What would
> you want to see first?

| Choice label | Description | Stored value |
|---|---|---|
| A cheat-sheet I can scan | Comparable information side by side | `table_first` |
| A recipe I can follow | First, second, third | `steps` |
| The highlights | A few crisp points | `bullets` |
| A short story | Plain-language paragraphs | `prose` |
| Surprise me | Use the clearest format for the task | `auto` |

Show a short preview after selection when practical.

### 10.2 Question 2 - detail and maximum length

Prompt intent:

> It is 4 PM on release day. How full is your mental cup?

| Choice | Detail value | Suggested maximum (not yet selected) |
|---|---|---|
| Espresso | `concise` | `150` words |
| Flat white | `balanced` | `400` words |
| Pour-over | `detailed` | `800` words |

Then ask:

> When does a reply start to feel like too much?

Choices:

- One screen - `150`
- A scroll or two - `400`
- A few scrolls - `800`
- I read it all - `null`

Detail and length are independent answers in one question group. Present the
suggested maximum as a choice, never silently select it.

- Selecting a cup answers only `detailLevel`.
- Explicitly accepting the suggested limit, selecting another preset, or
  selecting `No limit` answers `maximumResponseLength`.
- Skipping the length follow-up preserves the entry length and source, even
  after answering detail.
- A maker may skip detail and answer length.
- Skipping the whole group preserves both entry values/sources.
- On a new profile, preserved entry values are module defaults. On a retake
  or partial profile, they may already be explicit or learned.
- Editor/custom numeric input accepts integers from 50 through 5000 or
  explicit `No limit` mapped to JSON null. Do not clamp an invalid value or
  conflate `"null"` with null.

Explain that maximum length is a soft budget. Required outcomes, blockers,
actions, exact outputs, and remediation may exceed it.

### 10.3 Question 3 - tone

Prompt intent:

> Who would you want sitting next to you while you build an agent?

Every choice shows the same factual sample message in a different voice.

| Choice | Stored value |
|---|---|
| The senior engineer | `direct` |
| The teammate | `friendly_professional` |
| The auditor | `formal` |
| The mentor | `empathetic` |

State that tone changes phrasing, never facts or required copy.

### 10.4 Question 4 - confirmation frequency

Prompt intent:

> You handed a task to a new teammate. When should they check back?

| Choice | Stored value |
|---|---|
| Only if truly stuck | `minimal` |
| When something is genuinely unclear | `standard` |
| Before every significant scope or behavior choice | `frequent` |

Before accepting the answer, state that destructive actions, remote mutations,
environment or agent selection, role attestations, and skill-required
confirmations always remain.

### 10.5 Question 5 - proactive suggestions

Prompt intent:

> You finished a task. What do you hope a colleague says next?

| Choice | Stored value |
|---|---|
| Stay in the zone | `off` |
| One useful tweak within this task | `contextual` |
| One useful adjacent next step | `on` |

State that required fixes and blockers are not optional suggestions and always
remain. Every mode permits at most one optional suggestion.

### 10.6 Free-text mapping

For free text:

1. Treat the text as untrusted conversational input.
2. Map it in memory to the nearest documented typed option.
3. Do not pass raw text to `user_profile.py`.
4. Show:
   - the interpreted plain-language choice;
   - the typed effect in maker-facing terms, not enum syntax;
   - any coupled effect, such as detail plus maximum length.
5. Ask the maker to confirm or choose another option.
6. Only a confirmed mapping enters the draft.
7. If mapping confidence is low or multiple choices fit, show the structured
   choices instead of guessing.

## 11. Review, persona, and save

### 11.1 Review card in chat

After question 5, render:

- A derived persona name.
- A one-sentence plain-language summary.
- Six rows showing:
  - maker-facing setting name;
  - maker-facing selected value;
  - source question, `Default - skipped`, or `Unchanged - saved setting`;
  - `Edit` instruction.
- A short, labeled example response derived from the draft, never a claim that
  a real task ran.

Offer:

1. `Save my style`
2. `Edit settings`
3. `Retake quiz`
4. `Cancel and continue without saving`

No quiz preference write occurs before `Save my style`. Reminder claims may
already have been persisted. Cancelling discards draft answers; when entered
from an invitation it may call deferral with the retained claim, preserving
existing preferences. Explicit `/profile` cancellation writes nothing.

### 11.2 Persona derivation

Personas are a display function of effective preference values. They are not
stored and never affect behavior.

Implement this mapping once in `describe_profile` inside `user_profile.py`;
skills consume `preview` results instead of independently assigning labels.

Use the first matching rule:

| Priority | Rule | Persona |
|---|---|---|
| 1 | Tone is empathetic or confirmations are frequent | Supportive Learner |
| 2 | Detail is detailed or format is table-first | Curious Architect |
| 3 | Detail is concise and confirmations are minimal | Focused Navigator |
| 4 | Format is steps or tone is formal | Methodical Planner |
| 5 | Tone is friendly-professional or format is bullets/prose | Collaborative Builder |
| 6 | Fallback | Adaptive Explorer |

Keep the persona label playful but avoid psychological, medical, demographic,
or employment inferences. The summary must be assembled only from the six
settings.

The same helper returns deterministic labels and a short summary assembled
from those settings. Its preview uses one fixed fictional local-workflow
scenario with constant facts (files saved locally, review required, no live
deployment). Format/detail/tone affect only presentation; required warning
content is identical in every variant. This example is not a general response
renderer and makes no network/domain calls.

Always show `Example response - no action performed`. Do not incorporate the
maker's agent name, real task outcome, raw request, or generated artifacts.
Return presentation data only; neither the label nor example is persisted or
emitted in telemetry.

### 11.3 Save semantics

On `Save my style`:

- Send only answered fields to `onboarding-complete`.
- Omitted/skipped fields preserve entry values/sources. They stay
  default-sourced when there were no prior saved choices.
- Save all answered fields and onboarding completion in one profile revision.
- If every question was skipped, complete onboarding with `{}` and preserve all
  current sources. A wholly new profile therefore retains all defaults.
- On conflict, re-resolve and show that profile state changed. Require review
  again; do not silently overwrite.
- After success, state that changes apply to the next request.
- Resume the original request with a newly resolved immutable profile.

## 12. `/profile` and editing

### 12.1 Entry prompt

Add `.github/prompts/profile.prompt.md` and route it to
`src/skills/user-profile/SKILL.md`.

Recognize:

- `/profile`
- "show my style"
- "change my response style"
- "reset my preferences"
- "retake the style quiz"
- persistent natural-language changes such as "shorter from now on"

Do not confuse this maker communication profile with runtime employee profile
or Workday user-profile scenarios.

### 12.2 Chat editor

Because this phase is chat-only, render a plain-language table and edit through
structured questions.

Labels:

| Stored field | Maker-facing label |
|---|---|
| `responseFormat` | How replies are shaped |
| `detailLevel` | How much detail |
| `maximumResponseLength` | Preferred maximum length |
| `toneOfVoice` | Voice |
| `confirmationFrequency` | Check-ins |
| `proactiveSuggestions` | Optional tips |

Never present enum identifiers as the primary UI labels.

The editor offers:

- Edit one setting.
- Edit several settings.
- Retake the quiz.
- Review pending suggestions.
- Reset to defaults.
- Repair profile state when an error was observed.
- Exit without changes.

Use `profile-save` for confirmed edits. One multi-field save is atomic,
creates a missing profile using the reviewed `none:0` token, and marks
onboarding completed. Do not `initialize` speculatively when opening the
editor, and do not chain `initialize`, `set`, and `onboarding` as separate
commits. Saving an explicit value equal to today's default still pins it.

Opening `/profile` without a profile shows defaults labeled `Not saved`.
Reading, previewing, and cancelling do not create profile or experience files.
`Save` of a nonempty selection completes onboarding; `Use defaults and finish`
requires review/confirmation and calls `onboarding-complete` with `{}`.

### 12.3 Retake semantics

Retake begins from the current stored profile, not module defaults.

- An answered question replaces the matching active values as explicit.
- A skipped retake question preserves its current value and source.
- The review card shows changed and unchanged values.
- Saving uses the exact version resolved before the retake.

### 12.4 Natural-language persistent changes

Classify explicit duration:

- Current-request phrases such as "for this answer", "explain this in detail",
  or "make that shorter" apply only to the current response and do not write.
- Persistent phrases such as "from now on", "always", "for every skill", or
  "make this my default" enter profile-change confirmation.
- Ambiguous phrases ask whether the change is for this reply or all future
  skills.

For a persistent request:

1. Map text to typed candidate updates in memory.
2. Show the before/after values in plain language.
3. Offer `Save for all skills`, `Just this reply`, and `Cancel`.
4. Save only after explicit confirmation.
5. Use the exact observed version.
6. On success, state that the next request uses the new profile.

Raw natural-language text is never stored.
Use `profile-save` for persisted changes. `Just this reply` changes flexible
wording only, preserving necessary evidence and output contracts; it never
reruns domain mutations. If no response is pending to rephrase, apply it only
to the current management reply, not to a future task.

### 12.5 Reset

Reset requires a separate confirmation and shows:

- All six settings return to module defaults.
- Sources return to default.
- Pending and terminal proposal metadata is cleared.
- Onboarding returns to `not_started`.
- The old derived persona disappears; a later view derives a new label from
  the current defaults rather than restoring or deleting a stored persona.
- Experience cadence is reset.

Use normal profile reset, not recovery reset. Preserve profile generation;
rotate experience generation using the crash-safe reset protocol.

## 13. Chat-only style indicator

The prototype's persistent clickable pill is not available in this scope.

For completed profiles, top-level skill responses with flexible content may
include one compact line:

```text
**Style:** Steps · Concise · Direct · about 150 words
```

Rules:

- Show at most once per top-level response.
- Omit default-valued dimensions when needed for brevity, but never imply a
  value that is not active.
- Do not show on exact terminal messages, machine-readable-only output,
  safety-critical-only responses, parser errors, or reset/recovery output.
- Do not count the style line as the optional proactive suggestion.
- The line is informational, not clickable.
- `/profile` is the documented editing path.
- Nested skills do not add a second indicator.

## 14. Pending learned-preference proposals

### 14.1 Presentation

For automatic presentation, wait until the requested task has completed and
apply section 7.6, including optional tips, response-wide suggestion budget,
and output-contract restrictions. Turning optional tips off does not remove
pending proposals from the explicitly opened `/profile` editor.

When one pending proposal is eligible for presentation, show:

- A generic statement that a saved preference suggestion is available.
- Observation count.
- Current setting in maker-facing language.
- Proposed setting in maker-facing language.
- Privacy statement: the proposed typed value, count, confidence, and decision
  timestamps are local; raw messages are not stored.

Do not infer "this week", "on evaluation results", or the maker's reasons from
count/confidence. The stored proposal contains no time-window or skill-specific
observation evidence. Do not fabricate those claims from the prototype.

Do not expose numeric confidence unless product copy needs it for debugging.
Confidence remains a service validation field, not a persuasion score.

Offer:

1. `Make this my default`
2. `Keep my current setting`
3. `Ask me later`

### 14.2 Decisions

- `Make this my default` calls `accept` using the reviewed version.
- `Keep my current setting` calls `reject`.
- `Ask me later` calls `proposal-snooze` and does not change the profile.
- Acceptance may replace an explicit value because the maker just authorized
  it.
- Rejection does not remove terminal proposal metadata.
- Do not automatically re-propose rejected values in this phase.

### 14.3 No observation engine

Do not:

- Count natural-language overrides automatically.
- Infer confidence.
- Call `propose` based on chat history.
- Store raw evidence.

Tests may create pending proposals directly to exercise the experience.

## 15. Skill adoption

### 15.1 Central instruction

Add a user-profile request-entry section to
`solutions/ess-maker-skills/.github/copilot-instructions.md` in its routing
policy, plus the explicit profile-management setup exception in section 8.1.
Central instructions must delegate to the selected branch's admission gates
before executing profile entry. Do not run a global invitation before a
prompt has decided whether its branch is supported.

It must point to `src/skills/shared/user-profile-entry.md` rather than duplicate
the complete flow.

### 15.2 Entry prompts

Paths in this table are relative to
`solutions/ess-maker-skills/.github/prompts/`. This is the exhaustive manifest
for the current catalog, not a list inferred from filenames at runtime.

Modes:

- **E / eligible:** branch admission, combined resolution, one count/claim,
  execution context, and allowed post-completion handling.
- **R / resolve-only:** reuse supplied context; directly invoked, resolve
  preferences only. No counts, invitations, style indicator, or proposals.
  Preserve fixed output and use preferences only if an existing section
  explicitly permits flexible prose.
- **X / excluded:** no profile entry; unchanged terminal/setup/retired flow.
- **M / management:** `/profile` flow; no eligible-run counts or auto-prompting.

| Exact file | Mode and insertion point | Protected behavior |
|---|---|---|
| `analytics.prompt.md` | R after its setup gate | All Message blocks and script output; "ONLY text" restriction |
| `connect.prompt.md` | R after integration availability/materialization gates | Script-executor contract, selection, role/connection consent |
| `connect-workday.prompt.md` | Alias to connect; never a separate owner/count | Same gates as connect; no inferred integration capability |
| `create.prompt.md` | E only after selecting workflow or evaluation and passing that branch's admission | Topic-unavailable stop; workflow setup gate; evaluation pre-setup availability |
| `update.prompt.md` | E for admitted workflow/evaluation branches | Topic-unavailable stop; evaluation review routing; local-only workflow boundary |
| `evaluate.prompt.md` | E at selected action admission | Action/set selection, method admission, deployment/connection consent, delete gates |
| `run.prompt.md` | E after action admission | Separate set-selection turns, run IDs, connection selection, exact results |
| `review.prompt.md` | E separately for evaluation or topic branch | Evaluation pre-setup discovery and topic setup gate; no routing to validation by mistake |
| `scan.prompt.md` | E after setup gate, before cleanup work | Diagnostic evidence, checkpoint/fix authorization, required report |
| `test.prompt.md` | E for admitted deployed-topic testing; X for DA workflow-unavailable branch | Deployed-vs-local distinction; diagnosis/mutation approval |
| `landing-page.prompt.md` | E owned here but after skill setup/MCP availability admission | Preview/read-modify-write and destructive/contrast confirmations |
| `push.prompt.md` | E only in its supported evaluation-push branch | Exact deployment target/diff/consent; general DA push-unavailable stop |
| `flightcheck.prompt.md` | R after canonical FlightCheck entry gate | Exact Message blocks, summary banner, tables, required fix/consent turns |
| `menu.prompt.md` | X for menu display; add one `/profile` row | Keep the command menu; a follow-up concrete task is a new routed request |
| `setup.prompt.md` | X | Foundation setup and recovery messages/choices |
| `delete.prompt.md` | X under its current unconditional DA deletion stop | Do not reach the legacy routing below STOP |
| `troubleshoot.prompt.md` | X under current DA-GA unsupported guidance stop | Preserve exact terminal text |
| `backup-template-configs.prompt.md` | X under central retired-command policy | Do not re-enable legacy paths despite retained prompt text |
| `restore-template-configs.prompt.md` | X under central retired-command policy | Same retired-command boundary |
| `profile.prompt.md` (new) | M; no setup/authentication requirement | Profile-specific confirmation and recovery contracts |

Where prompt and central instruction disagree about legacy capability, preserve
the stricter existing gate. This feature does not resolve unrelated product
availability inconsistencies.

### 15.3 Entry skills

Paths below are relative to `solutions/ess-maker-skills/src/skills/`.
**I / inherit** means reuse supplied context and never own entry/completion;
if legitimately invoked directly, apply its stated fallback mode after gates.
Excluded paths are tracked in tests, not edited to add unused hooks.

| Exact file | Mode | Flexible sections / protected sections |
|---|---|---|
| `analytics/SKILL.md` | R | No new prose; preserve `Start`, all four cases, opt-out/reminder actions and exact messages |
| `connect/SKILL.md` | R | Preserve `Availability`, `Start`, `Routing`, and script-executor messages |
| `connect/workday/SKILL.md` | I; R direct | Preserve `W.1` lifecycle and `W.2` completion; never create an extra onboarding prompt |
| `flightcheck/SKILL.md` | R | Preserve scope/target selection, Step 2 consent, Step 3 summary/table/fix contracts |
| `cleanup/SKILL.md` | E or I from scan | Optional explanations in Steps 4/6 adapt; diagnostic evidence, checkpoint rules, fix consent and mandated report fields remain |
| `landing-page-config/SKILL.md` | E or I | Optional explanations adapt; setup/MCP gates, `Hard rules`, previews, fresh read-modify-write, contrast/clear/reset approvals and error receipts remain |
| `workflows/create/SKILL.md` | E or I | Optional explanation in Steps 3/4 adapts; initial required questions, file schema, approval and local-only boundary remain |
| `workflows/update/SKILL.md` | E or I | Optional change explanation/final summary adapt; `Rules`, checkpoint, validation and prompt-level DA deployment restrictions remain |
| `topics/test/SKILL.md` | E or I | Optional `Report` explanation adapts; fault classification, probe evidence, browser/auth steps and explicit mutation rules remain |
| `topics/review/SKILL.md` | E or I | Optional explanation outside the required report adapts; scope, persisted findings, Step 9 report and subagent return remain |
| `evaluations/dispatcher/SKILL.md` | E or I | Scenario clarification may adapt; `Rules`, set discovery/selection, and Steps 1-3 routing remain |
| `evaluations/create/SKILL.md` | I; E direct | Optional narrative adapts; Step 2 scope/replacement decisions, generated YAML/CSV, Steps 4.3-4.4 scorecard/actions and selected continuation remain |
| `evaluations/generate/SKILL.md` | I; E direct | Optional narrative adapts; scope/name choices, Steps 5-8 artifacts/preview/quality report and Step 9 actions remain |
| `evaluations/update/SKILL.md` | E or I | Optional explanation in `Step 8: Final summary` adapts; Flow R1/R2, selected folders, YAML/CSV edits, scorecard, completion/deployment gates remain |
| `evaluations/review/SKILL.md` | E or I | Optional reviewer explanation adapts; discovery, `List before reviewing`, selected-set identity and continuation remain |
| `evaluations/run/SKILL.md` | E or I | Optional explanation outside exact results adapts; Flow A selection/deployment/connection turns, `userGuidance`, Flow B results order and terminal messages remain |
| `evaluations/validate/SKILL.md` | I; R direct | Exact `Step 3` quality report and `Step 4` triage/gate stay unchanged; no automatic prompt or extra reviewer-return text |
| `evaluations/delete/SKILL.md` | I; E direct only if existing evaluation-specific admission allows | Optional deletion summary adapts; delete ordering, Steps 2/6 approvals, checkpoint, quality report and verification remain; does not enable `/delete` |
| `foundation-setup/SKILL.md` | X | All foundation setup messages, permissions and recovery choices |
| `setup/SKILL.md` | X | Retained setup flow, not an alternative entry |
| `setup/workday-da/SKILL.md` | X | Retained setup flow and permission gates |
| `topics/create/SKILL.md` | X | Direct authoring unavailable |
| `topics/update/SKILL.md` | X | Direct authoring unavailable |
| `topics/create-eval-driven/SKILL.md` | X | Retained legacy authoring does not enable topic creation |
| `topics/update-eval-driven/SKILL.md` | X | Same authoring boundary |
| `topics/delete/SKILL.md` | X | DA component-deletion gate |
| `workflows/delete/SKILL.md` | X | DA component-deletion gate |
| `workflows/test/SKILL.md` | X | DA workflow diagnostics unavailable |
| `troubleshoot/SKILL.md` | X | Current integration-troubleshooting gate |
| `backup-template-configs/SKILL.md` | X | Central retired-command policy |
| `restore-template-configs/SKILL.md` | X | Central retired-command policy |
| `user-profile/SKILL.md` (new) | M | Profile management and explicit confirmation |

Nested non-`SKILL.md` documents must carry context without running entry hooks:

| Exact file | Protected contract |
|---|---|
| `evaluations/experience-contract.md` | Before-generation message, method admission, expected responses, CSV, generated-case preview, post-generation quality scorecard, four maker actions |
| `evaluations/deployment-flow.md` | Admission, helper consent/target/diff tokens, promotion/deployment verification, exact intended continuation |
| `evaluations/quality-fix-flow.md` | Required quality-fix decisions and returned report; no nested count |
| `connect/shared/lifecycle-runner.md` | Lifecycle evidence and required turns; no nested count |

Other step documents inherit from their owning skill; do not mechanically add
an entry block to every markdown file.

The standard adopted section says:

1. Reuse a caller-supplied effective profile.
2. When direct, use the manifest's mode and branch gates before resolving.
3. Read `shared/user-profile-contract.md`.
4. Apply preferences only to flexible maker-facing sections.
5. Carry the same snapshot into nested skills.

Do not onboard legacy or unavailable authoring flows merely because files
exist. Existing capability gates still win.

In `workflows/create/SKILL.md`, narrow the "Do NOT run terminal commands or
scripts" rule only to permit the profile service calls explicitly required by
the shared entry contract. Do not use that exception to run domain scripts,
change telemetry policy, or enable push/test capabilities.

The test-owned JSON manifest stores each exact path, mode, entry anchor, and
protected heading/message anchors from these tables. It is an adoption coverage
fixture, not a second runtime router. Tests fail on missing files, duplicated
owners, removed protected anchors, or newly discovered prompt/skill files
without an explicit adoption/exclusion decision.

### 15.4 Output behavior

Adopt the existing section-level classifications:

- Flexible explanation adapts.
- Contractual blocks remain exact.
- Machine-readable output remains unchanged.
- Safety-critical content remains complete.

Current task instructions override saved style for that request without
persisting.

## 16. Error and edge behavior

| Condition | Experience behavior |
|---|---|
| Missing profile | Use defaults; claim initial invitation only if healthy unbound cadence permits |
| Maker skips initial onboarding | Create deferred default profile and continue |
| Third eligible run after deferral | Offer once more |
| Maker selects `Not again` | Suppress automatic invitations; `/profile` remains available |
| Individual quiz question skipped | Keep that field's entry value and source |
| Quiz abandoned before save | Discard answers, retain invitation claim, allow one final count-based re-offer; do not invent lost continuation context |
| Existing partially customized profile | Preserve saved choices; onboarding status is not permission to reset them |
| Detail answered, length skipped | Save detail only; keep entry length/source |
| Profile conflict at save | Show state changed; re-resolve and require new review |
| Experience-state conflict | Re-resolve cadence; do not duplicate an invitation |
| Experience-state invalid | Continue with valid profile, surface cadence unavailable, do not auto-prompt |
| Profile save succeeds, experience finalization fails | Report committed profile version and reconciliation needed; never blindly repeat save |
| Pending intent matches neither before nor after bytes | Stop experience writers; explicit reminder-history repair required |
| Profile invalid | Surface profile error, use explicit defaults only for unrelated work |
| Pending proposal stale | Return conflict; do not accept a replacement proposal |
| Required confirmation | Always show, regardless of confirmation-frequency preference |
| Exact terminal message | Do not prepend or append onboarding, style indicator, or suggestion |
| Reset requested | Require explicit confirmation |
| Recovery requested | Require observed content hash and explicit confirmation |
| Optional tips off | Suppress automatic preference proposals, not the final onboarding reminder; explicit `/profile` review remains available |
| Returning after an absence | Preserve counts/suppression; elapsed time alone does not cause a prompt |

## 17. Privacy and telemetry

- Keep both files under `.local/`.
- Store no maker name, email, UPN, employee ID, tenant identity, or raw content.
- Do not persist quiz free text or draft selections before save.
- Do not persist persona labels or summaries.
- Invitation claims, opaque request UUIDs, bounded receipts, and transition
  hashes are local control data only. Request UUIDs identify an operation, not
  a maker; never associate them with account identity.
- Do not emit preference values, proposal values, version tokens, generations,
  timestamps, hashes, or backup paths through telemetry.
- Do not emit the original request when onboarding interrupts it.
- New experience telemetry is deliberately deferred (section 21). Keep the
  deterministic service standard-library-only with no telemetry import or
  network dependency. Existing skill telemetry remains unchanged.
- Future approved instrumentation may emit coarse operation outcomes only,
  never preference values or local control tokens. It must be best-effort and
  cannot fail the experience. Record the deferral explicitly in the eventual
  implementation PR; do not claim instrumentation was delivered.

## 18. Testing

### 18.1 Service tests

Extend `test_user_profile.py` and add `test_user_profile_experience.py` for:

- Missing experience state has no write.
- Strict experience-state validation.
- Unknown fields and duplicate keys.
- Profile-generation reconciliation.
- Initial complete onboarding from `none:0`.
- Completed onboarding with all questions skipped.
- Answered fields explicit; skipped fields default.
- Q2 coupled update behavior.
- Existing deferred profile completion increments once.
- Composite save profile atomicity.
- Experience write failure after profile commit reports `committed: true`.
- Deferral creates a complete default profile.
- Third eligible run claims exactly one re-offer.
- Concurrent eligible runs do not create duplicate offers.
- Second invitation suppression.
- Completed onboarding never re-offers.
- Pending proposal canonical ordering.
- Proposal snooze and three-run re-offer.
- Proposal presentation limited to twice.
- Replaced proposal invalidates old snooze metadata.
- Normal reset clears experience state.
- Recovery generation invalidates experience state.
- Lock timeout and stale experience generation/revision tokens.
- CLI envelopes and exit codes.

Use separate processes for concurrency tests.

Additionally cover the reviewed gaps:

- Combined snapshot reads return the profile and its proposals from one byte
  snapshot; no default/profile identity mismatch during concurrent updates.
- Initial invitation claim creates only experience state, with null profile
  association; existing `resolve`/`defaults` still have no write side effects.
- Abandoned invitation is not shown again until three later eligible requests.
- Same request replay cannot count, render, finish, or claim twice.
- Nested and onboarding-continuation turns use the same receipt.
- Evicted receipt operations return conflict/expiry rather than new counts.
- Two simultaneous initial claims produce one initial invitation.
- Two simultaneous completion claims cannot show the same pending proposal.
- A lost claim response is an at-most-once delivery loss, not infinite retry.
- Direct editor save from `none:0` creates one completed profile.
- Existing explicit/learned values survive skip, retake skip, and deferral.
- `profile-save` and onboarding completion no-op rules preserve timestamps.
- Concurrent cadence updates do not invalidate a reviewed preference save.
- Profile reset rotates experience identity, including profile-no-op reset.
- Fault injection before/after every intent, profile replacement, and final
  experience replacement produces the documented commit/error state.
- Reconciliation only clears/applies metadata; it never replays a profile write.
- Unmatched external edits stop reconciliation instead of resetting history.
- Corrupt experience state does not prevent a confirmed profile-only save.
- Reminder repair preserves exact bytes; backup failure preserves active state.
- Same-clock proposal replacement has a distinct identity; metadata-only
  updates preserve identity and do not reset a snooze.
- Independent length/detail answers and numeric boundaries map correctly.
- `preview` accesses no disk or network and is deterministic across invocations.
- Automatic tips off, exhausted optional-suggestion budget, failed tasks, and
  protected terminal output suppress proposals without consuming an attempt.
- Explicit proposal review/snooze works before any automatic prompt, including
  run count zero.

### 18.2 Onboarding contract tests

`test_user_profile_onboarding_contract.py` verifies:

- Five questions cover all six fields.
- Every structured option maps to an allowed value.
- Q2 maximum presets are within service bounds.
- Free text requires confirmation.
- Raw free text is not persisted.
- Individual skips preserve default/current source.
- Save is explicit and composite.
- Persona is derived and non-persisted.
- Persona helper owns the single deterministic rule order; preview uses
  constant example facts and never claims actual execution.
- The original request resumes after save or defer.
- Privacy copy matches local-only behavior.
- Abandoned quiz and cancellation preserve already-saved preferences.
- `/profile` bypasses setup only for profile management.
- Safety guardrails are present in Q4 and Q5.

### 18.3 Adoption tests

`test_user_profile_adoption.py` verifies:

- Central instructions reference the shared entry contract.
- Every supported entry prompt declares profile behavior.
- Every supported entry skill contains the user-profile section.
- Setup and exact terminal commands are excluded.
- Nested skills reuse supplied context.
- No skill instructs callers to read profile JSON directly.
- Machine-readable and exact output exceptions remain documented.
- Style indicators are prohibited on exact terminal output.
- Manifest paths, modes, entry anchors, and protected sections match section 15.
- The workflow-create script exception permits profile calls only.
- Evaluation pre-setup admission still reaches the selected evaluation flow.
- Exact-only modes cannot count or invoke automatic invitation/proposal calls.
- Protected Message blocks, selection menus, scorecards, and code/payload
  examples are unchanged from checked-in pre-adoption baselines.

These are documentation-contract tests, not claims of model compliance.

### 18.4 Scenario tests

Use two explicit validation layers; do not treat keyword tests as proof of
conversational behavior:

- **Automated pytest:** `test_user_profile_experience.py` runs scripted typed
  event sequences against real service functions/CLI in temporary directories.
  Assert exact tokens, changes, prompt counts, and action/no-action decisions.
  Mock only faults/time; concurrency uses real child processes.
- **Documented manual chat acceptance:** exercise the scenarios below in a
  disposable Maker Kit checkout using the actual prompt/skill runtime. Capture
  sanitized pass/fail evidence and unchanged protected outputs. No new model
  runner or live tenant mutation is required for this feature. Stub task
  outcomes with clearly labeled sample results when domain access is absent.
  Record unexercised real-domain behavior as not tested, not as a pass.

For each scenario, record starting profile/cadence, user choices, expected
service calls, expected output classes, final state, and pass/fail. In
multi-persona comparison, exact scorecard/evidence/required remediation must
match; only surrounding flexible prose may differ.

Scenarios:

1. First request -> tune -> save -> original request resumes under the same
   request ID and a refreshed pre-execution profile, without another count.
2. First request -> skip -> defaults -> third later run -> re-offer.
3. All questions skipped -> completed profile with default sources.
4. Free text "just give me tables" -> table-first mapping -> confirmation.
5. "Explain this in detail" -> current reply only.
6. "Use more detail from now on" -> before/after confirmation -> explicit save.
7. Same skill under Focused Navigator, Curious Architect, and Supportive Learner
   retains identical facts and contractual output.
8. Pending proposal -> ask later -> reappears after cadence.
9. Minimal confirmations -> destructive action still asks.
10. Invalid profile -> error surfaced -> unrelated task uses explicit defaults.
11. Optional tips off -> no automatic proposal; `/profile` still lists the
    pending proposal and permits an explicit decision.
12. Optional tips off with deferred onboarding -> one final invitation after
    three eligible requests; `Not again` suppresses it.
13. Return after a long absence -> retained run counts; no time-triggered
    reminder and no reset of suppression.
14. Eligible proposal during a task -> no interruption; show only after
    completion when the output permits it and no other optional suggestion
    has used the response's suggestion budget.
15. Failed, cancelled, blocked, or exact-terminal task -> no automatic proposal
    and no consumed proposal presentation attempt.
16. Close chat midway through quiz -> no answers saved; three later eligible
    requests permit only the one final invitation.
17. Partially customized `not_started` profile -> skip preserves saved values;
    later quiz saves only answered fields.
18. Choose Detailed, skip length -> preserve existing limit or default null.
19. `/profile` before setup -> editor works; a mixed deployment request still
    fails the original deployment admission gate.
20. Reset commits but reminder finalization fails -> reload/reconcile, never
    reapply profile reset or resurrect old suppression.
21. Both files damaged or pending intent unmatched -> explicit hash-matched
    repairs remain possible without a circular dependency or lost backup.

### 18.5 Validation commands and completion evidence

From the repository root, the implementation phase runs:

```text
python -m pytest tests\scripts\test_user_profile.py tests\scripts\test_user_profile_experience.py tests\scripts\test_user_profile_contract.py tests\scripts\test_user_profile_onboarding_contract.py tests\scripts\test_user_profile_adoption.py -q
python -m ruff check solutions\ess-maker-skills\scripts\user_profile.py tests\scripts\test_user_profile.py tests\scripts\test_user_profile_experience.py tests\scripts\test_user_profile_contract.py tests\scripts\test_user_profile_onboarding_contract.py tests\scripts\test_user_profile_adoption.py
```

Also run existing regression tests for changed routing/output contracts,
selected from `tests/scripts/test_evaluation_review_routing.py`,
`tests/scripts/test_evaluation_experience_contract.py`,
`tests/scripts/test_da_command_degradation.py`, and
`tests/setup/test_workday_command_discovery.py`, plus directly affected contract
tests discovered during implementation. Preserve existing test runners and
dependency setup. Distinguish new failures from baseline failures.

Deliver exact command results, manifest coverage, manual scenario results,
and any untested host behavior with the implementation. This specification
update does not claim those implementation checks have already run.

## 19. Implementation sequence

1. Add typed experience-state model, independent tokens, and strict validation.
2. Add combined resolution, locking, pending-change protocol, reconciliation,
   and explicit experience repair. Wire existing writers into the protocol.
3. Add composite onboarding/editor save and preserving deferral operations.
4. Add deduplicated request begin/finish, prompt claims, suppression, and
   proposal snooze operations.
5. Add CLI commands and JSON envelopes.
6. Add service and concurrency tests.
7. Add shared request-entry contract.
8. Add `/profile` prompt and user-profile skill documents.
9. Implement onboarding questions, independent detail/length, abandonment,
   deterministic persona/example helper, and editing contracts.
10. Add pending-proposal experience.
11. Update central instructions.
12. Onboard exactly the manifest's paths/modes and protect their fixed sections.
13. Add adoption and scenario contract tests.
14. Run typed-event tests and manual chat scenarios; verify exact terminal
    outputs, machine-readable artifacts, and existing capability gates remain
    unchanged.

## 20. Acceptance criteria

The experience is complete when:

1. An eligible first request offers onboarding without blocking the skill.
2. Skipping creates a valid deferred default profile and continues the request.
3. The quiz captures all six settings in five questions.
4. Free text is mapped to typed values and confirmed before use.
5. No draft or raw answer is persisted before explicit save.
6. Answered fields are explicit; skipped fields preserve entry values/sources,
   including defaults when the profile is new.
7. Saving preferences and onboarding completion is one profile mutation.
8. The original request resumes automatically after save or defer.
9. Deferred onboarding is offered once more after three eligible runs and can
   be permanently suppressed.
10. `/profile` supports review, edit, retake, reset, and repair entry points.
11. Natural-language current-request overrides do not persist.
12. Persistent natural-language changes require before/after confirmation.
13. Persona labels are deterministic, derived, non-persisted, and behavior-free.
14. Pending proposals change nothing until accepted.
15. `Ask me later` uses bounded local cadence without rejecting the proposal.
16. Every onboarded request resolves one immutable profile and propagates it.
17. Flexible communication adapts while exact, machine-readable, and
    safety-critical output remains intact.
18. Experience-state failures never prevent a valid profile from being used.
19. Profile values, raw messages, and local control tokens are absent from
    telemetry.
20. No custom VS Code extension is required.
21. Automatic proposals appear only after task completion, honor optional tips
    off, and remain available for explicit review through `/profile`.
22. Optional tips off does not suppress the final onboarding re-offer;
    `Not again` does. Reminder cadence depends only on eligible run counts,
    including when the maker returns after an absence.
23. Abandoned quizzes persist no answers but cannot reset invitation counts;
    lost conversation context never causes invented task resumption.
24. Each logical request counts once. Nested calls, aliases, retries, and
    onboarding continuation cannot duplicate counts or claims.
25. Direct editing works before setup and with a missing profile, preserving
    existing selections and marking deliberate saves completed.
26. Detail and maximum length are independently confirmed and saved.
27. Two-file lifecycle changes have deterministic crash reconciliation, rotate
    experience identity on reset, and never replay committed profile mutations.
28. Reminder-state damage cannot silently overwrite history or prevent an
    independently valid profile save; explicit repair preserves a backup.
29. Exact-path adoption coverage and protected-section checks pass; legacy
    capability gates are not widened by personalization.

## 21. Deferred work

- Automatic observation collection and confidence calculation.
- Re-proposal policy after rejection.
- Rich graphical cards, persistent clickable pills, and custom editor UI.
- Cloud or cross-device profile synchronization.
- Shared-checkout operating-system user isolation.
- Administrative profile policy.
- Analytics based on preference values.
- Experience telemetry instrumentation; local service remains network-free.
- Runtime ESS employee personalization.

## 22. Decision closure

All product decisions raised in the pre-implementation review are resolved in
this specification. The implementation must follow the concrete state,
transaction, adoption, and validation contracts above rather than inventing
new persistence or reminder policies. Host-specific limitations discovered
during implementation must be reported explicitly; they are not permission to
weaken consent, exact-output, or no-data-loss requirements.
