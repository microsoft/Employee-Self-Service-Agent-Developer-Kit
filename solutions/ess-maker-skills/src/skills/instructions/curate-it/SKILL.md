# Curate IT Agent Instructions

Update the IT agent's system instructions given a new or changed set of requirements, applying the
same support-resource/escalation discipline and verification rigor developed for the DuPont IT
agent, without a wholesale rewrite and without exceeding the character budget.

This skill produces a curated, verified, ready-to-paste instructions text plus an updated eval
record. It does not push to a live Copilot Studio environment — `push.py` has no path for an
agent's `instructions:` field today. A maker still pastes the result into the Instructions box by
hand.

## Inputs

- The current IT agent instructions: either a repo file (look first at
  `docs/plans/assets/dupont-ess-it-agent-prompt.md`) or text the maker pastes directly from the
  live Instructions box. Treat a pasted version as authoritative for this run even if it has
  drifted from the repo file — note the drift, don't silently overwrite it without telling the
  maker.
- A plain-language description of the new or changed requirement(s).
- Optional: a character budget. Default to 8000 if the maker doesn't state one.
- Optional: real tester/UAT feedback (pasted rows, a transcript, or screenshots) for Step 6b.

## Step 1: Read the current instructions

Read the full current instructions text before changing anything. If it's a repo file, read it
directly. If pasted, save it to a working file so later diffing has something to diff against.

If what you're given looks like it's drifted from the repo's maintained version, say so — don't
silently reconcile the two without the maker's say-so.

## Step 2: Confirm the resource-grounding model

The IT agent **does have a standing resource**: a general self-service portal (ServiceNow) it may
offer any time it's the right next step, without needing a retrieval to justify it. This is
different from a *named*, specific contact, case line, or escalation path, which still needs a
retrieval for the user's exact subject to have actually surfaced it. Hold this distinction fixed —
don't apply the stricter "only if retrieved" rule to the standing portal, and don't let the
standing portal's existence excuse naming a *specific* contact without grounding. If the new
requirement seems to add or change what counts as standing vs. named, confirm with the maker before
assuming.

## Step 3: Apply the escalation pattern for the new requirement

The IT agent's instructions should already have a dedicated "Support resources and escalation"
section covering these five rules, gated by one grounding sentence that governs all of them: **name
a specific contact, case line, or support path beyond the standing portal only when retrieval for
the user's exact subject actually returned it — never because it appeared in an unrelated article
or seems typical.**

1. **Opening request to contact support.** If the first message asks to open a case or how to
   contact IT, don't troubleshoot yet — confirm you can help and ask the user to briefly describe
   the issue, **unless the subject is already stated**, in which case proceed straight to rules 2-5
   for that subject. (This carve-out matters for the same reason it did for the HR agent — don't
   drop it.)
2. **In-scope, unanswerable.** If no retrieved source addresses the subject, say it could not be
   found and direct to the standing portal. Name a more specific contact or escalation path only if
   retrieval for that subject surfaced one.
3. **Broad or ambiguous request ("the Dupont problem").** The IT prompt likely already has a
   dedicated clarify-first mechanism elsewhere in the file (look for a "Core principle" and/or a
   "Clarifying questions" section) — this is the single most load-bearing, most-restated rule in
   this prompt historically, so **cross-reference it from the escalation section rather than
   restating it**, the same way the existing instructions already do. If the requirement actually
   changes clarify-first behavior itself, edit it where it lives, not in the escalation section.
4. **Out of scope.** If asked something outside IT (e.g., an HR question), say so and stop. Do not
   offer the standing portal or any other resource here — it is an IT-specific destination, and
   offering it to an out-of-scope question misrepresents it as relevant.
5. **Stuck after reasonable attempts.** If the user tried the suggested steps and explicitly asks
   for more help, and retrieval for that subject surfaced a specific resource, offer it. Otherwise
   fall back to the standing portal guidance — unlike HR, there is always a safe generic fallback
   available here.

Map the plain-language requirement onto whichever of these five it actually changes. Most
requirement changes will touch one rule, not all five.

## Step 4: Edit with minimal diff, then de-duplicate

Edit the instructions to reconcile the requirement into the *existing* structure — do not rewrite
sections that aren't affected. This prompt in particular has a documented history of the
clarify-first rule getting restated across multiple headed sections (a first pass removed 4 pure
restatements; a second pass later found a duplicated worked example and 2 more residual
restatements the first pass missed). Treat this as a known risk class for *any* edit to this file,
not just clarify-first changes — check whether your edit introduced a new restatement elsewhere in
the file, not just whether it did what it was asked.

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
  make room. Low-risk early targets: a revision-history note or changelog blockquote at the top of
  the file (meta-commentary, not an instruction — safe to remove outright), and verbose "list what
  to include" style sentences that can be tightened without losing content.
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
  truncation point in your text and compare the character offset to what the live counter shows,
  double-checking you matched the *last* occurrence of any repeated phrase, not the first) before
  guessing at a cause.

## Step 6: Update the paired eval sandbox

The IT agent's sandbox lives at `docs/plans/assets/dupont-kb-sandbox/` (synthetic KB articles), with
`docs/plans/assets/dupont-it-eval-cases.md` (scenario table) and
`docs/plans/assets/dupont-it-eval-results.md` (manual walkthrough verdicts).

### 6a. Cases for the new requirement

1. Add one or more new cases to `dupont-it-eval-cases.md` covering the requirement — include a
   positive case and, where it makes sense, a negative/edge case.
2. If the requirement is itself a regression fix (your own equivalent of the "ABBR"
   unrelated-document-leak bug), add a dedicated regression case.
3. If the synthetic KB sandbox doesn't have enough breadth to construct a realistic case, mark it a
   **SANDBOX GAP** rather than forcing a verdict, and recommend expanding the sandbox if the case
   matters for sign-off.
4. Walk every new case by hand against the updated instructions and record one of: **PASS**,
   **PREDICTED PASS** (the case is the exact real-world failure mode being fixed and the text now
   supports it, but it's worth confirming against the live agent), **SANDBOX GAP**, or **OUT OF
   SCOPE** (a platform/connector issue, like citation rendering or a KB-number/link mismatch, that
   no instructions wording can fix).

### 6b. Ingesting real UAT/tester feedback (IT-specific)

If the maker provides real tester feedback (pasted spreadsheet rows, a transcript, or a
screenshot of an actual deployed agent being tested — note it may be testing an older/different
prompt version than the one in the repo, confirm which before assuming the failure still applies):

1. For each failure the tester observed, map it onto the existing KB sandbox articles (or note that
   no matching article exists yet).
2. Classify it as one of:
   - A **genuine prompt gap** — the instructions, as currently written, would produce the same
     failure. Add an eval case for it and fix the instructions (back to Step 3).
   - A **sandbox-fidelity gap** — the real KB likely has more breadth than the synthetic sandbox
     (e.g., more sub-categories than our mocked articles cover), so the case can't be meaningfully
     evaluated here. Record it as a SANDBOX GAP with a note on what the sandbox would need.
   - A **platform/connector bug** — e.g., a citation showing the wrong source icon or a missing KB
     number. No prompt wording fixes this. Record it as OUT OF SCOPE and say so plainly rather than
     attempting a text fix that can't work.
3. Don't claim a fix resolves a UAT failure without re-walking that exact case against the updated
   text and showing the verdict — a plausible-sounding fix is not the same as a verified one.

### 6c. Re-verification

**Re-check every existing case whose expected behavior touches text you changed in Step 4.** Don't
assume the rest of the suite is unaffected — diff the relevant sections (same discipline as Step 4)
and confirm each affected case's verdict still holds. Record this as a dated "re-verification" note
at the end of `dupont-it-eval-results.md` rather than silently editing old verdicts without a
trace.

## Step 7: Flag runtime-feasibility limits

If the requirement asks for something that needs a multi-step decision before an action — e.g.,
"search the knowledge base and only create a case if nothing relevant was found" — check whether
the agent's actual runtime can execute that check at the right point. A Declarative Agent, for
example, has no supported in-topic knowledge-retrieval node (`SearchAndSummarizeContent` is
confirmed unsupported there), and once a topic's own scripted dialog takes over a turn, no further
orchestrator-level decision happens until that topic ends — a multi-turn condition like "ask again
if the narrowed request still spans sub-categories" is a trigger-level heuristic that depends on
the model generalizing a stated rule, not a guaranteed mechanism, unless a worked example exists for
that exact scenario in the prompt text.

If the runtime can't reliably execute the full multi-step check, say so plainly in your output. Do
not silently write the requirement as if the gate will always hold — the maker needs to know it's a
best-effort text instruction, not an enforced rule, so they can decide whether that's acceptable or
whether it needs a different architectural fix (e.g., a new retrieval-capable action, once one
becomes available for the runtime).

## Step 8: Present and get approval

Before calling the curation finished, show the maker:
- The diff (or the specific sentences changed, for a small edit).
- The final character count and how much margin it has.
- The new/updated eval cases and their verdicts, including any UAT-sourced findings from Step 6b.
- Any runtime-feasibility caveat from Step 7.

Do not apply the change to the maker's live agent yourself — hand back the verified text for them
to paste, and the updated eval files for the repo.

## Output

- The curated instructions text (file update if sourced from a repo file; a plain text block ready
  to paste if sourced from a pasted live version).
- A short design-doc note (what changed, why, and any grounding/runtime caveats) if this is a
  repo-tracked change.
- Updated `dupont-it-eval-cases.md` and `dupont-it-eval-results.md`.
- The final character count, confirmed under budget with margin.
