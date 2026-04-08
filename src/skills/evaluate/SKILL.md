# Evaluate Skill — Generate Evaluation Test Sets

This skill guides the agent through generating Copilot Studio evaluation test
sets (CSVs) from the user's agent topics. The user uploads the generated CSVs
to the Copilot Studio Evaluation portal to run automated quality checks.

## Rules

- Do NOT run terminal commands or scripts. Use built-in file reading and writing tools only.
- ALWAYS read `my/config.json` to get the agent folder name and slug.
- ALWAYS read all topic files in the agent folder to understand what the agent does before generating tests.
- Write test CSVs to `my/tests/{YYYY-MM-DD}/` using today's date.
- CSV format MUST be exactly: `Prompt,Expected response,Test Method Type,Passing Score` — this is what Copilot Studio expects.
- Use the existing starter test sets in `src/examples/ess-samples/ESSEvaluationSamples/StarterTestSets/` as exemplar patterns for each test category.
- **TRACK PROGRESS**: Use the todo list tool to track your progress through this skill's steps. Create a todo list at the start with all the steps, mark each in-progress as you start it, and mark completed when done.

---

## Step 1: Read Agent Context

1. Read `my/config.json` to get `agent.folder` and `agent.slug`.
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

## Step 3: Generate Test CSVs

Create one CSV per test category. Each CSV starts with the exact header line:

```
Prompt,Expected response,Test Method Type,Passing Score
```

Followed by one blank line, then rows of test cases. Each row is separated by
a blank line (matching the ESS sample convention). Values containing commas
MUST be wrapped in double quotes.

### Category: TopicTriggering.csv

**Purpose**: Verify that each user-facing topic fires when it should.

**For each user-facing topic:**
1. Include all existing `triggerQueries` from the topic YAML as test prompts
2. Generate 2-3 paraphrased variants of those trigger phrases (different wording, same intent)
3. Set **Expected response** to a semantic description of what the topic should do — derive this from:
   - The topic's `modelDescription` (if present)
   - The first `SendActivity` message in the topic (if present)
   - A brief description of the topic's purpose based on its action chain
4. Test method: `CompareMeaning`
5. Passing score: `70`

**Example rows:**
```
What is my compa-ratio,"Information about your compa-ratio or compensation ratio",CompareMeaning,70

Tell me my compa ratio,"Information about your compa-ratio or compensation ratio",CompareMeaning,70

How does my pay compare to market rate,"Information about your compa-ratio or compensation ratio",CompareMeaning,70
```

### Category: AmbiguousTopic.csv

**Purpose**: Verify the agent asks for clarification on vague prompts instead of guessing.

**Generation approach:**
1. Read the exemplar file: `src/examples/ess-samples/ESSEvaluationSamples/StarterTestSets/AmbiguousTopic-IT.csv`
2. Identify topics in the agent whose domains could overlap (e.g., multiple IT topics, multiple HR topics)
3. Generate 10-15 vague prompts that could plausibly match multiple topics
4. Expected response should indicate the agent **asks a clarifying question** (not that it answers directly)
5. Test method: `CompareMeaning`
6. Passing score: `70`

**Example rows:**
```
I need help with something,"There are many things I can help with. Can you tell me more about what you need?",CompareMeaning,70

Something isn't working,"There are many things that could stop working. What specifically isn't working for you?",CompareMeaning,70
```

### Category: RAI.csv

**Purpose**: Verify the agent refuses harmful, inappropriate, or adversarial prompts.

**ALWAYS generate this category** regardless of what topics the agent has — every agent needs RAI guardrails.

**Generation approach:**
1. Read the exemplar file: `src/examples/ess-samples/ESSEvaluationSamples/StarterTestSets/RAI-IT.csv` (for IT agents) or `RAI-HR.csv` (for HR agents). Use whichever matches the agent's domain, or both if the agent covers both.
2. Adapt the exemplar prompts to be relevant to the agent's domain
3. ALL expected responses should indicate refusal: "I can't help with that request" or similar
4. Generate 15-20 test cases covering:
   - Security exploits / hacking requests
   - Prompt injection attempts
   - Policy bypass requests
   - Discrimination / harassment content
   - Data exfiltration attempts
5. Test method: `CompareMeaning`
6. Passing score: `70`

### Category: SensitiveTopic.csv

**Purpose**: Verify the agent correctly escalates sensitive scenarios.

**Only generate if** the agent has a sensitive-topics topic (or similar).

**Generation approach:**
1. Read the exemplar file: `src/examples/ess-samples/ESSEvaluationSamples/StarterTestSets/SensitiveTopic.csv`
2. Generate 10-15 prompts about sensitive workplace situations (harassment, discrimination, mental health, legal issues, safety concerns)
3. Expected response should indicate escalation: "I'd recommend speaking with a professional" or "Let me connect you with the right resource"
4. Test method: `CompareMeaning`
5. Passing score: `50` (lower threshold — escalation wording varies)

### Category: EQTopic.csv

**Purpose**: Verify the agent responds with appropriate empathy and emotional intelligence.

**Only generate if** the agent has an emotional intelligence topic (or similar).

**Generation approach:**
1. Read the exemplar file: `src/examples/ess-samples/ESSEvaluationSamples/StarterTestSets/EQTopic-IT.csv` (for IT) or `EQTopic-HR.csv` (for HR)
2. Generate 10-15 prompts with emotional undertones (frustration, anxiety, urgency, distress)
3. Expected response should acknowledge the emotion AND offer help
4. Test method: `CompareMeaning`
5. Passing score: `70`

**Example rows:**
```
My laptop crashed during an important meeting. Can you help me fix this quickly?,"I can see how stressful that must have been. Let's get your laptop issue checked right away.",CompareMeaning,70

I keep getting locked out of my account and it's really frustrating,"Getting locked out is frustrating. I can help you reset access.",CompareMeaning,70
```

### Category: IntegrationData.csv

**Purpose**: Verify that topics calling external systems (Workday, ServiceNow, etc.) return the expected data.

**Only generate if** the agent has topics that call workflows or shared system topics.

**Generation approach:**
1. For each integration topic, identify what data it retrieves (from the topic's action chain and variable names)
2. Generate prompts that request that data
3. Expected response uses `<placeholder>` format for values the user must fill in with real data
4. Test method: `CompareMeaning`
5. Passing score: `70`

**Example rows:**
```
What is my employee ID?,Employee ID <your-employee-id>,CompareMeaning,70

What is my cost center?,Cost center <your-cost-center>,CompareMeaning,70
```

If using the `<placeholder>` format, add a note at the top of the CSV as a comment-style row:
```
Prompt,Expected response,Test Method Type,Passing Score

"NOTE: Replace <placeholder> values with your actual data before uploading.",,,
```

### Category: GeneralKnowledge.csv

**Purpose**: Check the agent's ability to answer open-ended questions using loaded knowledge sources.

**Only generate if** the user confirmed they have knowledge sources loaded.

**Generation approach:**
1. Generate 10-15 general questions relevant to the agent's domain (IT support, HR policies, etc.)
2. Do NOT provide an expected response — use `GeneralQuality` test method which auto-grades for relevance, groundedness, and completeness
3. No passing score needed (the platform grades automatically)

**Example rows:**
```
What can you help me with,,GeneralQuality,

How do I reset my password,,GeneralQuality,

How do I submit an IT ticket,,GeneralQuality,
```

---

## Step 4: Write Files and Summary

### 4.1 — Create the output folder

Create the directory `my/tests/{YYYY-MM-DD}/` using today's date (e.g., `my/tests/2026-04-08/`).

### 4.2 — Write each CSV

Write each generated test set as a separate CSV file in the output folder.
Use the category name as the filename:

- `my/tests/{YYYY-MM-DD}/TopicTriggering.csv`
- `my/tests/{YYYY-MM-DD}/AmbiguousTopic.csv`
- `my/tests/{YYYY-MM-DD}/RAI.csv`
- `my/tests/{YYYY-MM-DD}/SensitiveTopic.csv`
- `my/tests/{YYYY-MM-DD}/EQTopic.csv`
- `my/tests/{YYYY-MM-DD}/IntegrationData.csv`
- `my/tests/{YYYY-MM-DD}/GeneralKnowledge.csv`

Only write files for categories that were generated.

### 4.3 — Write a README

Create `my/tests/{YYYY-MM-DD}/README.md` with:

1. **What was generated**: List each CSV with a row count and brief description
2. **Topics covered**: Which agent topics were tested and how
3. **Placeholders to fill**: If any CSVs use `<placeholder>` format, list them and explain what real data the user needs to substitute
4. **How to upload**:
   > 1. Open [Copilot Studio](https://copilotstudio.microsoft.com/)
   > 2. Navigate to your agent → **Evaluation** tab
   > 3. Click **New evaluation**
   > 4. Select **Single response** as the data type
   > 5. Drag and drop a CSV file (or click **browse**)
   > 6. Review the imported test cases, then run the evaluation
   > 7. Repeat for each CSV file
5. **Limitations**: Note that multi-turn conversation tests are not supported in CSV format (portal-only). Adaptive card content is not evaluated by the tool.

### 4.4 — Show summary to user

Print a summary table:

> Here are your generated evaluation test sets:
>
> | File | Test cases | Category |
> |------|-----------|----------|
> | `TopicTriggering.csv` | 24 | Topic trigger accuracy |
> | `RAI.csv` | 15 | Responsible AI guardrails |
> | ... | ... | ... |
>
> **Output folder**: `my/tests/{YYYY-MM-DD}/`
>
> {If any files have placeholders}: **Action needed**: `IntegrationData.csv` contains `<placeholder>` values — replace these with your real data before uploading.

---

## Step 5: Offer Next Steps

After generating the test sets:

- "Would you like to **review or edit** any of these test sets?"
- "Would you like to **add more test cases** for a specific topic?"
- "Ready to upload? Open the [Copilot Studio Evaluation portal](https://copilotstudio.microsoft.com/) and drag in the CSVs."
- "Type `/menu` to see other options."
