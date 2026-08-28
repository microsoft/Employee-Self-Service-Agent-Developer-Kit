# Generate Evaluation Test Sets Skill (catalogue-grounded)

Generate Copilot Studio evaluation test sets for the scenario/goal(s) a user
names, grounded in the **scenario catalogue bundled with this skill** — no
configured agent required. This is the portable, self-contained generator: it
depends only on files inside its own folder, so it can be reused elsewhere (for
example, dropped into a declarative agent) by swapping its catalogue for a
different domain.

It produces two artifacts per set from the same cases:
- **`.mcs.yml`** — the Copilot Studio-native EvaluationSet/EvaluationData format
  (importable and pushable by the host).
- **`.csv`** — a shareable / importable copy for informal sharing or seeding
  another agent.

> **Scope of this skill.** It only *generates* test-set artifacts. Whether/where
> they are pushed or deployed is the **host's** concern, not this skill's — this
> skill never pushes and has no dependency on any other skill.

## Rules

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
- **Negative** — a request the agent should refuse or deflect: out-of-scope
  ("book a flight to New York"), privacy boundary ("show me John's salary"),
  write-on-read-only ("change my employee ID"), or cross-domain mixing.

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
  - kind: GeneralQualityGrader

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
  `{slug}-2/`, `{slug}-3/`, each with its own parent using the same graders.

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
- Write it with a real RFC-4180 writer (Python `csv`, `quoting=csv.QUOTE_MINIMAL`).
  Prefix any cell starting with `=`, `+`, `-`, or `@` with an apostrophe
  (formula-injection guard). Keep every cell ASCII-only unless a target language
  was explicitly requested.

Generate BOTH artifacts for every set from the same cases in one pass.

## Step 6: Present the generated preview before validation

Before invoking quality validation, show the generated golden prompts grouped
under clear scenario headings. This preview is mandatory for catalogue-grounded
generation and must appear before any validator progress or quality report.

Use this shape:

> Based on your goals, here's the generated golden set. Tell me if you want to
> edit, remove, or add prompts.
>
> **{SCENARIO GROUP}**
>
> - "{Prompt 1}"
> - "{Prompt 2}"
>
> Generated - **{YYYYMMDD}_{Confirmed_Set_Name}.csv** ({N} prompts)
>
> The CSV is provided for preview and sharing. Quality validation will now
> check the source evaluation set.
>
> [{YYYYMMDD}_{Confirmed_Set_Name}.csv](workspace/evaluations/exports/{YYYYMMDD}_{Confirmed_Set_Name}.csv)

Group every generated prompt exactly once. Use user-facing goal/scenario names,
not internal catalogue or connector terminology. Do not wait for quality
validation before showing this preview. After showing it, continue directly to
Step 7 unless the user has explicitly requested an edit.

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

After the subagent returns, display its complete quality report directly to the
user, including the dimension table, scores, and flagged-case callouts. Do not
summarize or omit findings.

Follow the quality gate and fix flow in
`src/skills/evaluations/quality-fix-flow.md`. For this skill, the "review step"
means Step 8 below.

Do not proceed until validation has returned and any selected fixes are
complete. When validation or a fix changes a YAML case, regenerate the CSV from
the final YAML case list so both representations remain synchronized.

## Step 8: Present validated results

Show the user a summary and the downloadable link(s). Example:

> Here's your evaluation set{s}:
>
> | Set | Positive | Boundary | Negative | Total |
> |-----|----------|----------|----------|-------|
> | {Set name} | {n} | 2 | 2 | {n} |
>
> - Download / share: [{YYYYMMDD}_{Confirmed_Set_Name}.csv](workspace/evaluations/exports/{YYYYMMDD}_{Confirmed_Set_Name}.csv)
> - Copilot Studio-native copy: `{output}/{slug}/`
>
> Import the CSV from the Evaluate tab, reuse it in another agent, or ask your
> host to push the `.mcs.yml` copy once an agent is connected.

### Mandatory reviewer handoff reminder

Every final response from this workspace-only generation flow must include the
following reminder. Do not omit it because CSV generation or quality validation
completed:

> ⚠️ To make this test set available to an authorized judge or SME, it must be
> promoted to the configured agent and successfully pushed to Copilot Studio.
> The CSV and workspace files are currently local only. Say
> **"push {set name}"** when you are ready.

Continue showing this reminder in later generation/update summaries until a
successful push is confirmed. Copying the set into the configured agent's local
`evaluations/` folder is not sufficient; the Dataverse push is what makes it
retrievable by another user.

## Step 9: Offer next steps

- "Want me to **add another scenario** to this set, or generate a **different
  scenario**?"
- "Type `/menu` to see other options."
