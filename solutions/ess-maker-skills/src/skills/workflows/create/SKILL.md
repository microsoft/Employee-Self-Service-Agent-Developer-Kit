# Create Workflow Skill

This skill guides the user through creating a new Power Automate cloud flow for their Copilot Studio agent.

## IMPORTANT: When NOT to Create a New Workflow

**Do NOT create a standalone workflow for ServiceNow, Workday, or SAP scenarios.**
These integrations ship with a **shared flow pre-installed via their extension
pack**. The shared flow reads template configs from Dataverse and handles all
CRUD operations. Customers never create or modify these flows — they only create
template configs and topics. See `src/reference/ess-docs/customization/customize.md`.

**Only create a new standalone workflow when:**
- The scenario requires an integration that does NOT have an ESS extension pack (e.g., ADP, Jira, custom HTTP APIs, or other 3P tools)
- The customer needs a custom connector for an internal API
- The user explicitly requests a standalone workflow after being informed about the template config pattern

If the user asks to create a workflow for ServiceNow, Workday, or SAP, redirect them:
"ESS already has a shared flow for that integration — it's installed with the
extension pack. Instead of creating a new workflow, I'll create a topic that uses
the existing shared flow with a template configuration in Dataverse. This is the
recommended ESS pattern."
Then read `src/skills/topics/create/SKILL.md` and follow the template config path.

## Rules

- Do NOT run terminal commands or scripts. Use built-in file reading and writing tools only.
- ALWAYS read existing workflow files in the user's agent folder (`{agent.folder}/workflows/`) as schema examples before generating any workflow JSON.
- ALWAYS read the agent's `connectionreferences.mcs.yml` to understand connector wiring.
- ALWAYS read `.local/config.json` to get the agent folder name.
- Create the workflow in a new folder: `{agent.folder}/workflows/{WorkflowName}-{GUID}/`
- Write both `metadata.yml` and `workflow.json` into that folder.
- After writing, check for errors using the diagnostics tool.
- **TRACK PROGRESS**: Use the todo list tool to track your progress through this skill's steps. Create a todo list at the start with all the steps, mark each in-progress as you start it, and mark completed when done.

## Step 1: Understand the Request

Ask the user: "What should this workflow do? What external system does it call, and what data should it return?"

From their response, determine:
- **What connector** it uses (ServiceNow, Workday, Dataverse, HTTP, etc.)
- **What operation** it performs (query records, create record, update, delete, custom API call)
- **What inputs** it needs from the topic (IDs, search terms, parameters)
- **What outputs** it returns to the topic (data, success flag, error message)

## Step 2: Check Existing Workflows

Read `workspace/agents/{agent.slug}/workflows.md` to see if a suitable workflow already exists. If the agent already has a workflow that does something similar, tell the user:
- "Your agent already has a workflow called '{name}' that {does X}. Would you like to use that one, or create a new one?"

Also check `workspace/agents/{agent.slug}/connections.md` to see which connectors are already configured. If the needed connector isn't available, tell the user they'll need to add it through the Copilot Studio portal first.

## Step 3: Generate the Workflow

Read the template from an existing workflow in the agent folder (e.g., `{agent.folder}/workflows/*/workflow.json`).

Generate a new GUID for the workflow ID. You can use any valid GUID format (8-4-4-4-12 hex characters).

Create two files:

### metadata.yml
```yaml
jsonFileName: workflows/{WorkflowName}-{GUID}/workflow.json
workflowId: {GUID}
name: {WorkflowDisplayName}
type: 1
description: "{Description}"
subprocess: false
category: 5
mode: 0
scope: 4
stateCode: 1
statusCode: 2
isTransacted: true
```

### workflow.json
Customize the template by:
1. Setting the correct `connectionReferences` — match the `connectionReferenceLogicalName` to a value from `workspace/agents/{agent.slug}/connections.md`
2. Defining trigger inputs — what the topic will pass to the workflow
3. Adding the correct connector action — use the right `operationId` for the task
4. Defining the response outputs — what data goes back to the topic

For connector-specific action parameters:
- **ServiceNow**: Read `src/reference/ess-docs/integrations/servicenow-hrsd-itsm.md` for table names, query syntax, and field names
- **Workday**: Read `src/reference/ess-docs/integrations/workday.md` for SOAP operations and scenario names

Show the user the generated workflow and explain:
- What inputs it expects
- What connector operation it calls
- What outputs it returns
- How it handles errors

## Step 4: Write the Files

After the user approves:
1. Create the workflow folder: `{agent.folder}/workflows/{WorkflowName}-{GUID}/`
2. Write `metadata.yml`
3. Write `workflow.json`
4. Check for errors using the diagnostics tool
5. If errors exist, show them and propose fixes
6. If clean, show the user:
   - Links to the created files so they can review them
   - The Copilot Studio web link: `https://copilotstudio.microsoft.com/`
   - Example: "Your workflow is ready! Review it here: `{agent.folder}/workflows/{WorkflowName}-{GUID}/workflow.json` and test it in [Copilot Studio](https://copilotstudio.microsoft.com/)."

## Step 5: Connect to a Topic

After the workflow is created, the user needs a topic to call it. Tell them:
- "Your workflow is ready with ID `{GUID}`. To use it from a topic, add an `InvokeFlowAction` with `flowId: {GUID}`."
- "Would you like me to create a topic that calls this workflow?"

If they say yes, hand off to the topic creation skill (`src/skills/topics/create/SKILL.md`).
