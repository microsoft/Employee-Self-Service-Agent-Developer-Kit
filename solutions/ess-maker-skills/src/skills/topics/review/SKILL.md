# Review Topic Skill

This skill runs an **authoring-time conformance review** over a single authored Copilot Studio topic and
returns an **advisory** report — findings the maker should consider before publishing.

> **Advisory by construction.** This review has no power to block — it surfaces findings and the maker
> decides. Never present a finding as a hard failure or refuse to proceed.

## Rules

- Do NOT modify the topic. This skill only reads and reports; the review output is advisory prose and is
  not written to disk.
- Operate on the authored `.mcs.yml` in the maker's agent folder (`{agent.folder}/topics/`), i.e. the
  topic **before publish**. Do not require the published `samples/` copy.
- **TRACK PROGRESS**: use the todo list tool to track the steps below so the maker can see where you are.

## What this checks

This skill analyzes:

- the topic's **Power Fx expression logic** (guidance:
  `src/reference/ess-docs/conformance/powerfx-topic-local.md`) — decidable from the authored topic file;
- **`Global.*` reference integrity** across the agent (guidance:
  `src/reference/ess-docs/conformance/dangling-globals.md`) — references that resolve to no variable;
- **adaptive-card UX contract** (guidance: `src/reference/ess-docs/conformance/ux-contract.md`) — card
  data bindings that resolve to nothing, and empty/error/confirmation-state gaps;
- **ISV conformance** (guidance: `src/reference/ess-docs/conformance/isv-conformance.md`) — the topic
  against the documented field/schema conventions and known pitfalls of the backend system it integrates
  with, when ISV reference docs are available;
- **ISV integration pattern** (guidance: `src/reference/ess-docs/conformance/isv-integration-pattern.md`) —
  whether a topic for an ESS-orchestrated backend uses the shared template-config pattern rather than a
  standalone flow.
- **ServiceNow response-field integrity** — response fields the topic parses that the scenario's template
  config never returns, and which therefore render blank at runtime.

Other checks (cross-component error-code coverage) are not part of this skill; if the
maker asks about those, say they are not covered rather than guessing.

## Step 1: Identify the topic to review

Determine the target `.mcs.yml`:

- If the maker gave a path, use it.
- Otherwise read `.local/config.json` for the agent folder, list `{agent.folder}/topics/*.mcs.yml`, and
  ask the maker which topic to review (or offer to review the most recently modified one).

State the full path of the file you are about to review.

## Step 2: Read the topic

Read the entire target `.mcs.yml`. Identify every Power Fx expression: any value beginning with `=`, and
the expression bodies inside `AdaptiveCardPrompt.card` and `AdaptiveCardTemplate.cardContent`. For each,
capture the enclosing action's **`id:`**, **`displayName:`** (if present), and **`kind:`** — these are the
stable node locators the fix step keys on. Note the approximate line number as secondary context only.

## Step 3: Check Global reference integrity (run the detector)

Run this from the `solutions/ess-maker-skills/` directory:

```
python scripts/scan_globals.py --agent {agent-slug} --topic {topic-stem}
```

- `{agent-slug}` = the agent folder name under `workspace/agents/` (from `.local/config.json`).
- `{topic-stem}` = the reviewed topic's filename without `.mcs.yml`.

The detector's output is **authoritative** on whether a `Global.*` reference resolves. Every reference it
reports as dangling **does not exist** anywhere in this agent — it is neither written by any topic nor
declared as a variable. Do **not** reason about whether such a reference "might be blank" or "might exist
for some records": if the detector reports it, it will **always** read blank. Read
`src/reference/ess-docs/conformance/dangling-globals.md` and turn each reported reference into a finding,
applying the precision bar and reachability scoring to set severity. If the script genuinely cannot be
run, say so in the report rather than silently skipping.

## Step 4: Check adaptive-card UX contract

If the topic contains an adaptive card, run the binding detector from the
`solutions/ess-maker-skills/` directory:

```
python scripts/scan_bindings.py --agent {agent-slug} --topic {topic-stem}
```

Its output is **authoritative** on whether a card's `Topic.*` reference resolves: every reference it
reports **will always render blank at runtime**. Then read
`src/reference/ess-docs/conformance/ux-contract.md` and assess the card's empty/error/confirmation states
(Part 2). Turn each into a finding with the shared precision bar and severity mapping. If the script
cannot run, say so rather than silently skipping.

## Step 5: Analyze Power Fx expression logic (internal reasoning)

Read the analysis guidance at
`src/reference/ess-docs/conformance/powerfx-topic-local.md` and apply every heuristic in it to the
expressions you gathered. Use its precision bar (>=80% confidence), reachability scoring, and severity
mapping to decide which candidates are real findings and how serious each is.

## Step 6: Check ISV conformance (if the topic integrates a backend system)

If the topic calls an ISV scenario, read
`src/reference/ess-docs/conformance/isv-conformance.md` and follow it: determine the target ISV from the
scenario name, read that ISV's reference doc if one is available in the environment, and check the topic
against the documented field/schema conventions and known pitfalls. If the ISV reference docs are not
available, note that ISV conformance was not checked and continue — do not guess ISV behavior.

## Step 6b: Check the ISV integration pattern

Read `src/reference/ess-docs/conformance/isv-integration-pattern.md` and follow it: if the topic
integrates an ESS-orchestrated backend (ServiceNow, Workday, SAP SuccessFactors), confirm it delegates the
backend call to the shared system topic rather than calling its own cloud flow. This check reads only the
authored topic and always applies (no reference docs needed).

## Step 6c: Check ServiceNow response-field integrity (run the detector)

If the topic integrates ServiceNow, run this from the `solutions/ess-maker-skills/` directory:

```
python scripts/scan_config.py --agent {agent-slug} --topic {topic-stem}
```

Its output is **authoritative** on whether a parsed response field is returned by the scenario's template
config: every field it reports is one the topic parses but the config never produces, so it **will always
render blank at runtime**. Turn each reported field into a finding, applying the precision bar and
reachability scoring from the shared [`finding-contract.md`](src/reference/ess-docs/conformance/finding-contract.md)
(this check uses the `BTCF` finding-ID prefix). The detector covers ServiceNow scenarios only (Workday's
config declares only a top-level key); if it reports nothing, or the topic is not ServiceNow, this check
contributes no findings. If the script cannot run, say so rather than silently skipping.

Steps 3–6c are **internal reasoning**, and every lens reports findings in the one shared shape defined by
[`finding-contract.md`](src/reference/ess-docs/conformance/finding-contract.md) — precision bar, severity
via reachability, finding-ID prefixes, and the structured output format. Their rule IDs (e.g. `BTPF-001`),
reachability tags (`REACHABLE_NORMAL_UI`, etc.), and the word "lens" are working vocabulary **for you** —
they are NOT shown to the customer (see Step 8). Carry each finding's node locators (`id` / `displayName` /
`kind`) and `Fix targets` through internally so the consolidation and customer-facing steps can name the
step and a fixer can act.

## Step 7: Consolidate findings

Before presenting, dedupe the findings from Steps 3–6c so each fix site is shown once. Different
heuristics — and different lenses — can flag the same node (e.g. a hardcoded `flowId` caught by both the
Power Fx and ISV integration-pattern lenses).

Group findings by **fix-target node id** (fall back to the site `id` / `kind` if a finding has no distinct
fix target). Within a group:

- If **one fix resolves the group**, merge into a single finding: highest severity, one unified fix,
  keeping every contributing rule ID.
- If the node genuinely needs **two independent fixes**, keep both rows and add a short "same step" note.

Carry the consolidated locators, rule IDs, and `Fix targets` to Step 8.

## Step 8: Present the advisory report (customer-facing)

Present findings in **plain language**. Do NOT expose internal terminology to the customer — no "lens",
no rule IDs, no reachability tag names, no file-format jargon. Translate severity to plain words
(**High / Medium / Low**). Locate each finding by the **step/action it lives in** (its name/label), not a
line number.

Frame every finding as a **potential** issue, not a confirmed bug. These come from common-pattern
heuristics and can be false positives — hedge accordingly ("this might…", "you may want to check…",
"this could…"), never "this is broken" or "you must fix". Use the highest-severity finding for the
verdict:

- No findings -> `I looked over this topic's logic and didn't spot anything to flag.`
- Only Low / no-impact -> `This topic looks good — a couple of minor things you might want to double-check before publishing.`
- Any Medium -> `I spotted a few things that might be worth a look before you publish this topic.`
- Any High -> `I spotted some things that could cause problems — you may want to review these before publishing.`

Directly under the verdict, include this framing line:

> These are potential issues flagged from common patterns — not confirmed bugs. Some may not apply to
> your scenario; use your judgment.

Then a plain findings table. Locate each finding by the **step/action it lives in** (its name/label),
not a line number — that is how you (or `/update`) will find and fix it:

> **Review — `{TopicName}`** — {verdict}
>
> | # | Severity | Where (step) | Potential issue | Suggested fix |
> |---|----------|--------------|-----------------|---------------|
> | 1 | Medium | "Redirect to Workday Get Common Execution" | The flow call may not handle a failure, so an error could show the user nothing | Consider adding a branch that handles the failure case and shows an error message |

The table carries each finding — do **not** restate its rows in prose below. Order rows High -> Medium ->
Low, and group any "no user impact today" items under a short **Minor / cleanup** heading so the customer
sees the most likely issues first. Add a short explanation under the table **only** for a finding whose
suggested fix needs a Power Fx snippet or a nuance the table cell can't hold; keep it hedged and refer to
the site by its **step name/label**. If every finding is self-explanatory from the table, add nothing.

## Step 9: Close

End advisory, never blocking:

> This is advisory — you can publish as-is. Consider addressing the higher-severity items first (use
> `/update` to edit the topic), then re-run `/review` after edits to re-check.

**If invoked as a subagent by a parent flow** (not directly by the customer): skip the plain-language
translation and instead return the **structured** findings — rule IDs, severity, reachability, and sites
from the analysis guidance — so the parent can consume them programmatically. Do not prompt the customer
directly in that case.
