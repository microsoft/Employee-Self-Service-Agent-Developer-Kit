# Evaluation Creation Dispatcher

Select the correct evaluation-generation flow by matching the user's requested
scenario to the configured agent's topics. This skill only routes; it never
generates, edits, or pushes evaluation files itself.

## Rules

- Route by whether the requested scenario is implemented by a configured topic,
  not by whether the user knows or mentions internal topic terminology.
- Inspect topic evidence before choosing a generation skill.
- Route new generation to exactly one generation skill. Existing-set edit/add
  requests go to the update skill instead; never regenerate to reach editing.
- Do not expose skill names, file paths, or internal routing terminology to the
  user.
- After selecting a flow, read the selected skill and follow it completely.

## Step 1: Identify the requested scenario

First recognize an existing-set edit/add request, including a response to
**Edit this existing set** or **Add test cases to this set**. If the user already
selected an exact folder/source, carry it and the requested action directly to
`src/skills/evaluations/update/SKILL.md`. Otherwise use that skill's
`evaluation_review.py --list-all` discovery and explicit selection before any
mutation. Do not ask for a new scenario or pick a same-name set from another
source. For all other requests, continue below.

Extract the scenario, goal, or capability the user wants to evaluate, such as
compensation, employee ID, HR policy lookup, or IT ticketing.

If the request does not identify a scenario or goal, ask:

> Which scenario or goal should I create evaluation tests for?

Wait for the answer before routing.

## Step 2: Search configured topics

Read `.local/config.json` when it exists. A configured topic inventory is
available only when:

1. `setup` is `"complete"`;
2. `agent.folder` is present; and
3. `{agent.folder}/topics/` contains at least one `.mcs.yml` file.

When the inventory is available, inspect every topic's:

- Filename and topic display name.
- `modelDescription`.
- `triggerQueries`.
- User-facing messages and invoked actions when needed to confirm behavior.

Match by capability and meaning, not only exact words. For example, a
compensation request may match a topic described as base pay or salary.

## Step 3: Route from the match

### Matching topic found

When one or more topics clearly implement the requested scenario, read
`src/skills/evaluations/create/SKILL.md` and follow it. Carry the requested
scenario and matched topic names into that skill as the generation scope.

If several topics contribute to the same scenario, include all of them. Do not
ask the user to select topics unless the candidates represent genuinely
different scenarios.

The selected generator owns existing-set collision choices and renders the
pre-generation coverage explanation from
`src/skills/evaluations/experience-contract.md` once. Do not duplicate it here.

### No matching topic found

When no configured topic implements the requested scenario, or no configured
topic inventory is available, read
`src/skills/evaluations/generate/SKILL.md` and follow it.

The catalogue-grounded result is still a valid `.mcs.yml` plus CSV evaluation
set, but it represents the requested ESS scenario rather than behavior observed
in the configured agent.
