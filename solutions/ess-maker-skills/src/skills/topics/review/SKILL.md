# Review Topic Skill

This skill runs an **authoring-time conformance review** over a single authored Copilot Studio topic and
returns an **advisory** report — findings the maker should consider before publishing. It is the static
half of ESS agent hardening (the runtime half is `topics/test`).

> **Advisory by construction.** This review has no power to block. There is no PR or CI gate at the
> authoring stage — the skill surfaces findings and the maker decides. Never present a finding as a
> hard failure or refuse to proceed. This mirrors `evaluations/validate`: a gate, not a blocker.

## Rules

- Do NOT run terminal commands or scripts. Use built-in file reading tools only. This review is
  **agentic**: you read the authored topic and reason about it, guided by the lens instructions.
- Do NOT modify the topic. This skill only reads and reports.
- Operate on the authored `.mcs.yml` in the maker's agent folder (`{agent.folder}/topics/`), i.e. the
  topic **before publish**. Do not require the published `samples/` copy.
- Report findings as **advisory prose**; write nothing to disk.
- **TRACK PROGRESS**: use the todo list tool to track the steps below so the maker can see where you are.

## Scope (current slice)

This slice runs **one lens**: the **topic-local Power Fx** lens. It finds bugs expressed inside the
topic's Power Fx expressions, decidable from the single authored file alone — no preprocessing and no
reference repository required.

Lenses NOT yet wired in (planned for later slices, do not attempt them here): UX-contract (adaptive
cards), logic-and-dataflow, injection-and-auth, hygiene; and the reference-dependent Power Fx checks
(dead/dangling `Global.*`, upstream/downstream error-code coverage) that need the shipped ESS framework.
If the maker asks for those, say they are not in this slice yet.

## Step 1: Identify the topic to review

Determine the target `.mcs.yml`:

- If the maker gave a path, use it.
- Otherwise read `.local/config.json` for the agent folder, list `{agent.folder}/topics/*.mcs.yml`, and
  ask the maker which topic to review (or offer to review the most recently modified one).

State the full path of the file you are about to review.

## Step 2: Read the topic

Read the entire target `.mcs.yml`. Identify every Power Fx expression: any value beginning with `=`, and
the expression bodies inside `AdaptiveCardPrompt.card` and `AdaptiveCardTemplate.cardContent`. Keep track
of line numbers so findings can cite `file:line`.

## Step 3: Analyze the topic (internal reasoning)

Read the analysis guidance at
`src/reference/ess-docs/conformance/powerfx-topic-local.md` and apply every heuristic in it to the
expressions you gathered. Use its precision bar (>=80% confidence), reachability scoring, and severity
mapping to decide which candidates are real findings and how serious each is.

This step is **internal reasoning**. Its rule IDs (e.g. `BTPF-001`), reachability tags
(`REACHABLE_NORMAL_UI`, etc.), and the word "lens" are working vocabulary **for you** — they are NOT
shown to the customer (see Step 4).

## Step 4: Present the advisory report (customer-facing)

Present findings in **plain language**. Do NOT expose internal terminology to the customer — no "lens",
no rule IDs, no reachability tag names, no file-format jargon. Translate severity to plain words
(**High / Medium / Low**). Cite locations as `line N` of the topic.

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

Then a plain findings table:

> **Review — `{TopicName}`** — {verdict}
>
> This is advisory — it won't block publishing.
>
> | # | Severity | Where | Potential issue | Suggested fix |
> |---|----------|-------|-----------------|---------------|
> | 1 | Medium | `line 157` | The flow call may not handle a failure, so an error could show the user nothing | Consider adding a branch that handles the failure case and shows an error message |

Below the table, give each finding a short plain explanation, hedged: what **might** be wrong, why it
**could** matter to the user, and a suggested fix (a Power Fx snippet or YAML edit is fine — that is the
customer's own content, not internal terminology). Order High -> Medium -> Low. Group any "no user impact
today" items under a short **Minor / cleanup** heading so the customer prioritizes the most likely issues
first.

## Step 5: Close

End advisory, never blocking:

> This is advisory — you can publish as-is. Consider addressing the higher-severity items first (use
> `/update` to edit the topic), then re-run `/review` after edits to re-check.

**If invoked as a subagent by a parent flow** (not directly by the customer): skip the plain-language
translation and instead return the **structured** findings — rule IDs, severity, reachability, and sites
from the analysis guidance — so the parent can consume them programmatically. Do not prompt the customer
directly in that case.
