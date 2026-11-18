# Instructions-curation skills for HR and IT agents — design

**Date:** 2026-10-19
**Target location:** `solutions/ess-maker-skills/src/skills/instructions/{curate-hr,curate-it}/SKILL.md`

## Problem

This session did a lot of ad hoc, manual curation of the HR and IT agent system instructions:
adding the 5 support-resource/escalation scenarios, deduplicating restated rules across headed
sections (twice, for IT), trimming to an 8000-character budget (discovering along the way that
Copilot Studio's own Instructions-box counter runs ahead of a plain LF byte count — most likely by
counting CRLF line breaks as 2 characters), building and maintaining a paired synthetic KB-article
sandbox plus eval-cases/eval-results files, folding in real UAT tester feedback as new eval cases,
and re-verifying after every edit that nothing regressed. None of this was written down as a
repeatable process — it lived only in this conversation.

This design packages that process as two skills in this product's existing skill-authoring
convention (`{category}/{verb}/SKILL.md`, matching `topics/create/`, `evaluations/validate/`, etc.),
so a maker (or a future agent) can run the same curation discipline against either agent's
instructions without re-deriving it from scratch.

## Scope decision: two skills, not one

The maker chose two separate skills (`curate-hr`, `curate-it`) over one parameterized skill. This
means the shared process (dedup, char-budget trim, eval-sandbox discipline, re-verification,
runtime-feasibility flagging) is written out independently in each file, and the agent-specific
facts (target file path, resource-grounding model, sandbox location) are baked into each file as
plain content, not shared code or a shared data file. A process fix found in one skill must be
applied to the other by hand — accepted as the cost of the maker's choice.

## Scope decision: curation only, not live deployment

`push.py`'s `classify_path` function recognizes topics (`.mcs.yml`), template-configs, workflows,
and evaluation reviews as pushable components — it has no path for an agent's `agent.yml`
`instructions:` field. Making this skill actually push to a live environment would mean extending
`classify_path` and adding a new push code path in a script every other skill in this product
depends on. That is out of scope for this change and is called out below as a follow-on, not
built now. The skills produced here end at "verified, char-budgeted, ready-to-paste text plus an
updated eval record" — the maker still pastes it into Copilot Studio's Instructions box by hand,
exactly as happened all session.

## Shared process (written independently into each SKILL.md)

1. **Locate current instructions.** Accept either a repo file path or maker-pasted text — both
   happened this session (the HR agent instructions started as a user paste; later sessions synced
   a "live" pasted version that had drifted from the repo file).
2. **Confirm the resource-grounding model before touching escalation wording.** Ask whether this
   agent has a *standing* destination offerable without retrieval (IT's ServiceNow portal) or *no*
   standing resource (HR — every named contact needs per-subject grounding). Never assume either
   way; this distinction changes how rules 2 and 5 of the escalation pattern are worded.
3. **Apply the 5-scenario escalation pattern**, reconciled into the existing structure:
   - Opening request to contact support, with the "already stated subject" carve-out (the HR rule-1
     gap found and fixed this session).
   - In-scope, unanswerable — resource named only if retrieval for that subject surfaced one.
   - Broad/ambiguous request — clarify using only actually-retrieved sub-categories, never a
     generic/assumed list (the "Dupont problem"); cross-reference existing clarify-first logic
     rather than duplicating it if the target prompt already has some.
   - Out of scope — never offer a resource, including a standing one.
   - Stuck after reasonable attempts — resource only if retrieval surfaced one; otherwise fall back
     to a standing destination if one exists for this agent.
   - Underlying grounding rule above all 5: never name a resource/fact not actually retrieved for
     the specific subject, regardless of which numbered rule is firing. This is the fix for the
     "ABBR bug" (an unrelated document's resource leaking into an unrelated answer).
4. **De-duplicate.** After any edit, diff section-by-section against the pre-edit version. Confirm
   no sentence restates another's trigger condition, and confirm every original requirement still
   appears somewhere (even if relocated or reworded) — don't just assert this, check it with a real
   diff.
5. **Character budget.** Default 8000 characters unless told otherwise. Trim iteratively by cutting
   word-economy/redundant phrasing, never by dropping a rule. Never target the limit exactly — build
   in a safety margin (a rough rule of thumb from this session: +1 character per line beyond a
   plain LF count, to account for a CRLF-counting deployment surface).
6. **Update the paired eval sandbox.** For each new/changed requirement, add eval cases (positive,
   negative, and a regression case where relevant) to the agent's `eval-cases.md`, referencing its
   KB sandbox folder for simulated retrieval. Walk every new case against the updated instructions
   and record a verdict in `eval-results.md`: PASS, PREDICTED PASS (when it's the exact real-world
   failure mode being fixed and is worth live re-verification, not just a manual walkthrough),
   SANDBOX GAP (the synthetic KB isn't rich enough to test this case), or OUT OF SCOPE (a
   platform/connector issue no prompt wording can fix). Critically, also **re-check every existing
   case whose expected behavior touches changed text** — don't assume no regression, diff and
   re-verify it.
7. **Flag runtime-feasibility limits.** If a requirement needs a multi-step check (search, then
   decide) before taking an action, confirm whether the target runtime can actually execute that —
   e.g., a Declarative Agent has no supported in-topic knowledge-retrieval node
   (`SearchAndSummarizeContent` is confirmed unsupported there). If it can't, say so explicitly: the
   requirement can only be expressed as a single-turn trigger-level heuristic, not a guaranteed
   multi-turn mechanism, and that limitation must be stated in the output, not silently assumed away.
8. **Present the diff and final character count for maker approval** before calling the curation
   done.

## Agent-specific content

| | `curate-hr` | `curate-it` |
|---|---|---|
| Target file | `docs/prompts/*hr-agent-instructions*` | `docs/plans/assets/dupont-ess-it-agent-prompt.md` |
| Standing resource | None — every named contact needs retrieval-grounding | ServiceNow portal — offerable without retrieval |
| KB sandbox | `docs/plans/assets/hr-kb-sandbox/` | `docs/plans/assets/dupont-kb-sandbox/` |
| Eval files | `hr-agent-eval-cases.md` / `hr-agent-eval-results.md` | `dupont-it-eval-cases.md` / `dupont-it-eval-results.md` |
| Extra step | — | Ingest real UAT tester feedback (pasted rows/screenshots) as new eval cases mapped onto the KB sandbox, distinguishing genuine prompt gaps from sandbox-fidelity gaps from platform/connector bugs (e.g. citation rendering) |

## Follow-ons (explicitly not built in this change)

- Extend `push.py`'s `classify_path` and push logic to support an agent's `instructions:` field as
  a live-pushable component, so this curation could end in an actual deployment instead of a
  ready-to-paste text block.
- An optional helper script (e.g. `scripts/char_budget_check.py`) to automate the trim/recount loop
  and section-diffing instead of doing it by hand with `wc`/`diff` each time.
