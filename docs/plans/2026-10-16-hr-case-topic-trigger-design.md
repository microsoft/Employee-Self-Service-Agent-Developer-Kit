# HR case-creation topic trigger description — design

**Date:** 2026-10-16
**Related:** `docs/prompts/2026-10-15-hr-agent-instructions-support-escalation.md` (main HR
agent instructions), `solutions/ess-maker-skills/src/examples/ess-samples/ServiceNow/HRSDScenarios/ServiceNowHRSDCreateCase/topic.yaml`
(reference implementation of the topic being described)

## Problem

The user's live Copilot Studio environment has a trigger description for the "create/open/submit
an HR case in ServiceNow" topic. It predates the escalation rules just added to the main HR agent
instructions and has two gaps relative to them:

1. **No resolvability gate.** The topic can trigger on a subject the HR agent's own knowledge
   sources can already answer (e.g., "Submit an HR case about my benefits"), creating an
   unnecessary ServiceNow case instead of just answering — the same "don't escalate when you can
   answer" discipline the main instructions apply everywhere else.
2. **No context-gathering gate.** The topic can trigger on a bare command with no subject (e.g.,
   "Create an HR case"), before the opening-request clarification the main instructions now
   require (rule 1: ask what the issue is, unless already stated) has happened.

## Goal

Update only the topic's trigger description (not its internal dialog logic) so routing decisions
are consistent with the main agent instructions: trigger only once a subject is both known and
not better served by a direct answer, with one explicit override for a user who insists on a case
after already getting an answer.

## Approach

Restructure the flat "Trigger only if" bullet list into the existing style but add two new gating
conditions (not a full rewrite of unrelated bullets):

- **Context-gathering gate:** require the message to already state or have already established
  the subject. A bare "create an HR case" does not trigger; it's expected to fall to the main
  agent's opening-request clarification turn first, and this topic then triggers on the follow-up
  turn once the subject is known.
- **Resolvability gate:** require that the subject can't be resolved from existing HR knowledge
  sources, OR the user explicitly insists on a case after already receiving an answer.

Corresponding bullets are added to "Do NOT trigger," and examples are added/replaced to make both
gates concrete (a bare "Create an HR case" moves from the valid list to the invalid list; a
subject-bearing version and an explicit-override version are added as valid).

## Scope boundary

This change touches only the trigger/description text. The reference `topic.yaml`'s own internal
flow (`sendIntro` → `askSubject` → `askDescription` → ...) still asks for a subject *after*
triggering — that becomes partially redundant once the context-gathering gate is in place, since
the subject will already be known by trigger time on the common path. Adjusting that internal
flow is an explicit, separate follow-on and is not done here.

## Output

The complete revised trigger description text, provided as a plain-text deliverable the user can
paste into their Copilot Studio topic configuration — not a code change in this repository, since
the live topic configuration lives outside this repo.

## Update 2026-10-16 — live testing findings and revision

Live testing (Declarative Agent runtime) surfaced that the first description (dated 2026-10-16,
pre-update) did not hold: a bare "Create a Hr Case" message triggered the topic immediately, and
once triggered, the topic's own scripted `askSubject` question captured the next message
("i am not able to update benefits") and proceeded straight to a ServiceNow case-creation call —
with no resolvability check in between. The call errored, and only then did a knowledge-grounded
answer about benefits guidance appear, as an unrelated fallback.

Root-caused as follows:

1. **The resolvability gate cannot be enforced after trigger.** Once a topic fires, its own
   scripted dialog nodes run deterministically; the orchestrator does not re-consult the topic
   description, the root agent instructions, or any knowledge source on later turns within that
   same active dialog. A "check knowledge, then decide" step can only exist as a node inside the
   topic (or a competing topic that preempts it via `allowInterruption`).
2. **No DA-compatible retrieval node exists.** The classic `SearchAndSummarizeContent` node is
   confirmed unsupported for Declarative Agents (per this repo's own migration rule, RULE-007),
   and the user confirmed the agent is on the DA runtime and that no knowledge/search action node
   is available in the topic canvas at all. This rules out both an in-topic retrieval node and a
   new, separate competing topic that would retrieve knowledge as its action — there is currently
   no node to build either with.
3. **The only reliable lever left is the initial, single-turn trigger decision.** The orchestrator
   does make a fresh choice on a turn with no active dialog. The fix is therefore to make the
   "don't trigger on a bare, subject-less message" condition the primary, unambiguous, first-
   stated rule (not one bullet among several), so that a bare "create an HR case" falls through to
   the root agent instructions (which already handle "what's the issue?" per rule 1 of
   `docs/prompts/2026-10-15-hr-agent-instructions-support-escalation.md`) instead of being
   captured by this topic's own scripted question. The subject-bearing follow-up then arrives as a
   fresh turn, giving the orchestrator another real chance to prefer a direct knowledge-grounded
   answer over invoking this topic.

**Known limitation, stated plainly:** this remains a probabilistic, prose-driven trigger decision,
not a mechanical gate. The same classifier that previously under-weighted the "wait for subject"
condition could still occasionally fire early. There is no way to make this airtight without a
DA-compatible retrieval action becoming available. Re-test against the eval cases in
`docs/plans/assets/hr-agent-eval-cases.md` after publishing, and treat this as mitigation, not a
guarantee, until Copilot Studio exposes a supported in-topic knowledge node for DA.

**Final deliverable:** `docs/prompts/2026-10-16-hr-case-topic-trigger-description.txt` (1,015
chars), revised to lead with the subject-presence requirement.
