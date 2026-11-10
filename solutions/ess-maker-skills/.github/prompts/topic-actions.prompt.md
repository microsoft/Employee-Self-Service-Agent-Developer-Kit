---
mode: agent
description: "Review and approve ESS topic-set changes or restore original topic states on the selected agent"
---

# Topic actions

Read `src/skills/topic-actions/SKILL.md` first. It owns this route's narrower
target and workspace-preparation gate; do not require connection health or
`connect_ready: true`. Do not automatically start setup.

Follow its interaction and output contract: reuse known selections, keep
routine checks quiet, show one complete fresh execution review and collect
one explicit same-process approval decision. Listing and preview requests
need no approval. Do not add redundant confirmations, paste shell scripts or
raw helper output into responses, or offer unrequested follow-up actions.
Keep the supported interactive-terminal fallback when needed; do not
promise to hide host-rendered tool panels or bypass permission controls.

Use its source-inventory preview and same-session approval/execution flow.
For restore requests, use the fixed original baseline and recorded sets rather
than asking for a new selection. Restore only skill-affected topic states,
not old content. Missing original evidence or intervening edits block restore;
never silently replace the baseline with today's states. Initial baseline
capture is part of the one full review, not a second approval or an automatic
rollback policy.
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
are not required by this implementation; keep the unverified catalog,
package, protection and API assumptions visible in the review. Do not claim
customer-release qualification or proven draft/published isolation.
Never invent approval, prefill an approve response, publish, or bypass a
remaining identity, membership, state or freshness blocker through another
mutation path. A host must keep the execution process's input open until the
maker answers its review. Otherwise use an interactive terminal; do not
silently replace that review with approval saved from another invocation.
