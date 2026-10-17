# OOB IT agent — escalation scenarios design

**Date:** 2026-10-16
**Target file:** `tools/ess-ca-to-da/reference/it/agent.yml` (`metadata.instructions` block, line 534)
**Related:** `docs/prompts/2026-10-15-hr-agent-instructions-support-escalation.md` (HR equivalent)

## Scope

Apply only the 5 escalation scenarios already designed for the HR agent, to the **out-of-box**
IT agent instructions (not `docs/plans/assets/dupont-ess-it-agent-prompt.md`, which is a separate,
richer DuPont-customized draft left untouched). Explicitly excluded from this change:

- The `#Routing decision tree` (Workday/ServiceNow/KB topic classification) — untouched.
- DuPont's conversational-style additions (worked examples, Do/Don't lists, citation-integrity
  rules) — not carried over. OOB's terse, rule-dense voice is kept throughout.
- Scope question raised in the earlier analysis (whether Workday self-service belongs in this
  agent at all) — deferred, not part of this change.

## Changes

1. **New `#Support resources and escalation` section**, replacing the existing single-line
   `Abstain with: ...` sentence (previously in `#Tool-first grounding`) and the `EAP/People team
   for severe cases or explicit support requests only` sentence (previously in `#Handoff and
   emotional intelligence`). Consolidates both into one grounded, numbered section mirroring the
   HR agent's rules 1-5, adapted to IT's existing "abstain" line and the ServiceNow portal as its
   standing (non-retrieval-gated) fallback destination — a deliberate asymmetry from HR, where no
   such standing resource exists.
2. **One-line amendment to "Pre-call clarification"** (step 2 of the routing decision tree): OOB's
   existing text claimed KB ambiguity "never blocks initial search," meaning a multi-category KB
   result would get answered directly rather than clarified — the opposite of the HR agent's rule
   3 (the "Dupont problem" fix). Narrowed to apply only to single-sub-category ambiguity, with a
   cross-reference to the new section's rule 3 for the multi-category case.

## Why this reconciliation, not a straight copy

OOB's clarification already runs *before* any KB call (for queries too vague to search at all —
"bare umbrella" terms like "my laptop isn't working"). That pre-search gate stays as-is: it solves
a different problem (avoiding a wasted/unfocused search) than rule 3 (what to do once retrieval
itself comes back spanning multiple distinct topics). Keeping both means: vague query -> clarify
before searching; specific-enough query whose retrieval still spans categories -> clarify after
searching, grounded only in what was retrieved. This is the same two-stage shape the eval cases
validated for HR (case 6 vs. case 12: multiple categories retrieved vs. zero).

## Output

Edited directly into `tools/ess-ca-to-da/reference/it/agent.yml`'s `instructions:` block — this is
a reference/baseline file in the repo (not a live Studio config pulled from outside it), so the
change is a normal repo edit and commit, unlike the HR/text-file deliverables.

## Update 2026-10-16 — redirected to the DuPont asset file

After this design was applied to a standalone text deliverable based on the OOB baseline
(`docs/prompts/2026-10-16-oob-it-agent-instructions-support-escalation.txt`), the user asked to
apply the same 5 scenarios to `docs/plans/assets/dupont-ess-it-agent-prompt.md` instead — the
richer, DuPont-customized IT agent prompt, not the OOB baseline. The OOB-targeted file above is
left as-is (unused, not deleted, since it may still be useful as a reference).

Applying to the DuPont file changes the approach from the OOB pass in two ways:

1. **No style stripping.** The "keep OOB's terse voice, don't carry over conversational style"
   constraint doesn't apply here — this file's richer voice (Do/Don't lists, worked examples,
   citation-integrity rules) is its own, not something borrowed from elsewhere, and stays as-is.
2. **Scenario 3 (broad/Dupont question) needs no new logic** — this file already has the most
   mature version of it in the repo (the "Core principle," "Conversational interaction style," and
   "Clarifying questions" sections already clarify using only retrieved sub-categories). The new
   section cross-references this instead of duplicating it.
3. **The existing `## Escalation behavior` section stays untouched** — its categorical list (admin
   access, security incident, data loss, etc.) governs when the *standing* ServiceNow portal
   applies, which is a different and compatible concept from the new section's grounding rule for
   *named* contacts/resources.

New section inserted directly after `## Escalation behavior`, in the file's own markdown-heading
style (not plain prose like the OOB `.txt`), covering scenarios 1, 2, 4, and 5 as new content and
scenario 3 as a cross-reference.
