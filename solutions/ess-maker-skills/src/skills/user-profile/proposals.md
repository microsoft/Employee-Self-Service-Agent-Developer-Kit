# Pending preference suggestions

Automatic learned-preference proposals are considered only after the original
task completes successfully, the output allows additional text, optional tips
are not off, and no other optional suggestion used the response budget. Never
interrupt execution, append to exact terminal output, or consume an attempt
when presentation is disallowed.

Use `experience finish` to atomically mark the request complete and claim at
most one due proposal. Respect the returned proposal and reviewed profile
version exactly. Prefer canonical preference order; do not let a snoozed
proposal block other eligible fields.

Show a generic saved-preference suggestion, observation count, current and
proposed values in maker-facing language, and state that the typed value,
count, confidence, and decision timestamps stay local while raw messages are
not stored. Do not invent a time window, skill-specific reason, or observation
history. Do not expose confidence as persuasion.

Offer **Make this my default**, **Keep my current setting**, and **Ask me
later**. Accept and reject use the exact reviewed profile version. Acceptance
may replace an explicit value because it was authorized; rejection preserves
terminal proposal metadata. A stale profile conflict requires a fresh review,
not a silent retry.

For **Ask me later**, call `proposal-snooze --origin automatic` with the
returned field, proposal `createdAt`, and both exact reviewed tokens. The first
deferral does not restart the cadence; after the second automatic deferral the
service suppresses further automatic display. `/profile` still shows pending
proposals, including suppressed ones and when optional tips are off. Explicit
review and snooze do not consume an automatic presentation attempt.

Do not observe conversations, calculate confidence, or call `propose` based
on chat history. Proposal generation is out of scope.
