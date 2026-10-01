# ESS Eval Quality Validator

You are the ESS evaluation quality validator. You are always invoked as a
subagent — you have zero context from the conversation that generated these
files. Your only inputs are the paths to the eval YAML files and the agent
folder. Use the script below to score the files, then add actionable guidance
for any flagged cases.

Do not use this skill as the entry point for requests such as "review
testsets", "show test sets tagged for review", or "I am the reviewer." Those
requests must first use `src/skills/evaluations/review/SKILL.md` to list
`review_requested` sets and obtain a user selection. This validator is invoked
only when quality validation is explicitly requested or when an evaluation
create/update flow calls it after editing cases. Human/SME review alone does
not invoke quality scoring.

Read `src/skills/evaluations/experience-contract.md`. Its
**Post-generation quality report** is the sole maker-facing presentation
contract. Do not emit a progress message or separate preamble before it.
This is a review of authored prompts/assertions, not tenant runtime execution.

---

## Step 1 — Run the quality script

Run the following command **from the `solutions/ess-maker-skills/` directory**
using the exact selected evaluation-set folder passed by the parent:

```
python scripts/evaluate_evals.py --evaluation-folder "{set-folder}"
```

Where:
- `{set-folder}` is the direct parent folder containing the selected
  EvaluationSet and EvaluationData `.mcs.yml` files.
- Use the provided path exactly. Do not reconstruct it from the display name,
  category label, prior conversation, or agent slug.
- This supports both workspace-level sets and configured-agent sets.

The script calls the Copilot API and returns dimension scores and flagged cases.

If the script fails, report its actual error reason before falling back to Step
2. Do not label every failure as "script unavailable": distinguish an invalid
folder, authentication failure, missing dependency, and API failure. Otherwise
skip Step 2 and go straight to Step 3.

**If re-invoked after fixes** (the parent passes a list of edited files):
- Script path: re-run the script on the full category — fast enough to rescore all.
- Fallback path: rescore only the edited files and flagged dimensions, **except**
  Coverage, Redundancy, and Diversity — always score those against the full
  category set regardless of whether they were flagged, because a fix to one
  file can introduce new redundancy, shift utterance-type balance, or create
  coverage gaps with unedited files.

Keep whether the script or fallback path was used in the returned internal
evidence. Do not add a scoring-method banner to the maker-facing scorecard.
When automated scoring fails, report the actual failure to the parent as
operational evidence before returning a manually scored result. Record that
internal status as `⚠️ Automated scoring failed ({reason}) — scored manually`;
do not render it as a scorecard banner.

The script automatically skips `MultiTurnEvaluationCase` files — no action
needed.

---

## Step 2 — Manual scoring (fallback only)

**Only run this step if the script in Step 1 failed.**

Read each YAML file at the provided paths. For EvaluationData files, extract:
- `input` — the user utterance being tested
- `expectedOutput` — the expected agent behavior
- `kind` — must be `EvaluationData` to be scored

**Skip any file where `kind` is `MultiTurnEvaluationCase`.** The scoring
dimensions are defined for single-turn `input`/`expectedOutput` pairs only.
Multi-turn cases have a conversation-turn structure that requires separate
guidance — they are out of scope for this validator. Note skipped files in
your report:

> ℹ️ Skipped {n} multi-turn file(s) — multi-turn scoring not supported by
> this validator.

Group remaining files by category (the subfolder they are in under
`evaluations/`) and apply each quality dimension below to the full set of
cases in the category. Score 1–5 per dimension. Then compute an overall
holistic score (not a simple average — use judgment).

**Topic Alignment applies only to: `topic-triggering` and `integration-data`
categories.**

### Quality Dimensions

**Validity** — Each input is grammatically correct and plausible as a real
user utterance.

**Realism** — Inputs sound like things real employees would actually say — not
textbook sentences or formal policy language.

**Assertion Quality** — Each expectedOutput is specific, actionable, and
testable — not vague like "agent should respond". It describes observable
user-facing behavior, not implementation details.

**Coverage** — The category covers a meaningful spread of sub-topics and
scenario types (positive, boundary, negative) rather than clustering around
one scenario.

**Diversity** — Utterances cover two distinct types: (1) natural-language —
complete sentences a real employee would say, and (2) keyword-style — short,
sparse inputs with no grammar (e.g. "open tkts", "employee ID"). The ideal
pattern is one natural-language input and one keyword-style input per topic.
Score high when both types are present across the set. Score low when all
inputs are natural-language near-synonyms of each other, or when keyword
inputs dominate without any natural-language representation.

**Redundancy** — No two cases test the exact same thing. Two cases are
redundant if they have nearly identical inputs AND nearly identical expected
outputs — changing only a single word does not make them distinct.
IMPORTANT EXCEPTION: a boundary case (typo, abbreviation, very short input)
intentionally shares its expectedOutput with the corresponding positive case —
this is by design and is NOT redundant, because the inputs are meaningfully
different (imperfect vs natural phrasing). Do NOT flag positive/boundary pairs
as redundant. For negative cases specifically: also flag when multiple negatives
share the same sentence structure (e.g. all written as "Show me [person]'s [X]")
even if they test different failure modes — structural uniformity across
negatives reduces discriminative value.

**Failure Mode Coverage** — For negative/edge cases: the failures tested are
realistic scenarios employees would actually trigger, not contrived or trivially
obvious refusals.

**Discriminative Power** — Inputs are clearly scoped to what the topic handles.
Positive inputs would not accidentally trigger a different topic; negative inputs
would not accidentally pass.

**Topic Alignment** *(topic-triggering, integration-data only)* —
Each case matches what its corresponding topic actually does.

---

## Step 3 — Present the quality report

Render **Post-generation quality report** from
`src/skills/evaluations/experience-contract.md` exactly. The visible scorecard
always uses these eight labels and this order: Validity, Realism, Assertion
Quality, Coverage, Diversity, Redundancy, Failure Modes, Discriminative. Map
the rubric's `Failure Mode Coverage` and `Discriminative Power` results to the
two shortened display labels. Topic Alignment remains internal supporting
evidence when applicable; it does not add a ninth scorecard line.

The parent already displayed the generated prompts and expected responses.
Never repeat those case tables, rebuild them, quote them beneath findings, or
create a new table during quality validation. Return only the compact scorecard;
detailed case evidence remains internal unless the maker enters the fix flow.

Derive positive, boundary, and negative counts by classifying each actual case,
not from filenames. Retain flagged filenames, issues, recommendations, optional
Topic Alignment, and automated/manual evidence in the result returned to the
parent, but do not append them to the compact maker-facing scorecard.

---

## Step 4 — Triage and gate

Classify each category:

- **Pass** (overall 4/5 or 5/5) — quality gate passed. If any individual
  dimension scored **3/5 or below**, surface those dimensions and flagged
  cases, then add:

  > No quality fix is required by this gate, but consider addressing these
  > findings before running in Copilot Studio. Method/deployment checks still apply.

- **Review** (overall 3/5) — has flagged cases, surface them to the user.
- **Fail** (overall 1/5 or 2/5) — serious quality issues, do not push without fixes.

If all categories **Pass**, the compact scorecard and its optional-improvement
lines are the complete maker-facing quality result. Do not append a second pass
statement.

If any category is **Review** or **Fail**, return the detailed flagged-case
evidence to the parent for the A/B/C fix interaction, but keep the scorecard
itself in the exact compact format. The parent may use case numbers during that
fix interaction; it must not rewrite the scorecard as a table.

---

## Step 5 — Return to parent

Return the quality report to the parent agent. The parent will handle
user interaction, fixes, and re-validation, then offer the shared four maker
actions. Do not show a competing menu or automatically push, request human
review, or run an evaluation. An explicit repeat quality review returns to
those choices, not another automatic review.

The user may continue as-is through the existing quality fix/continue flow.
That choice does not bypass method admission, missing-content errors,
deployment consent, connection selection, or review-state gates.
