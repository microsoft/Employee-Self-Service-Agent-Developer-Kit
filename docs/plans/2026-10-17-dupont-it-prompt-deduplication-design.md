# DuPont IT agent prompt — remove redundant clarify-first restatements

**Date:** 2026-10-17
**Target file:** `docs/plans/assets/dupont-ess-it-agent-prompt.md`

## Problem

The "clarify first when a request spans multiple distinct sub-categories" rule was restated, in
different wording, in 7 places: the opening "Core principle" paragraph, `Conversational
interaction style`, `Authoritative knowledge source`, `Clarifying questions`, `Response length and
focus`, `Answer format`, and the closing `Configurable behavior preference` section. Adding the
"Support resources and escalation" section's cross-reference (rule 3) didn't remove any of this —
it just pointed at the existing restatements rather than consolidating them.

## Approach

Trim in place rather than merge into one new section: each of the 7 locations keeps its own
distinct purpose (tone/examples, retrieval-specific operationalization, "when to ask" criteria,
response-formatting discipline, procedural answer templates), so only the sentence that purely
re-explains the rule — with no new operational detail — was removed from each. Sections that
stated the rule *with* genuinely new detail were left intact.

## Changes made

- **Core principle** (Core identity): unchanged — this is now the sole general statement of the
  rule.
- **Conversational interaction style**: removed the opening sentence restating "ask a clarifying
  question first"; kept the tone framing, all 3 examples, and the "ask fewest questions, one at a
  time" guidance (none of that is stated elsewhere).
- **Authoritative knowledge source**: unchanged — its bullet ties the rule to retrieval clustering
  specifically (single cluster -> answer directly and cite; multi-cluster -> clarify), which is
  genuinely new operational detail, not a restatement.
- **Clarifying questions**: removed the bullet that duplicated the Authoritative knowledge source
  bullet verbatim ("grounded knowledge search... spanning multiple distinct sub-categories");
  kept the other 4 criteria, which are each distinct reasons to clarify.
- **Response length and focus**: removed the trailing "If multiple distinct sub-categories exist,
  ask a clarifying question instead of listing them all" line; kept the Do/Don't lists.
- **Answer format**: unchanged — its 3-step procedural template for generic/ambiguous requests is
  a distinct contribution (the *shape* of the response once clarifying), not a restatement.
- **Configurable behavior preference**: removed entirely. Its one sentence ("Always clarify first
  for broad requests... never one long response") added no detail beyond Core principle and
  Response length and focus combined.

## Verification

Read the file end-to-end after all edits: no remaining sentence restates the clarify-first rule
outside of Core principle's canonical statement and Authoritative knowledge source's
retrieval-specific operationalization. Every other section's unique content (examples, citation
rules, criteria list, Do/Don't bullets, procedural steps) is intact and unchanged.
