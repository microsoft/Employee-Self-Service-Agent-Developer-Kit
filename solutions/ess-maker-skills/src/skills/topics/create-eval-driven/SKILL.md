# Create a Simple Eval-Driven Topic

Create a topic from an approved eval contract. The same contract drives topic
generation, native Copilot Studio eval creation, static validation, and the
runtime-validation handoff.

This is the default topic path used by `/create`. It accepts:

1. A scenario YAML file that follows `eval-scenario.schema.json`.
2. Existing Copilot Studio eval YAML files.
3. A plain-language description of the intended employee outcome.

This PR supports only Phase 1 topics with no external-system call:
informational responses, clarification, routing, and handoff.

## Rules

- Read `.local/config.json` first and use the active agent folder.
- Read `src/skills/topics/create/SKILL.md` for topic-authoring rules and patterns.
- If the request needs Workday, ServiceNow, SAP, a connector, a cloud flow, or
  another external system, stop this wrapper and follow
  `src/skills/topics/create/SKILL.md` unchanged. Do not create an eval-driven
  scenario or eval files for that request in this PR.
- The base skill's no-terminal rule applies to topic authoring. This wrapper may
  run only the validation, checkpoint, materialization, dry-run, push, and
  telemetry commands listed below.
- Do not create a topic until the user approves the eval contract.
- Treat the approved scenario as the source of truth. Do not ask again for
  information already present in it.
- Keep the existing safety gates: checkpoint, diagnostics, topic review, dry
  run, explicit push confirmation, and verification.
- Store generated scenario contracts under
  `.local/eval-driven/scenarios/{scenario-id}.scenario.yaml`. Do not store them
  inside the agent folder.
- A topic is not complete merely because files were generated. Static
  validation and push must succeed. Runtime completion is reported only after a
  runtime validator returns results.

## Step 1: Identify the input

If the user already supplied a path or selected files, inspect them.

### Scenario YAML

Treat a YAML object with `schemaVersion`, `intent`, and `evals` as a scenario.
Copy it to the `.local/eval-driven/scenarios/` location only after approval.

### Existing native eval files

Native eval files do not normally contain enough topic-design information.
Collect only the missing fields needed by the scenario contract: scenario ID,
topic name, topic intent, topic type, persona, and approved source content when
required.

Then normalize the selected files deterministically:

```text
python scripts/eval_scenario.py normalize "{selected-eval-path}" --id "{scenario-id}" --name "{name}" --intent "{intent}" --topic-type "{topicType}" --persona "{persona}" --output ".local/eval-driven/drafts/{scenario-id}.scenario.yaml"
```

For an informational topic, also pass:

```text
--source-content "{approved source content}"
```

The command:

- Reads `EvaluationSet`, `EvaluationData`, and `MultiTurnEvaluationCase` files.
- Uses the parent set's `CompareMeaningGrader.threshold` when available.
- Converts single-turn rows and multi-turn activities into scenario evals.
- Infers categories using stable filename and expected-output rules.
- Preserves every source eval path in `references`.
- Fails on malformed files, unsupported kinds, or missing required fields.

Read the normalized draft and present it for approval. Do not manually
reconstruct eval rows when the normalization command can process them. Write
the approved version to `.local/eval-driven/scenarios/` only after approval.

### Plain-language request

Draft a scenario from the user's request. For Phase 1, include at minimum:

- One `directTrigger` case
- One `paraphrase` case
- One `nonTrigger` case
- Any clarification, missing-input, cancellation, or handoff case required by
  the intended conversation

Use realistic employee language. Expected outputs must describe observable
behavior, not implementation details.

For informational topics, require the approved response or source link in
`sourceContent`. Do not invent policy or guidance content.

Infer `topicType` as `informational`, `clarification`, `routing`, or `handoff`.
Do not ask the user to understand this internal field.

## Step 2: Present and approve the eval contract

Show a concise review:

| Field | Value |
|-------|-------|
| Topic | `{name}` |
| Intended outcome | `{intent}` |
| Topic type | `{topicType}` |
| Phase | `{phase}` |
| Persona | `{persona}` |
| Required evals | `{count}` |

Then show every eval:

| # | Category | Input or condition | Expected behavior | Required |
|---|----------|--------------------|-------------------|----------|

Ask the user to **approve** or **edit** the contract. Do not generate the topic
until the user explicitly approves it.

After approval:

1. Write the scenario YAML to
   `.local/eval-driven/scenarios/{scenario-id}.scenario.yaml`.
2. Validate it:

   ```text
   python scripts/eval_scenario.py validate ".local/eval-driven/scenarios/{scenario-id}.scenario.yaml"
   ```

3. If validation fails, fix the contract and present the changed fields for
   approval again.

## Step 3: Run dependency gates

Evaluate every `dependencyChecks` row that blocks generation.

Also enforce that the scenario is Phase 1, has no integration, and includes
approved `sourceContent` when `topicType` is `informational`.

If a required dependency is missing, stop before writing topic or eval files.
Explain the blocker and the next action from the scenario's `behavior`.

## Step 4: Generate the topic

Use the approved scenario instead of the interactive discovery steps in
`src/skills/topics/create/SKILL.md`:

- `name` supplies the new topic identity.
- `intent`, direct-trigger inputs, and paraphrases supply trigger queries and
  the model description.
- `nonTrigger` and boundary evals define when the topic must not run.
- `sourceContent` supplies informational responses.
- Multi-turn evals define conversation order, missing inputs, confirmation,
  correction, cancellation, and handoff behavior.
- Expected outputs define the required success, no-data, and error branches.

Follow the base topic skill's template-selection, neighbor-reading, authoring
invariants, file naming, and variable naming rules. Do not repeat its questions
unless the approved contract is genuinely incomplete.

Before changing files, run:

```text
python scripts/checkpoint.py "pre-eval-driven-create-{scenario-id}"
python scripts/emit_capability.py topic_create
```

Write the new topic to:

`{agent.folder}/topics/{TopicName}.mcs.yml`

## Step 5: Generate native evals and the runtime handoff

After the topic file exists, run:

```text
python scripts/eval_scenario.py materialize ".local/eval-driven/scenarios/{scenario-id}.scenario.yaml" --agent-folder "{agent.folder}" --topic-file "{agent.folder}/topics/{TopicName}.mcs.yml" --runtime-output ".local/eval-driven/{scenario-id}/runtime-manifest.json" --operation create
```

The command creates:

- Single-turn native `EvaluationSet` and `EvaluationData` files under
  `{agent.folder}/evaluations/eval-driven-{scenario-id}*/`.
- Native `MultiTurnEvaluationCase` files when the contract contains turns.
- `.local/eval-driven/{scenario-id}/runtime-manifest.json`, containing the
  topic path, every eval, stable eval IDs, required flags, thresholds, and
  native eval paths.

Condition-based rows are preserved in the runtime manifest but are not emitted
as native prompt evals because they require controlled backend state.

## Step 6: Run static validation

1. Check diagnostics across the full agent folder. Fix errors in newly created
   topic or eval files.
2. Run evaluation quality validation using
   `src/skills/evaluations/validate/SKILL.md` against the generated eval files.
3. Run the mandatory single-topic review from
   `src/skills/topics/review/SKILL.md` and show its full maker-facing report.
4. Run:

   ```text
   python scripts/push.py --dry-run
   ```

5. Show the new topic and eval files in the dry-run summary.

Do not proceed if generated YAML cannot be parsed. Topic-review findings remain
advisory and follow the existing fix-now or push-anyway flow.

## Step 7: Push and report

Ask for explicit confirmation, then run:

```text
python scripts/push.py
```

After success, report:

- Scenario contract path
- Topic path
- Generated native eval paths
- Runtime-manifest path

If no runtime pipeline is configured yet, state that static generation is
complete and the manifest is ready for the runtime-validation handoff. Do not
claim that runtime behavior passed.
