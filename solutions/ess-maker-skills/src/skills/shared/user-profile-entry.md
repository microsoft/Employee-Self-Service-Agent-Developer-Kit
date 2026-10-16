# Shared user-profile request entry

This contract governs prompt and skill entry. The entry owner is the prompt
that routes the task, or a skill directly invoked without supplied context.
Participating nested skills inherit context and never become a second owner.

## Modes and gates

- **eligible**: after branch-specific setup, capability, role, target, and
  confirmation gates pass, resolve and claim/count once. Freeze the resulting
  execution profile and handle only permitted post-completion proposals.
- **resolve_only**: resolve preferences for flexible prose only. Do not count,
  invite, show an indicator, or present proposals.
- **excluded**: do not read or mutate profile state or add profile output.
- **management**: use `/profile`; no eligible-run count or automatic prompt.

Use the mode declared by the calling prompt or skill. Profile entry is
workspace-local: resolve all paths and service commands from the Maker Kit
workspace. Do not search repository tests or load parent workspace instructions
to discover a mode. Profile entry never changes workspace routing.
Branch-specific admission and exact terminal behavior always win. Never run a
global invitation before the branch has passed its existing gates.

Only FlightCheck, Connect (including Workday aliases and lifecycle entries),
and foundation Setup may own eligible entries and offer automatic onboarding.
All other skills are excluded from profile handling: do not resolve, inherit,
apply, count, invite, or present proposals for them. `/profile` stays management.
A nested skill, including a FlightCheck or Connect called during Setup, inherits
the original owner's context only if it participates in profile handling and
never starts a second eligible entry. Do not pass profile context to excluded
skills, even when they are called by an eligible owner.

## Resolve-only request lifecycle

Reuse a caller-supplied immutable profile. Otherwise, after the existing
admission gates pass, call
`python scripts\user_profile.py experience resolve` once and use the returned
effective profile for flexible prose only. Do not call `experience begin` or
`experience finish`, change reminder history, or offer onboarding or proposals.
Continue the original task in the same workspace.

## Eligible request lifecycle

1. Preserve the original request and selected target. Create one canonical
   random UUID v4 request ID.
2. Call `experience resolve` once for one locked profile/experience snapshot.
   If the profile is invalid, surface its error. For unrelated work only, a
   caller may explicitly use `defaults` as temporary context.
3. Call `experience begin` once with the request ID and both returned version
   tokens. A conflict disables automatic prompts for this request; do not
   refresh tokens and retry. Render only the returned claim. For an
   `onboardingOffer`, read `src/skills/user-profile/onboarding.md` and follow
   its optional invitation, quiz, save/defer, and continuation instructions.
4. If the maker accepts onboarding, keep the original request, target, draft,
   and request ID in conversation context. Do not begin domain mutations
   until save, defer, or cancel. Replies, `Back`, confirmations, aliases, and
   nested skills are continuations, not new runs.
5. Save only confirmed typed values through one composite service call. Defer
   only with the retained invitation receipt. After successful save or defer,
   resolve one fresh execution snapshot; otherwise keep the entry snapshot.
6. Propagate the same immutable execution snapshot only to participating
   children. Never let a nested skill reread or replace it. Excluded children
   receive no profile context. A change during execution applies only to a
   later task.
7. At task completion, call `experience finish` once with actual task outcome
   and output permissions. It may claim one proposal only for successful
   flexible output with unused optional-suggestion budget and tips enabled.
   Never append after exact terminal or machine-readable-only output.

For these three eligible operations only, the claimed onboarding conversation
is a separate permitted interaction, even when domain output is restricted to
exact Message blocks or script results. It never rewrites those blocks or
interrupts a required selection, authorization, confirmation, or recovery turn.
Setup uses its resolved Python launcher for every profile command and preserves
its required progress render points; onboarding is not a setup stage or a
prerequisite for setup completion. Do not add a style indicator or automatic
proposal where the operation's output contract prohibits extra text.

If a claim response is lost, do not replay the prompt with refreshed tokens.
The receipt is at-most-once issuance; explicit `/profile` is the recovery path.
An evicted receipt is expired, not a new request. If conversation context is
lost, do not invent a task continuation.

## Immutable communication context

Carry `requestId`, `entryMode`, `entryOwner`, `entryHandled`, `runCounted`,
`phase`, `executionProfile`, `profileVersion`, `experienceVersion`,
`automaticPromptsAvailable`, original request, selected targets, draft values,
and answered fields in conversation context only. Never persist these drafts
or identify the maker.

Resolve preferences by precedence: security/authorization, destructive
confirmation, required choices, exact output contracts, current-task
instructions, saved values, then defaults. Adapt only flexible sections.
Contractual, machine-readable, and safety-critical content remains complete
and unchanged. The profile never authorizes an action.
