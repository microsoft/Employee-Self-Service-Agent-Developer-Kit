---
mode: agent
description: "Review and approve enabling or disabling ESS topic sets on the selected agent"
---

# Topic actions

Read `src/skills/topic-actions/SKILL.md` first. It owns this route's narrower
target and workspace-preparation gate; do not require connection health or
`connect_ready: true`. Do not automatically start setup.

Follow its interaction and output contract: reuse known selections, keep
routine checks quiet, show one complete fresh execution review and collect
one explicit structured chat approval decision. Listing and preview requests
need no approval. Show those requests as a concise topic inventory with short
topic names and current states, not requested states, plans, change counts or
write-specific limitation notes. Keep unresolved topics and blockers visible.
Use "No change" instead of "Already correct" in execution plans.
Do not add redundant confirmations, paste shell scripts or
raw helper output into responses, or offer unrequested follow-up actions.
Keep the supported interactive-terminal fallback when needed; do not
promise to hide host-rendered tool panels or bypass permission controls.
Render the helper's `userMessage` verbatim for each review and result.
Do not paraphrase it, add warning lists, display internal codes or append raw
diagnostic messages. Material limitations stay in the plain-language
"Before you approve" notes; safe technical details are available on request.

Use its source-inventory preview or Workday-style review/approval/apply flow.
Once enable/disable sets are established, use `--review`; never replace
the requested change with a read-only listing. For verified no-change enable/disable, display
the `already_correct` result and stop without approval or `--apply-review`.
Only `review_ready` permits approval. Display the
returned review, collect an unset Approve/Deny/Cancel structured question, then
send only the actual answer with `--apply-review` and `--decision`. A dismissed
or ambiguous answer cancels. No waiting process, stdin continuation, computer
control or generated approval bridge is needed. A review is single-use and
expires after five minutes; changed evidence requires fresh review and consent.
Restore and undo of earlier changes are not supported. Do not substitute
the opposite action: earlier topic states may have been mixed.
Enable/disable uses current live states without a baseline, history question
or `initializeBaseline` input. Leave existing original-state files untouched.
If prerequisite inspection or the helper
fails, report the blocker and supported next step. Do not expose raw inputs,
exceptions, caller context or service bodies.
Distinguish setup not established, incomplete and broken. `/setup` is a
supported setup entry, not a universal repair command or package installer.
Do not label unavailable evidence as missing packages, access denial or an
already-correct result. Before writes, cancellation says "Canceled. No topics
were changed." Preserve confirmed caller progress without promising an
unverified automatic return or resume.

Native writes are not restricted to Dev agents or ALM-enrolled agents.
Verify the exact selected native target and account; the service enforces
edit access. Use the topic-action-owned component client, not Connect
Workday's client or update logic. Central release admission and prequalification
are not required by this implementation; keep material catalog,
package, protection and API limitations visible through the fixed review notes. Do not claim
customer-release qualification or proven draft/published isolation.
Never invent approval, prefill an approve response, publish, or bypass a
remaining identity, membership, state or freshness blocker through another
mutation path. Never retry a consumed review, reuse an earlier answer, or claim
completion until the apply result verifies it. Use the interactive terminal
only when the maker requests it or a structured chat question is genuinely
unavailable, not because direct terminal input continuation is missing.
