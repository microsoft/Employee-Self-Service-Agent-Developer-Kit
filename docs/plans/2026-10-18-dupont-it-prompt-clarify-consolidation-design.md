# DuPont IT agent prompt — second consolidation pass (clarifying questions)

**Date:** 2026-10-18
**Target file:** `docs/plans/assets/dupont-ess-it-agent-prompt.md`

## Problem

A first dedup pass (2026-10-17) removed 4 pure restatements of the clarify-first rule. Re-reading
the file for this follow-up found more, smaller overlap that pass missed:

- The printer example appeared twice — once in "Conversational interaction style" (descriptive
  form) and again in "Clarifying questions" (full-sentence form) — the same example, two homes.
- "Answer format"'s "For generic or ambiguous requests" template (acknowledge -> ask -> wait) is
  the procedural version of the same clarify-first mechanism already described elsewhere.
- "Clarifying questions"' closing line ("Do not ask unnecessary questions when... clear") is the
  inverse restatement of Core principle's closing sentence.
- "Response length and focus"'s "Do not present all available options at once" bullet is a
  corollary of the same rule, not new information.

The user separately confirmed (in conversation) that clarify-first should stay a distinct concern
from "Support resources and escalation" — it's a general answer-quality rule, not an escalation
rule — so this pass keeps that conceptual boundary, and only targets the *internal* scatter across
the 5 sections that already owned clarify-first.

## Approach

Consolidate "Conversational interaction style" and "Clarifying questions" into one section
(renamed "Clarifying questions," since that's the operative behavior), and fold in:
- The single-cluster/multi-cluster retrieval bullet from "Authoritative knowledge source" (moved,
  not duplicated — the source section keeps only grounding/citation rules now).
- The "For generic or ambiguous requests" procedural template from "Answer format" (moved — that
  section keeps only its other two templates, which aren't about clarifying at all).

No requirement is dropped. Every criterion, every example topic (printer/password/laptop), the
formatting mechanics (reflect, name 2-4 retrieved-only options, "something else" catch-all), and
the sequential-narrowing guidance all survive — they're just stated once, in one place, instead of
scattered with partial restatement across 5 headers.

One addition beyond pure consolidation: explicit language for sequential/nested clarification
("if a narrowed request still spans distinct sub-categories... ask again rather than guessing"),
directly addressing the real UAT gap found in the Gold Prompt validation (row 1: password reset
asked system but never followed up with known-vs-locked once narrowed to Windows). This was
implicit in the rule before (it fires per retrieval event) but not called out, and the UAT evidence
showed that mattered.

## Verification plan

After editing, diff the full file against its pre-edit state and confirm:
- Every criterion/example/template from the 5 original sections is still present somewhere.
- No sentence restates another sentence's trigger condition.
- `Support resources and escalation` rule 3's cross-reference still resolves correctly (it already
  says "Already handled by the Core principle and Clarifying questions above," which remains
  accurate after the rename/merge).
- Re-run the eval suite in `dupont-it-eval-cases.md` / `dupont-it-eval-results.md` mentally against
  the new text to confirm no case's expected behavior changed for the worse.
