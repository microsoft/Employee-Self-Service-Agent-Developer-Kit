# Analyzing scenarios against the tools

Read in Round 3. For each scenario, decide from the tool descriptions and the agent's knowledge sources how much the skill must carry. Don't start from a label for the whole agent: one server can have a purpose-built tool for one scenario and only building blocks for the next, so decide step by step, scenario by scenario.

## Contents

- Read the tools
- Read the knowledge sources
- Break each scenario into steps
- Judge each scenario
- Plan the skills
- When the maker's request conflicts with the evidence
- Worked examples
- Signs the analysis was wrong

## Read the tools

Read the full description and input schema of every tool a scenario might use (`inventory.json` has both), not only its name. For each, note:

- What it does end to end, and for which entity or process.
- What it decides on its own: lookups, defaults, validation, a form the user reviews.
- What the caller must supply: a table or entity, field names, a query, values, an order of calls.
- Rules it states ("never", "only", "the user must"), and who it acts as.

The inventory's `kind` and `operations` are hints from names and schemas; the description decides. A tool named `update_record` may accept only some tables; a tool named `create_case_form` may look up services itself.

## Read the knowledge sources

The inventory's `knowledge` section lists the agent's `capabilities`: knowledge sources (SharePoint and OneDrive, Copilot connectors, web search and others) and how far the manifest limits each. Policy, process, how-to and eligibility questions are answered from these sources, not from tools.

You can see which sources are enabled, not what they contain, and you can't search them while building. When a scenario depends on an answer from knowledge, ask the maker whether it's there. A ServiceNow or similar knowledge-article tool is a tool, not the agent's knowledge search; use it only when its description says what it's for.

## Break each scenario into steps

List the steps a person would take: find, choose, collect input, confirm, change, verify, report. For each step, judge the fit of the best tool:

| Fit            | What the description shows                                                                                        | What the skill must carry for the step                                                                                       |
| -------------- | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Purpose-built  | The tool does the whole step for this scenario's entity or process, including its own lookups or form              | When to call it, which arguments to fill from the user's words, and its boundaries. Nothing the description already says     |
| Building block | The tool works on any record or data, and the caller supplies the table or entity, fields, query, values or order | The domain knowledge: where the data lives, field names and codes, defaults, call order, validation, how to verify the result |
| Partial        | A tool covers part of the step (it creates but can't set a required field; it reads but can't filter)            | What the tool covers, and what the user is told about the rest                                                               |
| None           | No tool can do the step                                                                                           | Nothing: the step is a gap                                                                                                   |

An informational step (what's the policy, how does it work, am I eligible) is **Knowledge** when the agent has a knowledge source that should hold the answer, and **None** when it has none. For a Knowledge step the skill carries which questions go to knowledge search, which of the user's details to add to the search (country, role) when the answer depends on them, and what to say when nothing is found.

Record each step, its tool and arguments, its fit and what the skill must carry in the capability map in `plan.md`.

## Judge each scenario

- **Achievable:** every required step is purpose-built, or a building block whose domain facts you can ground (Round 5).
- **Partly achievable:** some required steps are partial or missing. The skill can promise only what's covered.
- **Not achievable:** the core step (the change itself, or the data the user needs) has no tool.

A building-block scenario whose facts nobody can provide (which table, which required fields) is not achievable in practice: the model would guess. Ask the maker for the facts, or treat the step as missing.

The mix of fits sets the skill's weight. Mostly purpose-built steps make a thin skill: routing, argument mapping, boundaries and reply style. Mostly building blocks make a thick, focused skill that carries the procedure and the facts. Also note how many calls a routine request takes; five or more is slow for users.

## Plan the skills

Group the scenarios into skills using the analysis:

1. Scenarios whose steps are mostly purpose-built tools in one area go in **one area skill** that routes between those tools. When that routing fits in a few lines and slots are short, suggest the agent's instructions instead of a skill.
2. Scenarios that rely on building blocks get **one skill per scenario**, or per tight group that shares data, steps and success criteria. Each carries its own facts. Mechanics several of them share (query syntax, finding a person, confirmation, error handling) go in one **shared rules skill** that the others name.
3. A scenario with a purpose-built form but building-block lookups: the form makes the change; the skill carries only the lookups the form doesn't do.
4. **Split** partly achievable scenarios: build the achievable part, and leave the rest out until a tool exists. Never put an intent the tools can't serve in a skill's description: it makes the skill load, and the skill then fails the user.
5. Don't build not-achievable scenarios. Tell the maker which capability is missing.
6. Merge scenarios that share triggers, inputs and success criteria. Split when one description would have to cover unrelated intents.
7. When people often combine requests in one message (a policy question plus an action, several unrelated asks, or "if I'm eligible, apply"), and the plan has knowledge steps plus actions or two or more area skills, recommend one **orchestration skill**. It separates the intents, routes each to knowledge search or the right area skill, orders dependent steps, asks only what blocks the next step, shows one widget per turn and reports every outcome. It names the area skills and never repeats their steps. Ask **Mixed requests** to find out whether it's worth a slot; when it isn't, a short routing rule in the agent's instructions is enough. `examples.md` shows the pattern.
8. An agent has 8 skill slots. When the plan needs more, merge the thinnest skills, move simple routing into instructions, or ask the maker which scenarios come first.

Name each skill by what users want (`hr-case-create`, `my-time-off`), not by vendor or tool, so a provider change edits the body and never the triggering.

## When the maker's request conflicts with the evidence

Show the evidence (which steps, which tools, what's missing), recommend, and let the maker decide. Use the matching message, then ask **Plan** (in `interview.md`).

**Broad skill asked for, but the steps use building blocks.**

**Message:**

The tools for {AREA} are general-purpose: they can create and read any record, so the skill itself has to say where each kind of request lives, which fields to fill and in what order. One skill for all of {AREA} would have to carry that for every scenario, which makes it long, and the agent starts guessing. I recommend one focused skill per scenario ({SCENARIOS}), plus one shared skill for the rules they have in common.

**End message.**

**Narrow skills asked for, but purpose-built tools do the work.**

**Message:**

Your agent already has tools built for {SCENARIOS}, and their descriptions cover how to use them. Separate skills would mostly repeat those descriptions and use {N} of your 8 skill slots. I recommend one skill for {AREA} that tells the agent which tool fits which request{INSTRUCTIONS_OPTION}.

**End message.**

Replace `{INSTRUCTIONS_OPTION}` with ", or a few lines in your agent's instructions" when the routing is that short; otherwise leave it empty.

**Some scenarios aren't achievable.**

**Message:**

The connected tools can do {ACHIEVABLE}, but not {NOT_ACHIEVABLE}, because {MISSING_CAPABILITY}. I recommend building the skill for what works now and leaving the rest out, so the agent doesn't offer something it can't finish.

**End message.**

**More skills than free slots.**

**Message:**

This plan needs {NEEDED} skills, and your agent has {FREE} free slots out of 8. {RECOMMENDATION}

**End message.**

## Worked examples

**HR cases with purpose-built tools.** The tools include an HR case form that looks up HR services itself, a list of the user's cases with filters, and an update tool with a `work_note` field. Every step is purpose-built, so one thin `hr-cases` skill maps intents to tools ("open a case" opens the form prefilled; "add a note" confirms the text, then updates), and states boundaries (employees can't reassign cases; closed cases can't change). It carries no tables or field codes.

**HR cases with building blocks.** The tools are `list_records`, `get_record`, `create_record` and `update_record` for any table. Creating a case needs the HR service lookup, the service's table, people lookups, field names and a default priority, all from the skill. Viewing, creating and updating differ in triggers and steps, so they become three focused skills (`hr-case-create`, `hr-case-update`, `hr-cases-view`) plus a shared rules skill for query syntax and confirmation.

**A partly achievable request.** The maker wants "an HR ticketing skill" that creates, updates and comments on cases. The tools can create and read cases but nothing can change one. Build case creation and viewing; leave updates and comments out of every description, and tell the maker an update tool is missing.

**Mixed requests across knowledge and actions.** The agent has a SharePoint HR site and a Copilot connector for knowledge, plus case, catalog and Workday tools, and the plan has three area skills. Employees often write "what's the parental leave policy, and open a case about my payslip". Each area skill handles its own part, but nothing decides the order, keeps the policy answer separate from the case, or stops the agent opening two forms at once. Recommend one orchestration skill, modeled on `hr-request-orchestration`, that splits and routes such messages, and keep it out of single-intent requests.

## Signs the analysis was wrong

Check these after Round 8:

- The skill repeats what a tool description already says: the steps were purpose-built; cut the skill down.
- The model guesses table or field names: building-block steps lack facts; add them, or ask for a purpose-built tool.
- Two skills load for the same message: overlapping descriptions; merge, or sharpen both boundaries.
- A routine request takes five or more calls: consider a purpose-built tool or a form, and note the latency in `plan.md`.
- Compound messages drop a part, answer a policy question with a record, or open two widgets: consider an orchestration skill.
