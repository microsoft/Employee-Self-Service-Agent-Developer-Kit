# Evaluate Skill — Generate Evaluation Test Sets

This skill guides the agent through generating Copilot Studio evaluation test
sets from the user's agent topics and pushing them directly to Copilot Studio
via Dataverse. Test cases are stored as `botcomponent` records with
`componenttype=19` in a parent→child hierarchy (EvaluationSet → EvaluationData).

## Rules

- ALWAYS read `.local/config.json` to get the agent folder name and slug.
- ALWAYS read all topic files in the agent folder to understand what the agent does before generating tests.
- Write evaluation files to `{agent.folder}/evaluations/` as `.mcs.yml` YAML files.
- Use the existing starter test sets in `src/examples/ess-samples/ESSEvaluationSamples/StarterTestSets/` as exemplar patterns for each test category.
- Follow the standard mutation pipeline: **checkpoint → write files → scan → dry run → push → verify**.
- **TRACK PROGRESS**: Use the todo list tool to track your progress through this skill's steps. Create a todo list at the start with all the steps, mark each in-progress as you start it, and mark completed when done.

---

## Step 1: Read Agent Context

1. Read `.local/config.json` to get `agent.folder` and `agent.slug`.
2. Read ALL topic files in `{agent.folder}/topics/` — every `.mcs.yml` file.
3. Classify each topic:

| Trigger type | Classification | Use in test generation |
|-------------|---------------|----------------------|
| `OnRecognizedIntent` with `triggerQueries` | **User-facing (trigger phrases)** | Generate TopicTriggering tests using actual trigger phrases + paraphrases |
| `OnRecognizedIntent` with `modelDescription` only (no `triggerQueries`) | **User-facing (AI-routed)** | Generate TopicTriggering tests using the model description to craft natural prompts |
| `OnConversationStart` | System | Skip |
| `OnRedirect` | System | Skip |
| `OnError` | System | Skip |
| `OnActivity` | System | Skip |
| `OnUnknownIntent` | System | Skip |
| `OnGeneratedResponse` | System | Skip |

4. For each user-facing topic, extract:
   - `triggerQueries` (if present) — these become test prompts
   - `modelDescription` — describes what the topic does (use for expected response and for generating natural-language prompt variants)
   - First `SendActivity` message — can inform expected response
   - Whether the topic calls a workflow (`InvokeFlowAction`) — indicates integration data tests
   - Whether the topic calls a shared system topic (`BeginDialog`) — indicates template-config-based integration

5. Take note of special topics by display name or content:
   - Topics related to **sensitive content** → generate SensitiveTopic tests
   - Topics related to **emotional intelligence / empathy** → generate EQTopic tests
   - Topics related to **clarification / ambiguity** → generate AmbiguousTopic tests

---

## Step 2: Ask User About Scope

Present the user with options. Keep it simple — one question:

> I found **{N}** user-facing topics in your agent. I can generate evaluation
> test sets in these categories:
>
> | Category | Description | Tests based on |
> |----------|-------------|---------------|
> | **Topic Triggering** | Does each topic fire when it should? | Trigger phrases + paraphrases |
> | **Ambiguous Prompts** | Does the agent clarify vague requests? | Topics with overlapping intents |
> | **Responsible AI** | Does the agent refuse harmful requests? | Standard RAI guardrails |
> | **Sensitive Topics** | Does the agent escalate appropriately? | Sensitive-topic handling |
> | **Emotional Intelligence** | Does the agent respond with empathy? | Emotional tone scenarios |
> | **Integration Data** | Does the agent return correct data? | Topics calling external systems |
>
> Would you like a **full evaluation** (all categories), or would you prefer to
> pick specific categories?

Based on the user's answer:
- **Full evaluation**: Generate all categories that apply (skip categories where the agent has no matching topics, except RAI which is always generated)
- **Specific categories**: Generate only what the user picked
- **Specific topics**: If the user names specific topics, generate TopicTriggering tests for only those topics

Also ask: "Does your agent have **knowledge sources** loaded (documents, SharePoint, etc.)? This helps me decide whether to include knowledge-based tests."

---

## Step 3: Generate Evaluation YAML Files

### File format

Evaluation test sets are stored as `.mcs.yml` files in `{agent.folder}/evaluations/`.
There are two kinds:

**EvaluationSet (parent)** — one per test category. Defines the grader:

```yaml
kind: EvaluationSet
graders:
  - kind: GeneralQualityGrader
```

**EvaluationData (child)** — one per test case. Contains the test input and expected output:

```yaml
kind: EvaluationData
rows:
  - source: Imported
    expectedOutput: "The expected response text"
    input: "The user's test prompt"

extensionData:
  displayOrder: "{timestamp}"
```

For `GeneralQuality` tests (no expected response), omit `expectedOutput`:

```yaml
kind: EvaluationData
rows:
  - source: Imported
    input: "What can you help me with"

extensionData:
  displayOrder: "{timestamp}"
```

### Naming convention

- **Parent set file**: `evaluations/{category-name}.mcs.yml` (e.g., `evaluations/topic-triggering.mcs.yml`)
- **Child test case files**: `evaluations/{category-name}-{short-slug}.mcs.yml` (e.g., `evaluations/topic-triggering-check-ticket-status.mcs.yml`)

The `displayOrder` field is an epoch-milliseconds timestamp. Use the current time
and increment by 1 for each test case to preserve ordering.

### Categories to generate

Generate one EvaluationSet file + child EvaluationData files for each applicable category:

#### TopicTriggering

**For each user-facing topic:**
1. Include all existing `triggerQueries` from the topic YAML as test prompts
2. Generate 2-3 paraphrased variants (different wording, same intent)
3. Set `expectedOutput` to a semantic description of what the topic should do — derive from:
   - The topic's `modelDescription` (if present)
   - The first `SendActivity` message in the topic (if present)
   - A brief description of the topic's purpose based on its action chain

#### AmbiguousTopic

1. Read the exemplar: `src/examples/ess-samples/ESSEvaluationSamples/StarterTestSets/AmbiguousTopic-IT.csv`
2. Identify topics whose domains could overlap
3. Generate 10-15 vague prompts that could plausibly match multiple topics
4. `expectedOutput` should indicate the agent **asks a clarifying question**

#### RAI

**ALWAYS generate this category** — every agent needs RAI guardrails.

1. Read the exemplar: `src/examples/ess-samples/ESSEvaluationSamples/StarterTestSets/RAI-IT.csv` or `RAI-HR.csv`
2. Generate 15-20 test cases covering: security exploits, prompt injection, policy bypass, discrimination, data exfiltration
3. `expectedOutput` should indicate refusal

#### SensitiveTopic

**Only generate if** the agent has a sensitive-topics topic.

1. Read the exemplar: `src/examples/ess-samples/ESSEvaluationSamples/StarterTestSets/SensitiveTopic.csv`
2. Generate 10-15 prompts about sensitive workplace situations
3. `expectedOutput` should indicate escalation

#### EQTopic

**Only generate if** the agent has an emotional intelligence topic.

1. Read the exemplar: `src/examples/ess-samples/ESSEvaluationSamples/StarterTestSets/EQTopic-IT.csv` or `EQTopic-HR.csv`
2. Generate 10-15 prompts with emotional undertones
3. `expectedOutput` should acknowledge the emotion AND offer help

#### IntegrationData

**Only generate if** the agent has topics that call workflows or shared system topics.

1. For each integration topic, identify what data it retrieves
2. Generate prompts that request that data
3. Use `<placeholder>` format for real values the user must fill in

#### GeneralKnowledge

**Only generate if** the user confirmed they have knowledge sources.

1. Generate 10-15 general questions relevant to the agent's domain
2. Omit `expectedOutput` — use the `GeneralQualityGrader` auto-grading

---

## Step 4: Write Files and Push

### 4.1 — Checkpoint

Run `python scripts/checkpoint.py "before evaluation test set creation"` to save current state.

### 4.2 — Write evaluation files

Create the `evaluations/` folder inside the agent folder if it doesn't exist.
Write each EvaluationSet and EvaluationData file as described above.

### 4.3 — Dry run

Run `python scripts/push.py --dry-run` to preview what will be pushed. Confirm the
evaluation files are detected as new botcomponent records.

Show the user the dry run output and ask for confirmation.

### 4.4 — Push

Run `python scripts/push.py --yes` to push the evaluation test sets to Copilot Studio.
The push script handles two-pass ordering automatically: parent EvaluationSet records
are created first, then child EvaluationData records are linked via `parentbotcomponentid`.

### 4.5 — Show summary

Print a summary table:

> Here are your generated evaluation test sets:
>
> | Set | Test cases | Category |
> |-----|-----------|----------|
> | `topic-triggering` | 24 | Topic trigger accuracy |
> | `rai` | 15 | Responsible AI guardrails |
> | ... | ... | ... |
>
> ✅ Pushed to Copilot Studio. Open the
> [Evaluation tab](https://copilotstudio.microsoft.com/) to run evaluations.

---

## Step 5: Offer Next Steps

After pushing the test sets:

- "Would you like to **review or edit** any test cases?"
- "Would you like to **add more test cases** for a specific topic?"
- "Open the [Copilot Studio Evaluation tab](https://copilotstudio.microsoft.com/) to run the evaluations."
- "Type `/menu` to see other options."
