# Generate Evaluation Test Sets Skill (catalogue-grounded)

Generate Copilot Studio evaluation test sets for the scenario/goal(s) a user
names, grounded in the **scenario catalogue bundled with this skill** — no
configured agent required. Generation is catalogue-grounded; this kit's host
provides shared presentation, method validation, export, and action handling.
Other hosts must supply equivalent contracts when reusing the generator.

It produces two artifacts per set from the same cases:
- **`.mcs.yml`** — the Copilot Studio-native EvaluationSet/EvaluationData format
  (importable and pushable by the host).
- **`.csv`** — a shareable / importable copy for informal sharing or seeding
  another agent.

> **Scope of this skill.** It only *generates* test-set artifacts. Whether/where
> they are pushed or deployed is the **host's** concern, not this skill's — this
> skill never pushes. Run and Request Review delegate to the host's selected-set
> deployment flow after the user chooses an action.

## Rules

- Read `src/skills/evaluations/experience-contract.md` for shared coverage copy,
  Compare Meaning admission, complete case presentation, and four maker actions.
- This feature generates single-response `EvaluationData` only. Explain an
  explicit multi-turn request is unsupported before writing files; offer an
  explicit single-response alternative, never silently flatten or omit turns.
- The **scenario catalogue** bundled with this skill is **data only** — read it
  before you classify, expand, or write any case, and never introduce a category,
  scenario, connector, persona, or field it does not define. In this kit the
  catalogue file is `ess-catalogue.md`, co-located with this `SKILL.md`; to reuse
  the skill for another domain, replace that file — do not edit this behaviour.
- Generate **only** for the scenario/goal(s) the user names — never a whole
  "configured", default, or catalogue-wide set.
- ALWAYS produce **both** artifacts (`.mcs.yml` and `.csv`) from the same
  in-memory cases so they never drift.
- Write Copilot Studio-native artifacts to the host's eval output folder. In
  this kit that is `workspace/evaluations/{slug}/`. Write shareable CSV copies
  to `workspace/evaluations/exports/`.
- **TRACK PROGRESS**: Use the todo list tool to track your progress. Create a
  todo list at the start, mark each step in-progress as you begin it, and
  completed when done.
- Never expose internal terminology (skills, SKILL.md, catalogue files, routing)
  to the user — follow the host's user-facing tone rules.

---

## Step 1: Read the scenario catalogue

**This is mandatory and must be your first action. Read the bundled scenario
catalogue (`ess-catalogue.md` in this folder) in full before you classify,
expand, or write a single case — do not proceed on memory or a partial skim.** It
is the single source of truth for what the target agent can do. From it you will
use, by role (not by hard-coded name):

- The **scenario/category map** and the **representative scenarios** listed under
  each category.
- The **outcome-level scenarios / goals** for phrasing expected behaviour.
- The **connector/grouping** information only to understand which scenarios belong
  together — never put a connector or backend system name into a test case.

Do not invent scenarios, fields, or categories the catalogue does not list. Where
the catalogue describes a family only at a high level, expand it using the
sub-scenarios it names for that family (for example, a profile-read family that
names Employee ID, Job Details, Company Code, Cost Center, Hire Date, and so on →
generate one positive per named sub-scenario).

## Step 2: Determine scope (which goals/scenarios)

Before generating a new set, discover existing workspace/current-agent sets
with `python scripts/evaluation_review.py --list-all` (use `--query "{user text}"`
for an explicitly named set). Discover actual EvaluationSet parents, including
arbitrary slugs and overflow sets, not a fixed category-folder list.
Show matching sets with source and case count. For a returning maker offer:

- **Edit this existing set**
- **Add test cases to this set**
- **Create a new set**
- **Keep it unchanged**

Wait for an explicit selection. Edit/add carries the exact folder/source and
action to `src/skills/evaluations/update/SKILL.md` and stops this generator.
Never choose a fuzzy/same-name match or regenerate the set to enable editing.
Keep/cancel does not mutate, export, or deploy anything.

Generate evals **only** for the scenario/goal(s) the user specifies.

- If the user **named one or more goals/scenarios/categories** (for example
  "HR policy lookup", "IT ticketing", "manager scenarios"), that is the scope —
  map each to its catalogue family and generate for those only.
- If the user named nothing, ask one short question and wait for the answer:

  > Which scenario or goal should I generate tests for? For example
  > **HR policy lookup**, **IT ticketing**, or **manager scenarios**.

Never guess the domain from unrelated wording, and never expand to scenarios the
user did not explicitly ask for.

## Step 3: Confirm the test set name(s)

Always propose a name and let the user confirm or override — never invent a final
name silently, and never force them to type one from scratch.

- **One goal/scenario** → the name is obvious from the goal. Confirm it:

  > I'll save this as **{Goal name}**. Want a different name?

- **Multiple goals/scenarios** → propose one set per goal with smart default
  names, and offer to combine:

  > I'll create {N} sets — **{Goal A}**, **{Goal B}**, … . Prefer one **combined**
  > set instead? And any names you'd like to change?

Whatever the user confirms becomes BOTH the `.mcs.yml` EvaluationSet
`displayName` AND the `.csv` file slug, so the two artifacts always match. The
folder/file slug is the confirmed name reduced to `[a-z0-9-]` (fallback
`evalset`).

Wait for the user's confirmation before generating files.

Check the confirmed destination against the discovered sets before reusing a
slug. On collision, offer the same edit/add/keep choices or a distinct new name.
Explicit replacement requires showing affected cases and obtaining approval;
preserve existing deletion restrictions. It is never the default.

After scope/name confirmation, render **Before generating cases** from
`src/skills/evaluations/experience-contract.md` once, before Step 4.

## Step 4: Generate cases per confirmed set

For each confirmed set, expand its family into sub-scenarios (from Step 1) and
generate cases so the set looks identical to any other Copilot Studio eval set.

**Positives — one per grounded sub-scenario.** For every distinct readable field,
writable field, operation, or data topic the catalogue lists for the family,
write one positive. Never collapse a multi-field family into a single row. If a
family's full positive set exceeds **21**, split into multiple sets (each its own
folder with its own 2 boundary + 2 negative) rather than trimming.

**Exactly 2 boundary + 2 negative per set** (distinct, not paraphrases):
- **Boundary** — near-scope, typo'd, abbreviated, or very short input the agent
  should still handle (e.g. "empolyee ID", "comp ratio", "pto bal", "tkts").
- **Negative** — use two distinct behaviors:
  - **Outside this scenario, valid ESS:** ground the prompt in a different
    catalogue scenario. The expected response should route to or support that
    capability, not refuse it merely because it is outside this evaluation goal.
  - **Outside the ESS catalogue:** choose a genuinely unrelated domain, varying
    examples across sets (for example entertainment trivia, consumer shopping,
    recipe planning, personal investing, or schoolwork), and expect an
    appropriate limitation or redirection.
  Privacy boundaries ("show me John's salary"), write-on-read-only requests
  ("change my employee ID"), and cross-domain mixing remain separate negative
  behaviors and must not be relabeled as out of scope.

Do not use travel booking as the default unsupported example: travel can be a
valid employee-service scenario when configured. The two negatives must use
different behavior classes and different domains; never repeat one canned
off-domain prompt across generated sets.

**Utterance-type mix (apply across all case types):** each set needs both
natural-language utterances (full sentences a real employee would type) and
keyword utterances (short, sparse — "open tkts"). Never write two
natural-language paraphrases of the same intent — they inflate redundancy without
adding coverage. If a family gets two positives, make one natural language and
one keyword.

**Expected-response quality rules** (tuned for the CompareMeaning grader):
- Describe observable, user-facing behaviour — WHAT the agent does, not HOW or
  WHERE. e.g. "The agent should display the user's employee ID."
- **Never** name a backend system (ServiceNow, Workday, SuccessFactors, SAP,
  Dataverse) or a connector, even if the catalogue mentions it.
- For write scenarios, describe gather → confirm → submit behaviour, never a
  completed/confirmed change in a single turn.
- For refusals, give a plain-English reason plus a safe next step.
- Do not fabricate record values, IDs, statuses, or entitlements — use a
  `<placeholder>` when a concrete value would be needed.

## Step 5: Write the files (`.mcs.yml` + `.csv`)

Write to the host's eval output folder (in this kit,
`workspace/evaluations/{slug}/`; create it if missing).

**`.mcs.yml` — Copilot Studio-native.**

Parent EvaluationSet (one per set):

```yaml
kind: EvaluationSet
displayName: "{Confirmed set name}"
graders:
  - kind: CompareMeaningGrader
    threshold: 0.7
```

Child EvaluationData (one per case):

```yaml
kind: EvaluationData
rows:
  - source: Imported
    expectedOutput: "The expected user-facing behaviour"
    input: "The user's test prompt"

extensionData:
  displayOrder: "{timestamp}"
```

- Parent file: `{output}/{slug}/{slug}.mcs.yml`
- Child files: `{output}/{slug}/{short-case-slug}.mcs.yml`
- `displayOrder` is epoch-milliseconds; increment by 1 per case to preserve order.
- Copilot Studio caps a set at **100 cases** — if a set exceeds it, split into
  `{slug}-2/`, `{slug}-3/`, each with exactly one CompareMeaningGrader and the
  same threshold. The stricter 21-positive family split in Step 4 still applies.

**`.csv` — shareable / importable copy.** Write one CSV per set under
`workspace/evaluations/exports/` with these exact columns (the format Copilot
Studio's Evaluate tab imports). Create the `exports/` folder when needed:

```csv
Prompt,Expected response,Test Method Type,Passing Score
```

- `Test Method Type` = `CompareMeaning` for every row.
- `Passing Score` = `70` (the 0–100 equivalent of the 0.7 mcs.yml threshold).
- File name: `{YYYYMMDD}_{Confirmed_Set_Name}.csv`, with spaces and
  punctuation in the confirmed display name replaced by underscores (for
  example, `20260724_Workday_ProfileUpdates.csv`).
- Use `evaluation_csv.generate_set_csv`, also invoked by the presentation
  helper, for RFC-4180 export, formula-injection protection, actual filename
  collision handling, and method admission before old-export cleanup.
  Do not construct a second CSV writer.
- For CSV-only synchronization, use the `evaluation_csv.py --evaluation-folder`
  command from the shared **CSV synchronization** contract and the returned
  `csv` path. Never bypass strict feature admission.

Validate proposed parent/case documents with `validate_evaluation_documents`
from `evaluation_method_policy` before writing. Every row needs a meaningful
input and expected response; a refusal/clarification is a valid expectation,
not an excuse for a blank assertion. Generate BOTH artifacts for every set
from the same cases. Then run admission for each written folder:

```text
python scripts/evaluation_method_policy.py --evaluation-folder "{set-folder}"
```

Stop on failure without replacing a previous valid export or claiming readiness.

## Step 6: Present the generated preview before validation

Before invoking quality validation, follow **Generated-case preview** in
`src/skills/evaluations/experience-contract.md`. Use
`evaluation_presentation.py --evaluation-folder "{set-folder}" --list-rows`,
classify actual rows with source context, and render the complete two-column
Prompt / Expected Response tables through the helper. Preserve row identities,
including duplicate inputs with different assertions, and the real CSV link.
The CSV is provided for preview and sharing.

This preview is mandatory before any validator progress or quality report.
Catalogue scenarios must not be described as verified configured capabilities.
Do not wait for quality validation before showing it. Continue to Step 7 unless
the user explicitly requests an edit; do not show a competing action menu yet.

## Step 7: Quality validation

Invoke `runSubagent` for each generated set. Its first action must be to read
`src/skills/evaluations/validate/SKILL.md`. Pass all generated `.mcs.yml` file
paths and the exact set folder, and require it to run:

```text
python scripts/evaluate_evals.py --evaluation-folder "{set-folder}"
```

Wait for the validation report before continuing. Do not score the set in the
parent conversation and do not skip validation because this set was routed
through catalogue-grounded generation rather than topic-grounded generation.
Do not show a separate validation progress message or preamble after the
generated-case preview.

After the subagent returns, display its **Post-generation quality report**
scorecard verbatim. Preserve the exact opening paragraph, overall line,
case-count line, eight score rows, optional improvements, local-only warning,
next-steps heading, and four closing questions. Do not add a table, filename
callout, summary, or second preamble.
The generated-case tables from Step 6 appear once only; never repeat them during
or after quality validation unless a fix changed specific rows, in which case
show only those changed rows.

Follow the quality gate and fix flow in
`src/skills/evaluations/quality-fix-flow.md`. For this skill, the "review step"
means Step 8 below.

Do not proceed until validation has returned and any selected fixes are
complete. When validation or a fix changes a YAML case, regenerate the CSV from
the final YAML case list so both representations remain synchronized.

## Step 8: Present validated results

Re-read final YAML when fixes changed content; synchronize CSV and show only the
rows whose prompt or expected response changed, plus the current CSV link. Never
repeat an unchanged generated-case table. Keep the complete compact quality
report separate.
Use the shared local-only reminder: quality approval or a copied staging folder
does not make the set available to another authorized reviewer.

## Step 9: Offer next steps

Follow **Four maker actions** in
`src/skills/evaluations/experience-contract.md`. This closing question is
mandatory. Carry exact selected context to update Flow R1 for Request Review,
run Flow A for Run, or update for edit/add. Run and Request Review own required
promotion/push through `src/skills/evaluations/deployment-flow.md`; do not push
here or require a separate command. Explicit standalone push remains supported.
Repeat quality review returns to these choices without deployment.
