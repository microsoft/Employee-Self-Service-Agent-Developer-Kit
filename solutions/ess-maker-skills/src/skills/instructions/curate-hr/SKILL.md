# Curate HR Agent Instructions

Update the HR agent's system instructions given a new or changed set of requirements, applying the
same support-resource/escalation discipline and verification rigor developed for the Northern
Trust HR agent, without a wholesale rewrite and without exceeding the character budget.

This skill produces a curated, verified, ready-to-paste instructions text plus an updated eval
record. It does not push to a live Copilot Studio environment — `push.py` has no path for an
agent's `instructions:` field today. A maker still pastes the result into the Instructions box by
hand.

## Inputs

- The current HR agent instructions: either a repo file (look first at
  `docs/prompts/*hr-agent-instructions*`) or text the maker pastes directly from the live
  Instructions box. Treat a pasted version as authoritative for this run even if it has drifted
  from the repo file — note the drift, don't silently overwrite it without telling the maker.
- A plain-language description of the new or changed requirement(s).
- Optional: a character budget. Default to 8000 if the maker doesn't state one.

## Step 1: Read the current instructions

Read the full current instructions text before changing anything. If it's a repo file, read it
directly. If pasted, save it to a working file so later diffing has something to diff against.

If what you're given looks like it's drifted from the repo's maintained version, say so — don't
silently reconcile the two without the maker's say-so.

## Step 2: Confirm the resource-grounding model

The HR agent has **no standing resource**. Unlike an agent with a generic self-service portal it
can always point to, every named contact, case line, or resource the HR agent offers must be
grounded by a retrieval that actually returned it for the user's specific subject — there is no
safe generic fallback to offer instead. Hold this as fixed. If the new requirement seems to
introduce something that behaves like a standing resource (e.g., "always mention the HR support
case form"), stop and ask the maker to confirm that's really intended, since it changes the
escalation model materially.

## Step 3: Classify the requirement, then apply

First decide what kind of requirement you were given:

- **Extends or modifies one of the 5 known escalation scenarios** (opening request, in-scope
  unanswerable, broad/ambiguous, out-of-scope, stuck-after-attempts) → follow the worked pattern in
  Step 3a below. This pattern is validated: it's been built, tested, and fixed against real gaps
  (the rule-1 "already stated subject" carve-out was a real bug found by testing, not a
  hypothetical).
- **A new rule category entirely** — tone, formatting, a citation requirement, a new eligibility or
  routing rule, a new prohibition, anything that isn't about when/how to escalate or name a
  resource → there is no pre-validated pattern for this. Don't force it into the 5-scenario shape.
  Instead:
  1. Find the most structurally similar existing section in the current instructions (or decide a
     new section is genuinely warranted) and state the new rule there, once.
  2. Hold it to the same grounding discipline as everything else in the document: never assert a
     fact, capability, or exception the document doesn't already authorize from an approved source
     or configured tool.
  3. Explicitly tell the maker in your output that this is a **novel rule category without a
     pre-validated pattern** — recommend they review it more carefully than an escalation-scenario
     change, and treat your first eval cases for it (Step 6) as a first draft to refine, not a
     proven-correct pattern.
  Still run Steps 4-8 (dedup, char budget, eval sandbox, runtime-feasibility flag, approval) exactly
  as written — those are general-purpose and apply regardless of which kind of requirement this is.

## Step 3a: Apply the escalation pattern for the new requirement

The HR agent's instructions should already have (or should gain, if missing) a dedicated
escalation section covering these five rules, each gated by one grounding sentence that governs
all of them: **name a resource only when retrieval for the user's specific subject actually
returned one — never because it appeared in an unrelated document, because one typically exists,
or because the search returned nothing.**

1. **Opening request to contact support.** If the first message asks to open a case or how to
   contact HR, confirm you can help and ask the user to describe the issue — **unless the subject
   is already stated in that same message**, in which case proceed straight to rules 2-5 for that
   subject. (This carve-out was a real gap found by testing — an agent that always re-asks even
   when the subject is already given is redundant and un-conversational. Don't drop it.)
2. **In-scope, unanswerable.** If no retrieved source or tool addresses the subject, say it could
   not be found. Name a resource only if retrieval for that subject surfaced one; otherwise say
   none is available — don't invent one because it feels like it should exist.
3. **Broad or ambiguous request ("the Dupont problem").** If the request is too broad to answer
   directly, ask one clarifying question naming only the sub-categories actually covered by
   retrieved sources — never a generic or assumed list of options. Do not name a resource at this
   step. If the target instructions already have clarify-first logic elsewhere (they may not — this
   is HR-specific, not guaranteed the way it is for the IT agent), cross-reference it instead of
   restating it.
4. **Out of scope.** If the question is outside this agent's domain (e.g., an IT question asked to
   the HR agent), say so and stop. Never offer a resource here.
5. **Stuck after reasonable attempts.** If the user has made repeated attempts on the same subject
   and explicitly asks for help, and retrieval for that subject surfaced a resource, offer it.
   Since HR has no standing resource, if nothing was ever retrieved for the subject, say so plainly
   — do not invent a contact just because the user is visibly stuck.

Map the plain-language requirement you were given onto whichever of these five it actually changes.
Most requirement changes will touch one rule, not all five — resist rewriting the whole section
when only one sentence needs to change.

## Step 4: Edit with minimal diff, then de-duplicate

Edit the instructions to reconcile the requirement into the *existing* structure — do not rewrite
sections that aren't affected. HR's instructions have previously needed two kinds of cleanup after
edits like this:

- A rule restated in multiple sections (found and fixed once already — watch for a new edit
  re-introducing this, e.g., stating the same escalation condition both in the dedicated escalation
  section and again in a general "response behavior" section).
- A section whose closing summary just repeats an earlier section's content with no new detail —
  these are safe to trim or remove outright.

After editing, diff the full file against the pre-edit version:
- Confirm only the lines relevant to the requirement changed.
- Confirm no sentence restates another sentence's trigger condition.
- Confirm every requirement that existed before this edit still appears somewhere — even if
  reworded or relocated. If you can't find where an old requirement went, you dropped it; put it
  back or flag it as an explicit, maker-approved removal.

## Step 5: Enforce the character budget

Count the file's characters (plain LF count is fine as a first pass: `wc -c` after stripping `\r`).
If over budget, trim iteratively:

- Cut word-economy and redundant phrasing (tighten sentences, remove filler), never drop a rule to
  make room.
- Re-count after each cut; don't guess and submit untested.
- **Do not target the budget exactly.** Copilot Studio's own Instructions-box character counter has
  been observed running ahead of a plain LF byte count by roughly one extra character per line —
  consistent with it counting `\r\n` line breaks as 2 characters where a plain count uses 1. Leave
  a safety margin (as a rule of thumb, aim to land comfortably under budget by at least the file's
  line count, e.g. ~70-100 characters of margin for a ~70-line file) rather than landing at exactly
  8000 by your own count.
- If the maker reports the live counter still shows the content truncated or over budget after you
  believed it fit, don't assume duplicate/leftover content in the field without asking — confirm
  whether the field was cleared before pasting, then re-measure precisely (find the actual
  truncation point in your text and compare the character offset to what the live counter shows)
  before guessing at a cause.

## Step 6: Update the paired eval sandbox

The HR agent's sandbox lives at `docs/plans/assets/hr-kb-sandbox/` (synthetic KB articles), with
`docs/plans/assets/hr-agent-eval-cases.md` (scenario table: rule tested / user turn(s) / simulated
retrieval / expected behavior) and `docs/plans/assets/hr-agent-eval-results.md` (manual walkthrough
verdicts).

For the requirement you just implemented:

1. Add one or more new cases to `hr-agent-eval-cases.md` covering it — include a positive case
   (the requirement behaving correctly) and, where it makes sense, a negative/edge case (a
   plausible way the requirement could be misapplied — e.g., firing when it shouldn't, or not
   firing when it should).
2. If the requirement is itself the fix for a previously-observed bug (your own equivalent of the
   "ABBR" unrelated-document-leak regression), add a dedicated regression case for it.
3. If the synthetic KB sandbox doesn't have enough breadth to construct a realistic case (too few
   articles, missing a sub-category the real KB would have), say so explicitly and mark the case a
   **SANDBOX GAP** in the results rather than forcing a verdict on insufficient data. Recommend
   expanding the sandbox if the case matters for sign-off.
4. Walk every new case by hand against the updated instructions and record one of: **PASS**,
   **PREDICTED PASS** (used when the case is the exact real-world failure mode being fixed and the
   text now supports it, but it's worth confirming against the live agent rather than trusting a
   manual read), **SANDBOX GAP**, or **OUT OF SCOPE** (a platform/connector issue, like citation
   rendering, that no instructions wording can fix).
5. **Re-check every existing case whose expected behavior touches text you changed in Step 4.**
   Don't assume the rest of the suite is unaffected — diff the relevant sections (same discipline
   as Step 4) and confirm each affected case's verdict still holds. Record this as a dated
   "re-verification" note at the end of `hr-agent-eval-results.md` rather than silently editing old
   verdicts without a trace.

## Step 7: Flag runtime-feasibility limits

If the requirement asks for something that needs a multi-step decision before an action — e.g.,
"search the knowledge base and only create a case if nothing relevant was found" — check whether
the agent's actual runtime can execute that check at the right point. A Declarative Agent, for
example, has no supported in-topic knowledge-retrieval node (`SearchAndSummarizeContent` is
confirmed unsupported there), and once a topic's own scripted dialog takes over a turn, no further
orchestrator-level decision happens until that topic ends.

If the runtime can't reliably execute the full multi-step check, say so plainly in your output:
the requirement can only be expressed as a single-turn trigger-level heuristic (e.g., a stronger,
better-placed description of when *not* to fire a bare request), not a guaranteed mechanism. Do not
silently write the requirement as if the gate will always hold — the maker needs to know it's a
best-effort text instruction, not an enforced rule, so they can decide whether that's acceptable or
whether it needs a different architectural fix (e.g., a new retrieval-capable action, once one
becomes available for the runtime).

## Step 8: Present and get approval

Before calling the curation finished, show the maker:
- The diff (or the specific sentences changed, for a small edit).
- The final character count and how much margin it has.
- The new/updated eval cases and their verdicts.
- Any runtime-feasibility caveat from Step 7.

Do not apply the change to the maker's live agent yourself — hand back the verified text for them
to paste, and the updated eval files for the repo.

## Output

- The curated instructions text (file update if sourced from a repo file; a plain text block ready
  to paste if sourced from a pasted live version).
- A short design-doc note (what changed, why, and any grounding/runtime caveats) if this is a
  repo-tracked change.
- Updated `hr-agent-eval-cases.md` and `hr-agent-eval-results.md`.
- The final character count, confirmed under budget with margin.
