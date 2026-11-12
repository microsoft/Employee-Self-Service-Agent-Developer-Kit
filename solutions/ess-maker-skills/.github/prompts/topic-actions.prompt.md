---
mode: agent
description: "List current ESS topic sets, or review and approve enabling or disabling them"
---

# Topic actions

Re-read `src/skills/topic-actions/SKILL.md` from disk on every invocation,
even if this conversation read it earlier. Do not reuse earlier question
options or remembered available sets. It owns this route's narrower
target and workspace-preparation gate; do not require connection health or
`connect_ready: true`. Do not automatically start setup.

## Mandatory set-picker gate

Never batch action and set selection into one question call. If the action
is unknown, ask Enable/Disable/List in that order, keeping the host's
"Enter custom answer" fourth. Wait for the answer, then run
`--list-agent-sets` for the currently selected agent before any set picker.
If the action is already known but sets are unknown, run that same fresh
discovery before asking for sets.

Render the returned `userMessage`. For enable/disable, pass the returned
`selectionQuestion` unchanged as the sole next structured question. Its
options contain only friendly set names, without state/count suffixes or
descriptions; keep counts and states in the overview only. This applies to
all four supported sets. These are the complete allowed picker choices; map answered labels back
to the keys in the same response's `sets`. Never add catalog entries,
integration/HR/IT combinations, custom-answer fields or remembered choices.
Do not use `--list-sets` or `catalog.provisional.json` as a picker source.
If `selectionQuestion` is absent/null or discovery failed, do not show a
set picker or fall back to the catalog. Listing stops after the overview
without using `selectionQuestion`. A known action and explicit set selection
still go directly to fresh review.

## Review and output

Follow its interaction and output contract: reuse known selections, keep
routine checks quiet, show one complete fresh execution review and collect
one explicit structured chat approval decision. If the action is unknown,
ask Enable/Disable/List in that order, with "Enter custom answer" fourth.
Then use `--list-agent-sets` to show the
selected agent's live set count, friendly names, present topic counts and
Enabled/Disabled/Mixed/Unknown states. Listing stops there, without a set
question or approval. Enable/disable without known sets uses a structured
multi-select supplied by `selectionQuestion`, not a free-text internal-key question.
Do not invent catalog-only choices or treat failed/incomplete discovery as
an empty success. Reuse an explicit action and sets without this detour.
Listing and previews need no approval. Only explicit topic-detail previews
show individual short topic names and current states, not requested states,
plans, change counts or write-specific limitation notes.
Keep unresolved topics and blockers visible.
Use "No change" instead of "Already correct" in execution plans.
Do not add redundant confirmations, paste shell scripts or
raw helper output into responses, or offer unrequested follow-up actions.
Keep the supported interactive-terminal fallback when needed; do not
promise to hide host-rendered tool panels or bypass permission controls.
Render the helper's `userMessage` verbatim for each review and result.
Do not paraphrase it, add warning lists, display internal codes or append raw
diagnostic messages. Do not add a "Before you approve" section or replacement
warning notes. Limitations stay in structured diagnostics; safe technical
details are available on request.

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
the opposite action: earlier topic states may have been mixed. Ask for the
desired enable/disable action only if unknown, then offer live set choices
if sets are unknown.
Enable/disable uses current live states without a baseline, history question
or `initializeBaseline` input. Leave existing original-state files untouched.
Use the live agent's present topics as the enable/disable scope for each
requested set. Ignore absent template members without warnings; agents can
have different topic counts. If none are present, say
"<set-key> topics are not available in this agent." Keep ambiguity, state,
protection and freshness safeguards.
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
are not required by this implementation; retain catalog, package, protection
and API limitations in structured diagnostics for technical questions. Do not claim
customer-release qualification or proven draft/published isolation.
Never invent approval, prefill an approve response, publish, or bypass a
remaining identity, membership, state or freshness blocker through another
mutation path. Never retry a consumed review, reuse an earlier answer, or claim
completion until the apply result verifies it. Use the interactive terminal
only when the maker requests it or a structured chat question is genuinely
unavailable, not because direct terminal input continuation is missing.
