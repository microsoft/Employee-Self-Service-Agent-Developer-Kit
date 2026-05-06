# Create Topic Skill

This skill guides the user through creating a new Copilot Studio topic.

## Rules

- Do NOT run terminal commands or scripts. Use built-in file reading and writing tools only.
- ALWAYS read existing topic files in the user's agent folder (`{agent.folder}/topics/`) as schema examples before generating any YAML.
- ALWAYS read `my/config.json` to get the agent folder name and schema name.
- Write the new topic file to `{agent.folder}/topics/{TopicName}.mcs.yml`.
- After writing the file, check for errors using the diagnostics tool on the new file.
- **TEMPLATE CONFIG IS THE DEFAULT**: For any scenario that calls ServiceNow or Workday, use the **Template Config + Shared Flow** pattern. This is the official ESS extensibility pattern. The topic calls the existing shared system topic (e.g., `ServiceNowHRSDSystemGetCommonExecution`), which invokes the shared orchestrator flow. Do NOT create standalone cloud flows for these connectors.
  - ALWAYS read `src/reference/ess-docs/customization/customize.md` when the scenario involves ServiceNow or Workday.
  - Use an existing topic in the agent folder that calls a shared system topic as the starting pattern.
  - Guide the user through creating the template config record in Dataverse as part of the flow.
- **STANDALONE IS THE EXCEPTION**: Only use the standalone topic + workflow pattern when the scenario requires a connector that does NOT have an existing ESS orchestrator flow (e.g., Jira, custom HTTP APIs, non-ESS connectors). In this case, read `src/skills/workflows/create/SKILL.md` to create the workflow.
- **COMPLETE THE CHAIN**: If the topic requires a template config in Dataverse to function, walk the user through creating it. Do NOT stop after creating the topic YAML — guide the user through the Dataverse template config creation steps in the Power Platform Maker portal.
- **CLEAR FILE SUMMARIES**: When showing the user what was created, list every file with its FULL path, not just the filename. Show folder paths so the user can find each file. Example: `topics/ServiceNowQueryCMDB.mcs.yml` not just the filename.
- **TRACK PROGRESS**: Use the todo list tool to track your progress through this skill's steps. Create a todo list at the start with all the steps, mark each in-progress as you start it, and mark completed when done. This gives the user visibility into where you are in the process.

## Step 1: Understand the Request

Ask the user: "What should this topic do? Describe the conversation you want the agent to have."

Wait for their response. From it, determine:
- **What the topic does** (e.g., "look up vacation balance", "create an IT ticket", "show org chart")
- **What integration it needs** (ServiceNow, Workday, Dataverse, none)
- **What user input it needs** (free text, selections, dates, etc.)
- **What output it produces** (message, data display, adaptive card, etc.)

## Step 2: Choose the Right Template

Based on the user's description, select a starting template:

| Scenario | Template | When to use |
|----------|----------|-------------|
| Calls ServiceNow or Workday | Existing agent topic that calls a shared system topic | **Primary path.** Uses the ESS template config pattern with the shared orchestrator flow. |
| Simple informational response | Existing simple topic in agent folder | No external data needed. Just trigger phrases and messages. |
| Calls a non-ESS connector | Existing topic with `InvokeFlowAction` | Only for connectors without an ESS orchestrator flow (Jira, HTTP, etc.). Requires a standalone workflow. |
| Needs structured user input | Existing topic with `AdaptiveCardPrompt` | User needs to select from a list, fill a form, or make choices. Combine with any pattern above. |

**Decision rule**: If the scenario involves ServiceNow or Workday, ALWAYS use the template config pattern with the shared system topic. Do NOT create standalone flows for these connectors — that bypasses the ESS orchestrator.

If the topic involves ServiceNow, also read `src/reference/ess-docs/integrations/servicenow.md` and `src/reference/ess-docs/integrations/servicenow-hrsd-itsm.md` for integration-specific guidance.
If the topic involves Workday, also read `src/reference/ess-docs/integrations/workday.md` and `src/reference/ess-docs/integrations/workday-extensibility.md` for integration-specific guidance.

**Official samples**: Before generating YAML, read a relevant sample from `src/samples/` to use as a real-world reference:
- **Workday employee scenarios**: `src/samples/workday/employee/` — contains topic.yaml + template config XML for vacation balance, time off requests, contact info, education, government IDs, job taxonomy, emergency contacts
- **Workday manager scenarios**: `src/samples/workday/manager/` — company code, cost center, job taxonomy, service anniversary, time in position
- **ServiceNow HRSD scenarios**: `src/samples/servicenow/hrsd/` — create HR case, get user cases (JSON template configs)
- **ServiceNow ITSM scenarios**: `src/samples/servicenow/itsm/` — create incident, get user tickets, get ticket details (JSON template configs)
- **ServiceNow Catalog/CMDB scenarios**: `src/samples/servicenow/catalog/` — browse service catalog, CMDB asset lookup
- **Facilities scenarios**: `src/samples/facilities/` — facilities tickets, dining, guest invitations, vehicle registration
- **Evaluation test sets**: `src/samples/evaluations/` — starter and templated CSV test sets for HR/IT scenarios

Tell the user which approach you're taking and why.

## Step 3: Gather Details

Ask the user for the specifics you need. Don't ask everything at once — ask in groups:

**Group 1: Identity**
- "What should this topic be called?" → becomes `componentName`
- "What are 5-10 ways a user might ask for this?" → becomes `triggerQueries`

**Group 2: Model Description**
- Write a `modelDescription` based on the user's description. Include:
  - What the topic does (1-2 sentences)
  - Valid trigger examples
  - Invalid trigger examples (when NOT to trigger)
- Show the proposed description to the user and confirm. Keep under 1024 characters.

**Group 3: Conversation Flow Design**

This is the most important step. Do NOT just ask the user "how should it work?" — YOU are the expert. Analyze the scenario and **propose a flow with reasoning**.

For any scenario that involves data collection + external system calls, think through these design dimensions:

**Data collection approach**: How should the topic get information from the user?
- **Form-style** (adaptive cards with dropdowns/inputs): Deterministic, easy to build, feels like a form.
- **Conversational** (LLM extracts from natural language): Copilot-native, user describes once, system infers. Better UX but needs confirmation step.
- **Hybrid**: LLM extracts first, falls back to form if confidence is low.
- Always prefer the conversational approach — it's what makes Copilot better than a traditional form. Users should describe their problem ONCE and the system should infer the rest.

**Flow ordering**: What's the natural sequence?
- Collect the user's description FIRST — it drives everything downstream (classification, filtering, pre-population).
- Infer structured fields (category, type, etc.) from the description using the LLM.
- Query external systems with the inferred values.
- Show results for selection (filtered list, not the full dataset).
- Confirm everything before submitting.

**Result handling**: What if the query returns too many/too few results?
- 0 results → broaden the query or ask user to rephrase
- 1 result → auto-select and confirm
- 3-10 results → show dropdown
- 10+ results → ask a refining question before showing

**Present your proposed flow** as a numbered sequence with a diagram. Explain WHY you chose this approach. Ask the user to confirm or adjust. Example:

```
[1] User describes issue (free text) ─── drives short description + classification
        │
[2] LLM classifies → Category + Subcategory ─── user confirms or corrects
        │
[3] Query external system with classified values → filtered result list
        │
[4] User selects from adaptive card dropdown
        │
[5] Confirmation card (all fields pre-filled) ─── user confirms or edits
        │
[6] Record created → success confirmation
```

## Step 4: Check for Existing Patterns

Read the agent snapshot at `my/agents/{agent.slug}/topics.md` to see if similar topics already exist. If a similar pattern exists:
- Tell the user: "I found a similar topic ({name}) that does {X}. I'll use its pattern as a reference."
- Read the existing topic file to understand the action chain.

If the topic calls a workflow, check `my/agents/{agent.slug}/workflows.md` to see if a suitable workflow already exists. If not, tell the user they'll also need a workflow and offer to create one after the topic.

## Step 5: Generate the Topic YAML

Read the selected template from existing topics in the agent folder. Replace all `{{PLACEHOLDER}}` values with the user's specifics.

**File naming**: Use the pattern `{IntegrationPrefix}{ActionName}.mcs.yml`. Examples:
- `ServiceNowQueryCMDB.mcs.yml`
- `WorkdayGetVacationBalance.mcs.yml`
- `EmployeeCheckEquipmentStatus.mcs.yml`

**Action ID naming**: Use short, descriptive camelCase IDs (e.g., `sendIntro`, `askCategory`, `callFlow`, `checkResult`, `showCard`).

**Variable naming**: Use `Topic.{DescriptiveName}` for topic variables (e.g., `Topic.SelectedCategory`, `Topic.ResponseData`).

Show the generated YAML to the user for review. Highlight the key parts:
- Trigger phrases
- Model description
- Action chain (what happens step by step)
- Any placeholders that still need values (like workflow GUIDs)

## Step 6: Checkpoint, Write, Scan, and Push

This is the end-to-end delivery step. Do NOT stop after writing the file.
The user should never have to leave VS Code or manually push changes.

### 6.1 — Checkpoint

Before making any changes, save the current state. Run in the terminal:

```
python scripts/checkpoint.py "pre-create-{TopicName}"
```

Tell the user: "Saved a backup of your current agent files."

### 6.2 — Create dependencies (if needed)

**If the topic uses the Template Config pattern (ServiceNow/Workday):**

The topic calls the shared system topic, which looks up a template config by
`ScenarioName` in Dataverse. The template config record must exist for the
topic to work. **Create it before writing the topic file.**

1. **Try to use the Dataverse MCP** regardless of what `templateConfigsDiscovered`
   says in `my/config.json`. The flag may be stale. Search for Dataverse tools
   by calling `tool_search_tool_regex` with pattern `dataverse|Dataverse`.
   If tools are found, proceed with automated creation. If no tools are found,
   fall back to manual instructions (see "Manual Fallback" below).

2. Read the appropriate integration docs:
   - **ServiceNow**: Read `src/reference/ess-docs/integrations/servicenow-hrsd-itsm.md`
   - **Workday**: Read `src/reference/ess-docs/integrations/workday-extensibility.md`

3. Follow the template config skill's steps to:
   - Generate the template configuration content (JSON for ServiceNow, XML for Workday)
   - Use `create_record` to insert the new record into Dataverse
   - Verify the record was created

4. Wire the returned scenario name into the topic YAML. Update the topic's
   `ScenarioName` variable value with the actual scenario name that was created.

5. For Workday scenarios where the XML SOAP template was flagged for engineering
   review, add this warning: "The Workday XML SOAP template needs to be reviewed
   by someone with Workday API expertise before this topic will work. The template
   config record has been created in Dataverse, but the template configuration
   content is a placeholder."

**Manual Fallback** (if Dataverse MCP is unavailable):

If the Dataverse MCP tools fail:
1. Tell the user: "I couldn't connect to Dataverse automatically. You'll need to
   create the template configuration record manually."
2. Provide the scenario name the topic uses.
3. Walk the user through creating the record in the Power Platform Maker portal:
   - Open `make.powerapps.com` → select the ESS environment
   - Navigate to `msdyn_employeeselfservicetemplateconfigs` table
   - Create a new record with the scenario name, operation type, table name, and
     template configuration content
   - See `src/reference/ess-docs/customization/customize.md` for the full field reference

**If the topic uses the Standalone pattern (non-ESS connectors only):**

The topic references a workflow via `InvokeFlowAction`. If the workflow doesn't
exist yet, create it now. Read `src/skills/workflows/create/SKILL.md` and follow
its steps. The user should not have to manage the dependency chain manually.

### 6.3 — Write the topic file

1. Read `my/config.json` to get `agent.folder`.
2. Write the topic file to `{agent.folder}/topics/{filename}.mcs.yml`.

### 6.4 — Scan for errors

Check for errors across the **full agent folder** using the diagnostics tool —
not just the new file.

- If errors exist in the **new file** → fix them before proceeding.
- If **pre-existing errors** exist in other files → mention them briefly but
  do NOT block the push. Example: "I also found 3 pre-existing errors in other
  topics. You can fix those later with `/scan`."

### 6.5 — Dry run

Run in the terminal:

```
python scripts/push.py --dry-run
```

Show the user the diff summary from the output. This tells them exactly what
will be created, modified, or deleted in their environment. Example:

> Here's what will be pushed:
>
> | Action | File |
> |--------|------|
> | ➕ New | topics/SubmitITSupportTicket.mcs.yml |

### 6.6 — Push

Ask the user: "Ready to push to your environment?"

When confirmed, run in the terminal:

```
python scripts/push.py --yes
```

This authenticates to Dataverse, creates/updates records, and updates the
local baseline and component map.

**If the push fails:**
- Show the error output to the user.
- Offer two options:
  - **Retry** — run push again
  - **Revert** — `python scripts/checkpoint.py --revert` to restore the
    backup from step 6.1

### 6.7 — Verify and link

After a successful push, show the user what was created:

- Topic file path (linked so they can click to open it)
- If template config was created: the scenario name
- If workflow was created: the workflow file path

Then show:

> Your topic is live! Test it here:
> [Open Copilot Studio](https://copilotstudio.microsoft.com/)

## Step 7: Offer Next Steps

After the topic is pushed and verified:
- "Would you like to create another topic?"
- "Type `/menu` to see other options."
