# Profile editor and recovery

Use the central management entry and combined `experience resolve` snapshot.
Do not call `initialize` when opening the editor. Show missing-profile values
as defaults labeled **Not saved**. A read-only review or cancellation creates
no files.

## View and edit

Show a plain-language table in this order: **How replies are shaped**, **How
much detail**, **Preferred maximum length**, **Voice**, **Check-ins**, and
**Optional tips**. Do not use enum identifiers as UI labels. Offer to edit one
setting, edit several settings, retake the quiz, review pending suggestions,
reset to defaults, repair observed state, or exit.

Collect typed updates in conversation context and show the complete before/after
values. For direct edits, call `profile-save --values-stdin
--expected-version <token> --yes` once with a non-empty map. Saving even a
value equal to today's default pins it as explicit. Saving marks onboarding
completed. A retake starts from current saved values; skipped answers preserve
their values and sources. Use the same preview and review contract as
`onboarding.md`.

For natural language, distinguish a current-response override from a persistent
request. “For this answer”, “explain this in detail”, and “make that shorter”
do not write. “From now on”, “always”, “for every skill”, or “make this my
default” require showing the typed before/after mapping and offering **Save for
all skills**, **Just this reply**, and **Cancel**. Ask whether an ambiguous
request is current-only or persistent. `Just this reply` affects flexible
wording only; it never reruns domain mutations.

On profile version conflict, explain that the saved state changed, resolve
again, and require a fresh review. Do not silently overwrite or reuse an old
approval.

## Reset

Reset requires a separate explicit confirmation. Explain that all six settings
return to defaults, sources and proposal metadata are cleared, onboarding
returns to `not_started`, and reminder cadence is reset so a fresh invitation
may be offered. This differs from repair, which preserves profile preferences.
Call `reset --expected-version <token> --yes`. The service coordinates profile
reset and healthy reminder-history reset; if it reports a committed profile
with reconciliation required, do not retry the reset. Reconcile or repair
using the reported exact tokens and hashes.

## Repair

Offer repair only after the service reports damaged state. Never infer or
fabricate a hash. For profile damage, show that recovery resets preferences and
requires a separate confirmation; call `reset --recover
--expected-content-hash <observed-profile-hash> --yes`. The service keeps an
exact local backup.

For damaged reminder history, offer **Repair reminder history** separately
from **Reset my style**. Require explicit confirmation, the exact observed
experience content hash, and the current profile version. If profile state is
damaged, use its exact observed content hash instead of a version. Call
`experience recover --expected-content-hash <experience-hash>
--expected-version <profile-token> --yes`, or substitute
`--expected-profile-content-hash <profile-hash>` for a damaged profile. The
service backs up the exact reminder bytes and never changes profile
preferences. Invalid or unreadable bytes are never overwritten without
hash-authorized repair.

If an unmatched pending two-file intent blocks profile recovery, repair reminder
history first using the observed hashes; preserve its backup, then separately
recover the profile. Never silently discard intent data or automatically
repair both documents.
