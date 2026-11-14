# HR agent: support resource & escalation design

**Date:** 2026-10-15
**Output:** `docs/prompts/2026-10-15-hr-agent-instructions-support-escalation.md`

## Problem

The HR agent's instructions had one escalation rule, which let support resources leak in
whenever an unrelated retrieved document happened to contain one (e.g., "What is the definition
of ABBR?" surfaced an HR contact line from an unrelated Employee Handbooks article). There was
no explicit handling for:

1. A user's first message directly asking to open a support case or how to contact HR.
2. An in-scope question the agent can't answer because no knowledge source/capability covers it.
3. A broad question (e.g., "how do I reset my password") — needs clarification, but the
   clarification options must reflect what's actually retrievable, not a generic guess
   (the "Dupont problem").
4. An out-of-scope question (e.g., an IT question posed to the HR agent) — must never offer a
   support resource.
5. A user stuck after reasonable back-and-forth who explicitly asks for help.

## Approach

Added one new section, **"Support resources and escalation,"** replacing the old single bullet
in "Source and accuracy requirements." It opens with the governing grounding rule — a resource
may only be named if retrieval performed for the user's specific subject actually returned one,
never because it appeared in an unrelated document, is assumed to typically exist, or the search
simply returned nothing — then lists the 5 scenarios as numbered rules, each stating whether a
resource may be offered and under what condition.

Rules 2 and 5 are kept separate (not merged) even though both are "no answer available": rule 2
fires on first failure, rule 5 only after repeated attempts on the same subject plus an explicit
ask for help. Rule 3 (broad/Dupont) explicitly forbids naming a resource at the clarification step
and requires that any subject options offered come from retrieved sources/tools, not a generic
list. Rule 4 (out of scope) is an explicit "never offer" to prevent a support resource from
leaking across domains (HR agent fielding an IT question).

"Grounded" is defined narrowly per the user's decision: a resource counts as retrieved only when
a search run for that specific subject in the current turn returned it — not reused from an
earlier, unrelated retrieval in the same session.

## Constraints honored

- Full backward compatibility: core identity, absolute prohibitions, context/role handling,
  response-ending rules, source/accuracy discipline, role boundaries, and tone/capitalization
  rules are unchanged in substance (wording tightened only to make room).
- Under 8,000 characters (final: 7,994).
- No new variables or capabilities invented — the design relies only on the existing
  retrieval-grounding mechanism already present in the rest of the instructions.

## Why no implementation plan

This is a single prompt/instructions document with no supporting code in this repository — the
revised text in `docs/prompts/2026-10-15-hr-agent-instructions-support-escalation.md` is the
complete deliverable, to be pasted into the agent's configuration directly. There is no
code-change implementation phase to plan.
