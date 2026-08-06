# Update a Simple Topic with Evals

Update an existing Phase 1 topic from an approved eval contract. The same
contract drives the topic edit, native Copilot Studio eval generation, static
validation, and runtime-validation handoff.

This is the default topic path used by `/update` for simple topics:
informational responses, clarification, routing, and handoff.

## Rules

- Read `.local/config.json` first and use the active agent folder.
- Read `src/skills/topics/update/SKILL.md` for topic matching and safe-editing
  rules.
- Resolve exactly one existing user-facing topic before drafting the contract.
- If the request or selected topic uses Workday, ServiceNow, SAP, an
  `InvokeFlowAction`, a connector, a template configuration, or another
  external system, stop this wrapper and follow
  `src/skills/topics/update/SKILL.md` unchanged. Do not create or refresh evals
  for that request in this PR.
- Do not edit the topic until the user approves the eval contract.
- Preserve the topic filename, schema name, component name, trigger kind, and
  existing action IDs unless the requested edit requires an action-chain
  change.
- Never create a second topic file during an update.
- Keep the existing safety gates: checkpoint, diagnostics, topic review, dry
  run, explicit push confirmation, and verification.
- Only replace eval files in folders owned by this scenario:
  `{agent.folder}/evaluations/eval-driven-{scenario-id}*/`.
- Do not modify unrelated evaluation sets.

## Step 1: Resolve the topic and confirm Phase 1 scope

Use the matching rules in `src/skills/topics/update/SKILL.md` to find the
existing topic. If the match is missing or ambiguous, ask the user to select
one.

Read the full topic and the requested change. Use the legacy update skill
instead when either the existing topic or requested change involves an
external system.

## Step 2: Build the update contract

Choose a stable `scenario-id`:

1. Find every runtime manifest under
   `.local/eval-driven/*/runtime-manifest.json` that points to this topic path.
2. If exactly one manifest matches, reuse that manifest's scenario ID.
3. If more than one manifest matches, stop before making changes. Show the
   conflicting manifest paths and ask the user which scenario owns the topic;
   never select one silently.
4. If no manifest matches, use the lowercase kebab-case slug of the existing
   topic filename.

Read, when present:

- `.local/eval-driven/scenarios/{scenario-id}.scenario.yaml`
- `{agent.folder}/evaluations/eval-driven-{scenario-id}*/`

If the user supplied other existing native eval files, collect the topic type,
persona, intent, and approved source content needed by the contract, then run:

```text
python scripts/eval_scenario.py normalize "{selected-eval-path}" --id "{scenario-id}" --name "{existing topic name}" --intent "{intent}" --topic-type "{topicType}" --persona "{persona}" --output ".local/eval-driven/drafts/{scenario-id}.scenario.yaml"
```

For an informational topic, also pass `--source-content`. Read the normalized
draft and merge only the user's requested behavior change and required
regression cases before presenting it for approval. Do not manually reconstruct
native eval rows or overwrite the approved scenario before approval.

Draft the updated Phase 1 scenario from:

- The existing topic behavior.
- The user's requested change.
- Existing scenario-owned evals.

Infer `topicType` as `informational`, `clarification`, `routing`, or `handoff`.
For informational topics, require the approved response or source link in
`sourceContent`. Do not invent policy or guidance content.

Include:

- Direct trigger, paraphrase, and non-trigger coverage.
- Cases for the requested change.
- Regression cases for existing behavior that must remain unchanged.

If no scenario-owned evals exist, create the initial contract from the topic
and requested change. Do not treat the absence of evals as an error.

## Step 3: Present and approve the contract

Show:

| Field | Value |
|-------|-------|
| Existing topic | `{topic path}` |
| Intended outcome | `{intent}` |
| Topic type | `{topicType}` |
| Persona | `{persona}` |
| Existing generated evals | `{count or none}` |
| Required evals after update | `{count}` |

Then show every eval:

| # | Category | Input or condition | Expected behavior | Required |
|---|----------|--------------------|-------------------|----------|

Ask the user to **approve** or **edit** the contract. Do not change the topic
until the user explicitly approves it.

After approval:

1. Write the scenario to
   `.local/eval-driven/scenarios/{scenario-id}.scenario.yaml`.
2. Validate it:

   ```text
   python scripts/eval_scenario.py validate ".local/eval-driven/scenarios/{scenario-id}.scenario.yaml"
   ```

3. If validation fails, fix the contract and present changed fields for
   approval again.

## Step 4: Update the existing topic

Before editing, run:

```text
python scripts/checkpoint.py "pre-eval-driven-update-{scenario-id}"
python scripts/emit_capability.py topic_update
```

Use the approved contract instead of repeating discovery questions:

- `intent`, direct triggers, and paraphrases update trigger queries and model
  description when required.
- `nonTrigger` and boundary evals define when the topic must not run.
- `sourceContent` supplies approved informational responses.
- Multi-turn evals define clarification, correction, cancellation, routing,
  and handoff behavior.
- Regression evals identify behavior that must remain unchanged.

Apply only the requested changes to the resolved existing topic file. Follow
the safe-editing rules in the base update skill, but do not run its checkpoint,
dry-run, or push steps because this wrapper owns those lifecycle steps.

## Step 5: Generate or refresh evals

Run:

```text
python scripts/eval_scenario.py materialize ".local/eval-driven/scenarios/{scenario-id}.scenario.yaml" --agent-folder "{agent.folder}" --topic-file "{existing-topic-file}" --runtime-output ".local/eval-driven/{scenario-id}/runtime-manifest.json" --operation update
```

This creates evals when none exist. When scenario-owned evals already exist, it
replaces those files and removes stale cases from only that scenario's owned
folders.

## Step 6: Validate, review, and preview

1. Check diagnostics across the full agent folder. Fix errors in the edited
   topic or generated evals.
2. Run evaluation quality validation using
   `src/skills/evaluations/validate/SKILL.md`.
3. Run the mandatory single-topic review using
   `src/skills/topics/review/SKILL.md` and show its full maker-facing report.
4. Run:

   ```text
   python scripts/push.py --dry-run
   ```

5. Confirm the dry run shows the existing topic as modified, generated evals
   as new or modified, and no second topic as new.

Do not proceed if generated YAML cannot be parsed. Review findings remain
advisory and follow the existing fix-now or push-anyway flow.

## Step 7: Push and report

Ask for explicit confirmation, then run:

```text
python scripts/push.py
```

After success, report:

- Scenario contract path
- Modified topic path
- Generated native eval paths
- Runtime-manifest path

If no runtime pipeline is configured, state that static update and deployment
are complete and the manifest is ready for runtime validation. Do not claim
that runtime behavior passed.
