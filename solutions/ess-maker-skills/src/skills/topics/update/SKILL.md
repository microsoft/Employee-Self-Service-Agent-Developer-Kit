# Update Topic Skill

This skill guides the user through modifying an existing Copilot Studio topic.
Updating means editing the local working copy AND pushing the change to the
live environment via push.

## CRITICAL — Local Files Are a Working Copy

The files in `workspace/agents/{slug}/` are a **working copy** of what's deployed in
Copilot Studio. Editing a local file is NOT the same as updating the live
topic. You MUST push the changes to Copilot Studio via `push.py` for them to
take effect. **NEVER stop after editing only the local file.**

## Rules

- ALWAYS read `.local/config.json` to get the agent folder, slug, and schema name.
- ALWAYS read existing topic files in the user's agent folder as schema examples before editing any YAML.
- ALWAYS checkpoint before making changes.
- ALWAYS push changes to Copilot Studio after editing.
- NEVER modify system topics (`on-error`, `conversation-start`, etc.) without
  warning the user about potential side effects.
- **PRESERVE THE AUTHORING INVARIANTS**: follow [`authoring-invariants.md`](src/reference/ess-docs/customization/authoring-invariants.md) — an edit MUST keep the shared-system-topic delegation, the standard parse → iterate → table rendering, and the shared error path intact.
- **TRACK PROGRESS**: Use the todo list tool to track your progress.

## Step 1: Identify the Topic

Read `.local/config.json` to get `agent.folder` and `agent.slug`.

If the user named a specific topic, find the matching file in
`{agent.folder}/topics/`. Match by filename, `componentName`, trigger phrases,
or `modelDescription`.

If the match is ambiguous, list available topics and ask the user to pick.

## Step 2: Understand the Change

Read the full topic file. Ask the user what they want to change if not
already clear. Common modifications:

| What the user says | What to change |
|-------------------|---------------|
| "Change the trigger phrases" | Update `triggerQueries` list |
| "Change the response message" | Update `SendActivity` → `text` |
| "Add a question/prompt" | Add a `Question` or `AdaptiveCardPrompt` action |
| "Add a condition" | Add a `ConditionGroup` action |
| "Change when the topic fires" | Update `modelDescription` and/or `triggerQueries` |
| "Call a different workflow" | Update `InvokeFlowAction` → `flowId` |
| "Add a step" | Insert a new action in the `actions` chain |
| "Remove a step" | Remove an action (update `nextActionId` chain) |

Show the user the relevant section of the current topic and propose the
specific edit. Explain what will change and why.

**Power Fx + Power Automate (flow-backed data).** If the change makes a topic **consume a custom Power Automate flow's output in Power Fx** — typed tables, dynamic/dependent option lists, or status/success handling — read `src/reference/ess-docs/customization/powerfx-and-power-automate-authoring.md` first. It defines the type-safety constraints (untyped flow output → stringify → `ParseValue` into a typed table, `number` not `integer` status codes, `kind:Skills` flow Response, PascalCase system-topic schemaname) and the deploy/verify loop (`push` registration, `publish`, `validate`, `--repair`). Skipping these causes silently dropped fields or a non-functional topic.

**Acting on a `/review` finding.** If the change comes from a `/review` finding, prefer the structured
findings catalog `/review` writes at `.local/review-findings/{topic-stem}-catalog.json` — it survives
across sessions and gives each finding a stable `id`, its `files[]`, and a `concrete_fix`. List it with
`python scripts/merge_findings.py --solution {topic-stem} --show` from `solutions/ess-maker-skills/`. Act on
the finding whose `id` (or step/label) the customer named; if the catalog is absent, fall back to the
suggested fix in the visible `/review` report. Either way, locate the action by its **identity** (`kind` +
node `id`, step name/label, any quoted expression) — **not** a line number — and apply the fix. Read the
surrounding actions first: if the node's actual context makes a better fix obvious than the suggestion (for
example, the flagged value turns out to be dead — written but never read — so removing it is cleaner than
rewriting it), apply that and say why. If one finding covers several angles at the same node, address each.

After a fix is applied and you have confirmed by re-reading the file that the flagged node is gone or
corrected, tell the customer to re-run `/review` — its reconcile step sees the finding's file changed
(evidence-stale), confirms the node is gone, and records it resolved in the shared ledger so it stops being
carried forward. Then continue from Step 3.

## Step 3: Checkpoint

Run in the terminal:

```
python scripts/checkpoint.py "pre-update-{TopicName}"
python scripts/emit_capability.py topic_update
```

Tell the user: "Saved a backup of your current agent files." The
`emit_capability.py` line records anonymous usage telemetry (best-effort,
non-blocking); it needs no user-facing message and never fails the step.

## Step 4: Apply the Edit

Make the change to the topic file using file editing tools.

**Safe modification patterns:**
- Adding/removing trigger phrases: Edit the `triggerQueries` list
- Changing messages: Edit `text` fields in `SendActivity` actions
- Changing model description: Edit `modelDescription` (keep under 1024 chars)
- Adding actions: Insert in the `actions` list and update `nextActionId` links
- Removing actions: Remove from `actions` and fix `nextActionId` chain

**What NOT to change without warning:**
- `schemaName` — breaks references from other topics
- `componentName` — may affect display in Copilot Studio
- `kind` — system vs. general topic classification
- Action IDs referenced by other actions — breaks the flow chain

After editing, read the file back to verify the change looks correct.

## Step 5: Scan for Errors

Check for errors across the **full agent folder** using the diagnostics tool.

- If errors exist in the **edited file** → fix them before proceeding.
- If **pre-existing errors** exist in other files → mention briefly but do
  NOT block the push.

## Step 6: Dry Run

Run in the terminal:

```
python scripts/push.py --dry-run
```

Show the user the diff summary. It should show the topic as modified.

## Step 7: Push to Copilot Studio

Ask the user: "Ready to push this change to your environment?"

When confirmed, run:

```
python scripts/push.py --yes
```

**If the push fails:**
- Show the error output.
- Offer: **Retry** or **Revert** (`python scripts/checkpoint.py --revert`).

## Step 8: Verify

After a successful push, tell the user:

> ✅ **{TopicName}** has been updated in Copilot Studio.

Topic (botcomponent) changes only go live once the agent is **published** (flow `clientdata` edits are live immediately). Offer to publish for them:

```
python scripts/publish.py
```

If the change added or modified a ServiceNow ITSM flow (e.g. the runtime dependent-dropdowns options flow), also offer to confirm the flow is agent-invocable — this verifies it is activated, `modernflowtype=1`, has kind:Skills Response actions, a bound flow-scoped connection reference, and a system-topic link:

```
python scripts/validate.py "<flow name>"
```

If the user prefers to publish manually instead, point them at [Copilot Studio](https://copilotstudio.microsoft.com/).

## Step 9: Offer Next Steps

- "Would you like to make another change?"
- "Type `/scan` to check for errors."
- "Type `/menu` to see all available commands."
