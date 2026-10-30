# Evals

Read in Round 8. Evals show whether the skill triggers when it should and makes the agent do the right thing, compared with a baseline: no skill, or the previous version.

## Contents

- What to write
- Run offline
- Run in Copilot
- Grade
- Compare and iterate

## What to write

Fill [../assets/evals-template.json](../assets/evals-template.json) as `evals.json` in the iteration folder, not in the skill folder (everything in the skill folder ships with the agent).

**Trigger queries.** About 20 realistic messages labeled `should_trigger`:

- 8 to 10 positives that vary phrasing (formal, casual, typos), explicitness (names the area or only the need) and length. The most useful ones need the skill without naming it. Start from the maker's example requests.
- 8 to 10 near misses: messages that share words with the skill but belong to a neighbouring skill or to knowledge search ("what's the leave policy" for a case-creation skill).
- Keep about 40% aside as a validation set when you tune the description, so you don't overfit to the training phrasings.

**Behavior cases.** At least three, from the acceptance criteria in `plan.md`:

- `prompt`: what a user types, with realistic detail.
- `expected`: what success looks like, in a sentence.
- `assertions`: checkable statements about tool calls and the reply, for example "creates the case with `create_record` in the chosen service's table", "asks for confirmation before creating", "doesn't set `assigned_to`", "replies with the case number". Avoid exact wording; it breaks on correct replies.
- Include at least one edge case: an ambiguous request, a missing value, or a request the tools can't do.

## Run offline

Fast, and possible before anything is uploaded. Invoke `runSubagent` for each run; each subagent starts fresh, with no access to this conversation or to other runs.

- **Trigger run.** Give the subagent only the agent's skill names and descriptions (from `inventory.json`, with the new skill's description) and one query. Ask which skills it would load, or none. Three runs per query; the trigger rate is the share of runs that picked the skill. A positive passes above 0.5, a near miss below.
- **Behavior run.** Give the subagent the skill folder, any shared rules skill it references, the tool list from `inventory.json` (names, descriptions, parameters) and one prompt. It must not call anything; it writes the tool calls it would make, in order with arguments, then the reply, assuming plausible tool results. Run the same prompt with the baseline in a separate subagent.

Offline runs show whether the instructions are clear enough to plan from. They don't show what Copilot's model will do, which may skip the skill entirely. Tell the maker this when you report results.

## Run in Copilot

After the maker adds the skill to their agent:

1. Start a new chat with the agent for each prompt. Type `-developer on` first to get the trace.
2. Export the turn's debug information.
3. In the export, a skill was read if a skills `read_resource` call names it; tool calls show the tool name and parameters.

Copilot doesn't always show a skill-loading step in the chat, so its absence doesn't mean the skill wasn't read; check the export.

## Grade

Record each assertion as PASS or FAIL with evidence quoted from the run, in `grading.json` next to the run. Require concrete evidence for a PASS: a label without substance fails. While grading, fix assertions that always pass (with and without the skill), always fail, or can't be checked.

When two versions both pass, compare them blind: give both plans to a fresh subagent without saying which is which and ask which better meets `expected`, and why.

## Compare and iterate

Summarize each configuration in `benchmark.json`: pass rate, trigger accuracy, and, for live runs, seconds and tool calls per turn. Then:

- Assertions that pass only with the skill show its value; keep what produced them.
- Failures with a clear cause become fixes: a missing step, an unclear rule, or a new gotcha.
- If results vary between runs of the same prompt, an instruction is ambiguous; make it specific or add an example.
- Generalize fixes; don't patch for one prompt. Remove instructions the runs show are never needed.

Report to the maker in plain language: how often the skill was picked when it should be, which behavior cases passed, and what you'd change. Then go back to Round 7 with their choice. Stop when there's nothing left to fix or results stop improving.
