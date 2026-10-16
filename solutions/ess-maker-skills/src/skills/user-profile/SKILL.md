# Maker communication profile

Manage the maker's local communication preferences. This profile is separate
from employee data, agent configuration, and runtime ESS behavior. Use it only
for flexible maker-facing language; never change facts, permissions, required
choices, exact messages, machine-readable artifacts, or safety-critical
content. Saved preferences apply only to FlightCheck, Setup, and Connect;
other skills do not load, inherit, or apply them.

## Entry and privacy

- `/profile` and clear requests to review or change maker communication style
  work before setup and without an agent or environment.
- This management flow never increments eligible-run counts and never makes
  automatic onboarding or proposal claims.
- Read `shared/user-profile-entry.md` and `shared/user-profile-contract.md`.
- Invoke `python scripts\user_profile.py experience resolve`; do not access
  either local JSON document directly.
- A missing profile is shown as defaults labeled **Not saved**. Reading,
  previewing, or cancelling creates no profile or experience file.
- Surface invalid profile state and offer only hash-matched, separately
  confirmed repair. Invalid reminder history does not block valid profile
  viewing or saving; disclose that automatic reminders are unavailable.
- Never retain free text, drafts, persona labels, prompt text, or identity
  details in persistent state or telemetry.

## Route by intent

- First-use or deferred invitation: read `onboarding.md`.
- View, edit, retake, persist a style change, reset, or repair: read
  `editor.md`.
- Review a pending preference proposal: read `proposals.md`.
- For mixed requests, allow the profile action but apply the requested task's
  original setup, permission, capability, target, and confirmation gates
  independently.

## Save and continuation

Only explicit approval authorizes persistence. Collect edits in conversation
context, show the before/after or full review, and send typed values only to
the service. After a successful save, say the new style applies to the next
request. Do not silently change a running task's frozen profile or repeat its
domain operations.

When this flow was opened as an invitation, return to the entry owner with the
same request ID and original request after save, defer, or cancel. Do not count
the continuation again. A direct `/profile` cancellation writes nothing.
