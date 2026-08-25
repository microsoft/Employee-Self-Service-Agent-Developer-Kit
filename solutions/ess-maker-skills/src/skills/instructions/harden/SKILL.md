# Harden Instructions Skill

This skill reviews an agent's **system instructions** (the `instructions:` block in `agent.mcs.yml`) and
proposes changes that reduce two failure modes:

- **Ungrounded answers** — the agent states something its knowledge sources do not support.
- **Over-committing answers** — the agent offers an action, service, or referral that nothing authorized.

It also always checks the instructions for **internal contradictions**, which are worth fixing even when
the agent is behaving well: a rule contradicted elsewhere is not in force, however firmly it is written.

> **Advisory and diff-based.** Every change is shown as exact before-and-after text and applied only after
> the maker approves. Instructions govern every answer the agent gives, so an unreviewed edit here is far
> more dangerous than an unreviewed edit to a single topic.

**All paths in this skill are relative to the solution root** — the folder containing `scripts/`, `src/`,
and `workspace/`. They are not relative to this file.

## Rules

- **Never rewrite the instructions wholesale.** Propose the smallest set of changes that address what was
  actually found. A rewrite is unreviewable — the maker cannot tell an intended change from an incidental
  one — and it discards wording their organization may have chosen deliberately.
- **Do not tighten just because you were invoked.** If the review finds nothing and the maker reports no
  problem, say so and propose nothing (you still finish with Step 10). Adding prohibitions "to be safe"
  causes the agent to refuse questions its sources fully answer, which is a real regression traded for a
  hypothetical one.
- **Anchor every finding to a sentence** — see "Anchoring" below. Never attribute a problem to a sentence
  that did not cause it.
- **Never propose a rule that blocks a supported action.** Establish what the agent supports (Step 5)
  before prohibiting anything.
- **Ask questions in prose, not as menus.** When you are eliciting what the maker has seen or wants
  (Step 2), never present numbered or lettered options to pick from. A picked option is a category, and
  categories are not evidence — you cannot anchor a change to one. Ask the open question and wait for their
  own words. Offering a choice between concrete alternatives you have already drafted (Step 8) is fine;
  that is a decision, not an interview.
- **Never end the run without Step 10.** Every path that reached the analysis — applied, declined, nothing
  found — ends by pointing at `/test` and `/evaluate`. This skill reads text; it cannot show that the
  agent's answers improved. The only exceptions are the Step 1 gates, where there is no agent or no
  instructions to review and the maker is sent to `/setup` instead.
- **Never apply changes without a checkpoint** (Step 9).
- **Do not push.** This skill writes locally. Pushing is the maker's separate, explicit decision via `/push`.
- **Run the analysis silently.** Steps 3–5 are internal. Do not narrate which files you are reading, what
  you are about to check, or what you found until Step 8. Keep progress labels generic — "Reviewing the
  instructions" is fine, "Checking for jurisdiction-scope gaps" is not.
- **Speak the maker's language.** Never show `INSTR-*` ids, the filenames of this skill's own reference
  material, or the words "detector", "rule pack", or "probe". Describe findings in plain language. The
  maker's own instruction wording is *their* language and is shown verbatim.
- **Recommend, don't disqualify.** Do not tell the maker which commands are *not* right for their
  situation, or why — that is this skill's routing logic, not their next step, and it reads as hedging.
  This is not a limit on how many commands you name: when a path needs both `/push` and `/evaluate`, give
  both, in order.
- **TRACK PROGRESS**: Use the todo list tool to track your progress through this skill's steps. Create a
  todo list at the start with all the steps, mark each in-progress as you start it, and mark completed when
  done. Update it as you go rather than at the end — several steps here wait on the maker's reply, and a
  list that never moves gives them no idea whether you are working or waiting. If you loop back (Step 8 to
  Step 6), reopen that step rather than leaving it complete.

## Anchoring

Instruction blocks are usually a handful of enormous paragraphs — a single "line" can run past 1,000
characters. Quoting a whole paragraph to justify a nine-word change produces a proposal no one can review.

- **Anchor to the sentence**, not the physical line or the paragraph.
- **A bullet, a heading, or a standalone fragment counts as one unit** even when it is not a grammatical
  sentence. Split on what the maker would recognize as a single rule, not on punctuation.
- **Quote only the sentence you are changing**, plus at most a few words either side if the change would
  otherwise be ambiguous.
- **For a missing safeguard, do not pick a "guilty" sentence.** Say plainly that nothing in the
  instructions constrains the behavior, and name where the new rule would go — for example "in the same
  paragraph as the existing restrictions". Inventing a culprit misleads the maker about their own text.

## What this checks and what it does not

This skill reads the **instructions text** and the agent's **topic and workflow inventory**. It **cannot**
see the agent's knowledge sources, and it cannot tell you whether the agent actually produces a bad answer
— retrieval quality, knowledge-source coverage, and the underlying model matter at least as much.

Say this plainly when it is relevant. A maker whose agent gives ungrounded answers because a knowledge
source is not being retrieved will get no benefit from tighter instructions, and letting them believe
otherwise costs them the time they should have spent on retrieval. Two signals that instructions are the
wrong lever:

- the agent answers correctly when the maker pastes the source content into the chat, but not otherwise;
- the agent says it cannot find information the maker knows is in an attached source.

Both point at knowledge-source configuration. Route those makers to `/flightcheck` and `/troubleshoot`
rather than editing instructions.

## Step 1: Resolve the agent

Read `.local/config.json`. The active agent's folder is `agent.folder` — a path relative to the solution
root, e.g. `workspace/agents/<slug>`. The instructions are the `instructions:` block of
`{agent.folder}/agent.mcs.yml`.

If the file is missing, tell the maker their agent has not been extracted yet and to run `/setup`, then STOP.

If the `instructions:` block is missing or empty, say so and STOP — there is nothing to harden, and this
usually means the agent's instructions were never configured rather than that they are safe.

## Step 2: Ask what the maker has actually seen

Ask before analyzing. What the maker has observed is better evidence than anything derivable from the text,
and it determines whether Step 6 proposes changes or only reports.

**Ask in plain prose. Do not offer numbered options, lettered choices, or a menu to pick from.** The
answer you need is the maker's own description of what went wrong; a menu invites them to pick a category
instead, and a category tells you nothing you can anchor a change to. Ask this as a single open question:

> Before I look at your instructions — have you seen specific answers from your agent that you didn't like?
>
> If you can paste one or two, that helps most: the exact question and what the agent said. Otherwise, tell
> me the kind of answer you want to prevent — for example, making claims your documents don't cover, or
> offering to do things the agent can't actually do.
>
> If nothing specific has gone wrong, that's fine too — say so and I'll check the instructions for
> contradictions and gaps and tell you what I find.

**If the answer names a category rather than a behavior, you do not have an answer yet — ask again.**
"General concerns", "the usual problems", "hallucination", or picking one of your own examples back are
labels, not evidence. Follow up in prose — *"What has it been doing that concerns you?"* — and wait. Do
not proceed to Step 3 on a label. A proposal built from a category is a proposal built from nothing, and
it will read as generic hardening because that is what it is.

Record their answer. Do not paraphrase a vague answer into a specific complaint — if they said "it makes
things up sometimes" without an example, you have a **theme**, not a case, and Step 6 treats those
differently. Wanting the agent "locked down" before a rollout is not a reported problem; it is branch B.

## Step 3: Read the instructions and the reference guidance

Read the full `instructions:` value and `src/reference/ess-docs/hardening/instruction-rules.md`.

Split the instructions into numbered **sentences** so findings can be anchored precisely (see "Anchoring").
Keep the maker's original wording, spelling, and casing exactly — you will quote it back and diff against it.

## Step 4: Contradiction pass (always runs)

Apply Part 1 of the reference guidance (`INSTR-001` … `INSTR-005`) to the **current** instructions. This
pass runs regardless of the maker's answer in Step 2, and it runs here — before any proposal exists — so
that what you find describes the maker's text rather than your own.

A second contradiction pass runs in Step 6 against the proposed text. Hardening adds prohibitions to a
document that already has rules, which is precisely how contradictions get created.

**Threshold.** Report a contradiction only when you can state a **concrete request** where the two rules
demand different behavior and both cannot be satisfied. Tone guidance and grounding rules coexisting is not
by itself a contradiction — "be warm and authoritative" and "don't answer without enough information" are
routinely satisfiable together. Without this bar you will manufacture a conflict to justify the run.

For each contradiction, record **both** sentences. Do not decide which one is "right": the maker knows which
behavior they intended. In Step 8 you present the conflict and the options, and let them choose.

## Step 5: Grounding and over-commitment pass

Apply Parts 2 and 3 of the reference guidance (`INSTR-010` … `INSTR-022`).

Where the maker gave specific bad responses in Step 2, work backward from each one: identify which sentence
*permitted* it, or state that nothing constrains it. A missing safeguard is a valid finding — anchor it as
described under "Anchoring".

**Establish what the agent supports before writing any capability rule.** Run:

```
python scripts/list_agent_capabilities.py --agent {agent.folder}
```

This lists every topic with what the model is told it handles and whether it merely replies or invokes a
flow, connector, or HTTP call, plus the workflow inventory. Use it — do not read the topic tree by hand. A
stock agent has dozens of topics, several of them large generated files, so reading them is both expensive
and unreliable, and a capability conclusion drawn from a sample is exactly how a supported action gets
prohibited. Open an individual topic only when the inventory is genuinely ambiguous about a capability you
are about to write a rule for.

Note the distinction the inventory draws: a topic that *answers about* something is not the same as a topic
that *does* it. "Look up leave balance" and "submit a time-off request" are different capabilities.

The inventory lists workflows by name only, and a name like "create case" does not reveal what the workflow
actually does or who calls it. If a capability rule depends on a workflow's behavior, ask the maker rather
than inferring it from the name.

For any finding where an existing rule already targets the reported behavior **by listing forbidden
phrases**, record that the mechanism itself failed. Phrase lists are evaded by rewording; the replacement
must prohibit the *function* — offering, asserting, referring — and say that rephrasing does not exempt it.

## Step 6: Decide what to propose

Branch on Step 2:

**A — the maker described specific responses or a specific behavior.**
Propose targeted changes for those, plus any contradictions from Step 4. Every proposed change must trace to
either a reported behavior or a contradiction. Do not append unrelated hardening because the file happened
to be open.

**B — the maker reported nothing specific.**
Propose fixes only for **contradictions** (Step 4) and for rules that are **internally inconsistent or
vacuous** (`INSTR-004`, `INSTR-005`). Report the grounding and over-commitment findings from Step 5 as
observations with the risk each carries, and ask whether the maker wants any of them addressed. Do not
propose those changes pre-approved. Reporting risks and proposing nothing is a **legitimate and complete
outcome** of this branch — it is not a failed run.

**A theme is branch A, narrowly.** "It makes things up about benefits" or "it offers to do things it
can't" names a behavior class without an example. Treat it as branch A but scope every change to that
class, and say in Step 8 which findings you addressed because they match the theme and which you are only
reporting. Without an example you cannot confirm the instructions caused it, so present the change as your
best reading rather than a diagnosis.

Worth saying to the maker if they push back: prohibitions have a cost. Each one makes the agent more likely
to decline a question it could have answered, and without a reported problem there is nothing to weigh that
cost against.

**Before finalizing any proposal**, run the Step 4 contradiction pass again — this time against the
**candidate as a whole**: your new and amended sentences read together with every original sentence you are
leaving in place. Use the same threshold. A new prohibition frequently collides with a rule that stays
behind: "never offer a next step" against an existing "always end by offering further help", or "answer
only from retrieved content" against an existing instruction to fall back on general knowledge.

When the candidate contradicts a surviving rule, **amend or remove that rule as part of the same
proposal**. Do not stack a stricter rule on top and rely on it winning — that is the failure this skill
exists to catch, and you would be introducing it. Show the surviving rule you changed in Step 8 alongside
the rest, so the maker approves that removal explicitly rather than discovering it later.

Then check the proposal against Part 4 of the reference guidance (`INSTR-030` … `INSTR-033`):

- every prohibition states what the agent should do instead;
- the proposal as a whole includes a sentence stating the prohibitions restrict invention, not helpfulness
  — this sentence is part of proposing safely and is required even in a narrowly scoped theme run;
- nothing prohibits a capability the Step 5 inventory shows the agent has.

**One caveat you cannot resolve alone:** you cannot see the knowledge sources. If a proposed rule would ban
referrals to outside organizations, ask the maker whether any external resource — an employee assistance
program, a benefits carrier, an ombudsman — is deliberately endorsed in their content, and carve it out.
A blanket ban can contradict their own approved material.

## Step 7: Check the character budget

**If Step 6 produced no proposal, skip this step and go to Step 8.** There is nothing to measure, and
building a candidate identical to the current instructions only creates a file to clean up.

Instructions have a length ceiling in Copilot Studio, and hardening usually lengthens them, so measure the
complete candidate rather than estimating the delta.

Create `.local/harden/` if it does not exist, write the proposed **full** instructions to
`.local/harden/candidate.txt`, then run:

```
python scripts/check_instruction_budget.py --agent {agent.folder} --candidate .local/harden/candidate.txt
```

Read the `###INSTRUCTION_BUDGET_JSON###` line. **Its verdict is authoritative — do not estimate the length
yourself and do not override it.**

- `ok` — proceed.
- `tight` — proceed, and tell the maker how little room is left. Do **not** cut further wording just to
  reach `ok`; deleting the maker's text to buy headroom they did not ask for is its own regression.
- `over` — **do not present the proposal as-is.** Identify what to remove and propose that too. Prefer
  removing permissive or vacuous sentences (`INSTR-004`, `INSTR-011`, `INSTR-022`) — removing a sentence
  that invites the bad behavior is usually worth more than the prohibition you were trying to add. Re-run
  until the verdict is `ok` or `tight`.

The default limit is this kit's working assumption, not a verified platform constant. If the maker knows
their real ceiling, pass it with `--limit`.

If you finish the run without applying anything — the maker declines, defers, or you had nothing to propose
— delete `.local/harden/candidate.txt`. A stale candidate is worse than none: a later run can measure or
present the wrong proposal.

## Step 8: Present the proposal and get approval

Present, in this order:

1. **What you found**, in plain language, contradictions first, then risks. Quote the maker's own sentence
   for each; for a missing safeguard, say nothing constrains the behavior rather than blaming a sentence.

   Only attribute wording to the shipped template when it matches the marker text listed in Part 6 of the
   reference guidance. Otherwise say nothing about where it came from — a wrong attribution either blames
   the maker for product text or excuses text they wrote themselves.

2. **What you propose to change**, as before-and-after pairs at sentence granularity:

   > **Currently:** "{the exact sentence being changed}"
   > **Proposed:** "{the exact replacement}"
   > **Why:** {one or two sentences tied to what this prevents}

   For a removal, quote the sentence and say what removing it changes. For an addition, quote nothing —
   show the new sentence and say where it goes. **Never paste an entire paragraph** to show a small edit.

   For a contradiction with no obvious winner, present both directions as options and ask which behavior
   they intended, rather than choosing for them.

3. **The checks you ran on the proposal**, in one or two lines alongside each other:

   - **Contradictions**: state the result of the Step 6 re-check explicitly — that you read the proposed
     text against the rules staying in place, and either that nothing conflicts or which surviving rule you
     had to amend. Say this even when the answer is "none". The maker cannot see that this check happened,
     and a silent pass is indistinguishable from a skipped one — which is the exact failure this skill
     exists to catch, so leaving it implicit undermines the result.
   - **Length**: the new total and the remaining headroom.

   > Checked the new wording against the rules that stay in place — no conflicts. Length: 3,140 of 8,000
   > characters, 4,860 to spare.

4. **What this does not cover**: instructions do not fix a knowledge source the agent cannot retrieve. If
   the maker's reported examples looked like retrieval problems (see "What this checks"), say so here.

Then ask for approval. The maker may accept all, accept some, or decline. Apply exactly what they accept.

If there is nothing to propose, say so directly — do not manufacture a finding to justify the run — and go
to Step 10. If you have risks but nothing to propose (branch B), present the risks, ask whether they want
any addressed, and go to Step 10; that is a complete outcome. Do not end the conversation here on any path.

**If a branch-B maker asks for one of the reported risks to be addressed**, that risk becomes a reported
problem. Return to Step 6 and draft a proposal for the risks they named and nothing else, re-run the
candidate contradiction check and Step 7, and come back here to present it. Do not draft it in the same
message you asked the question in — you would be pre-approving the change you just said you would not.

## Step 9: Apply

Only after explicit approval:

```
python scripts/checkpoint.py "pre-harden-instructions"
python scripts/emit_capability.py harden
```

The `emit_capability.py` line records anonymous usage telemetry (best-effort, non-blocking); it needs no
user-facing message and never fails the step.

Then edit the `instructions:` block in `{agent.folder}/agent.mcs.yml`, changing only the approved sentences.
Preserve the YAML block scalar style and the indentation of the surrounding file.

Preserve **exactly** any `{System.Bot.Components.Topics...}` references or other placeholder tokens in the
instructions. These are live references, not example text — rewording one silently breaks the behavior it
drives.

If the maker accepted only part of the proposal, rebuild the candidate from what they accepted and re-run
the Step 7 check before writing. The measurement of a proposal they did not take does not describe the file
you are about to write.

Re-run the budget check without `--candidate` to confirm the written file measures as expected, then delete
`.local/harden/candidate.txt`.

**Say where the change landed.** "I updated `agent.mcs.yml`" reads as done, and a maker who believes the
change is live will stop watching for the behavior they reported. State that this is a local file:

> I've updated your local copy of the agent. Your agent in Copilot Studio is still running the previous
> instructions.

Leave it there — Step 10 gives the instruction to push. Do not write the two messages as separate
paragraphs saying the same thing.

## Step 10: Hand off to validation

**This step always runs — after applying, after a decline, and after a run that proposed nothing.** It is
the last thing the maker sees. Do not end the conversation on a diff, on "done", or on a summary of
findings.

Instruction changes are behavioral changes, and this skill has no way to demonstrate that the new text
produces better answers. Say that plainly and route the maker onward.

**Internal — do not say any of this to the maker.** `/push` writes the local `agent.mcs.yml` to Copilot
Studio through Dataverse. It does **not** publish the agent: the change lands in the agent's draft, which is
what the Copilot Studio test pane answers from, while published channels keep serving the previous
instructions until the maker publishes. `/test` drives that test pane — it sends a prompt and captures the
reply — so it is the command that shows whether the new instructions changed the answers. A pushed
instruction change is not always visible immediately; the runtime can serve a cached definition for several
minutes. Neither command reads the local `agent.mcs.yml`, which is why the push comes first. Name only the
command you are recommending. A maker who is told which commands *not* to use has been handed your
reasoning instead of a next step.

**If changes were applied:**

The applied path **must** name `/push`, as its own instruction, before anything about testing. This is
the only command that makes the change real, and it is the one most easily lost when it is bundled into a
paragraph about testing. Do not merge it into the `/test` sentence, and do not leave it implied.

> Two things to know before you check whether this worked.
>
> The change is in your local copy only — your agent in Copilot Studio is still running the previous
> instructions. **Run `/push` to send it.** That updates the agent in Copilot Studio but does not publish
> it, so anyone using the published agent keeps the previous instructions until you publish.
>
> Then run `/test` and ask the questions that produced the answers you didn't like. It drives your agent
> and shows you the actual replies, which is the only way to see whether the new instructions changed the
> behaviour. A pushed change can take a few minutes to reach the test pane — if you still see the old
> behaviour, wait and ask again before concluding it didn't work.

Where the maker gave specific bad responses in Step 2, carry them forward: those are the highest-value
probes available, and they are the only direct evidence of whether this pass worked. Offer to run `/test`
with them.

Also mention, once, that a change intended to prevent a bad answer can also cause the agent to decline good
questions — so the questions asked should include a few normal, in-scope ones alongside the failing ones.
Without those, an agent that has started refusing everything still looks fixed.

**If the maker declined or deferred the proposal:**

> Nothing has changed, locally or in Copilot Studio. If you want to find out whether the behaviour I
> described actually shows up, `/test` drives your agent so you can ask the questions directly — that
> gives you a baseline before changing anything.

**If nothing was proposed:**

> I didn't find anything worth changing in the instructions. That doesn't mean the agent answers well —
> instructions are only one input, and knowledge sources and topics matter at least as much.
>
> `/test` drives your agent so you can ask the questions that concern you and see the actual replies. That
> finds behaviour problems this review cannot see.

Reading the instructions cannot tell you what the agent actually says. Do not let a clean review stand as
evidence that the agent is fine.

## References

- `src/reference/ess-docs/hardening/instruction-rules.md` — contradiction classes, grounding and
  over-commitment risks, over-restriction risks, rewriting principles, and the shipped-template markers.
- `scripts/list_agent_capabilities.py` — topic and workflow inventory (Step 5).
- `scripts/check_instruction_budget.py` — character-budget measurement (Step 7).
