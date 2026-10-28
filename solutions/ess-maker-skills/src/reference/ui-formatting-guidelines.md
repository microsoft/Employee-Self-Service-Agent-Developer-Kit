# UI formatting guidelines

This document is the source of truth for maker-facing guidance rendered by ESS
Maker Skills. It applies to planning, role assignment, portal navigation, setup,
remediation, troubleshooting, and every user-facing next-step handoff.

## Goals

- Make the next action obvious.
- Make instructions easy to scan while the maker works in another window.
- Distinguish destinations, UI controls, selected values, and product names.
- Use known context instead of asking the maker to translate generic guidance.

## Formatting semantics

Use formatting consistently according to what the text represents:

| Content | Format | Example |
| --- | --- | --- |
| Portal or web destination | Markdown link | [Power Apps](https://make.powerapps.com) |
| Environment, agent, or selected value | Code | `ESS combined` |
| Menu, tab, field, button, command, or keyboard shortcut | Code | `Connections`, `New connection`, `Ctrl+Shift+P` |
| Product, connector, or service name | Bold | **Microsoft 365 Self-Help**, **Dataverse MCP** |
| Chat choice the maker must select | Bold | **Check again** |
| Recommended next action | Bold action sentence beneath a heading | **Assign people to the rollout roles.** |

Do not use bold for portal controls or code formatting for product names merely
for emphasis. Formatting conveys meaning, not decoration.

Apply the same semantics inside confirmation questions and picker labels. For
example: `Is **Microsoft 365 Self-Help** connected and shared with the
\`Employee Self-Service IT\` agent?`

## Next-step handoffs

When handing control back to the maker, make the next action prominent, not a
buried sentence at the end of a paragraph. This applies to creation, review,
sharing, activation, assignment, task completion, status, and recovery.

1. First state the verified outcome briefly. Name what actually completed:
   activating a plan is not completing a rollout task or deploying ESS.
2. Start a separate `## Your next step` section, with blank lines around it.
   Render a real Markdown heading, not a bullet, blockquote, or code block.
3. On its own line, **bold the action itself**, not just the words "next step".
   Use a short imperative naming the work, such as assigning rollout owners.
4. Give at most one short sentence explaining why it matters or what is blocked.
5. Put the continuation on its own line: **Say:** with a copyable natural-language
   prompt, **Run:** with a supported command in code, or **Open:** with a
   descriptive link. For genuinely missing input, use **Reply:** and name the
   information needed; do not fill in a fictional person, system, or decision.

Choose one primary action for the person asking, from the current state.
Refresh it after progress; do not repeat a finished action or assign someone
else's work to the requester. Put secondary links or team context before this
section, not after it. If the person has no action, use the same prominent
section to say **No action is needed from you right now.** Name any real handoff
or waiting condition, without manufacturing a task or continuation prompt.

The first plan may instead show a short `## Next steps` roadmap: bold each action,
put its **Prompt:** on a separate line, and distinguish what to do now from what
follows sharing or happens after activation. Do not repeat that whole roadmap
after every update. A displayed prompt is not permission to execute it.
Do not add a handoff block to internal progress messages or interrupt an
already-requested workflow merely to show a next step.

## Questions that need the maker

**The main chat owns questions** about identity, choices, and approval. If work is
delegated to a subagent, it must return the missing question and verified progress
to the main chat instead of trying to collect the user's answer itself. Reuse
confirmed context before asking; ask only for what is actually missing.

A question result saying "user is not available", an unavailable question tool,
or an empty response is **not an answer** and **not consent**. It is not the
maker choosing a default or choosing to defer. Do not choose a person, tenant,
environment, permission, or destructive action from a "pragmatic option" fallback.

If a delegated question could not reach the maker, ask it once in the main chat
using the host's interactive question tool. Respect an explicit cancellation or
decline; do not re-ask it as though the tool failed. If the tool is also unavailable, expose
the missing input with the next-step handoff above and wait for a real reply;
do not retry the unavailable question in a loop. Preserve the unfinished action
without calling it completed. Continue only independent work that does not need
the missing answer; never bypass identity, permission, or approval gates.

## Procedural guidance

1. Use a numbered list for any sequence of UI actions.
2. Put one action on each numbered line.
3. Start with a clickable destination when a portal must be opened.
4. Identify the environment or agent immediately after opening the portal.
5. Use the exact visible label and casing for every control.
6. End with the action that returns control to the skill, when one is required.

Use actual values from setup state or discovery whenever available. Render a
known environment as `ESS combined`, for example, rather than "the target
environment." Never show unresolved placeholders such as
`{ENVIRONMENT_NAME}` to the maker.

## Authoring pattern

Compose UI guidance from the runtime context rather than copying a stored
walkthrough:

1. Link directly to the closest available destination.
2. Identify the selected environment, agent, or other scoped object.
3. Name each UI control required to reach the target.
4. Identify the product, connector, or service being acted on.
5. Describe the required state or action.
6. End with the save, confirmation, retry, or return action.

The steps above describe structure, not text to display. Each owning skill must
generate its instructions from the controls and values relevant to that
workflow. Do not add complete popup messages or workflow walkthroughs to this
document.

## Avoid

- Dense navigation sentences such as "Open Power Apps, select the environment,
  go to Connections, and click New connection."
- Raw portal host names when a descriptive Markdown link can be used.
- Vague values such as "the target environment" when the selected value is
  known.
- Multiple UI actions on one numbered line.
- Arrows as a substitute for a numbered sequence when the maker must switch
  pages or perform several actions.
- Formatting every noun for emphasis.
- Internal implementation terms, state paths, tool names, or placeholders in
  maker-facing messages.

## Accessibility and resilience

- Do not rely on color, icon position, or screen position alone.
- Keep sentences short and use descriptive link text.
- Preserve official product names and visible UI labels.
- If a UI label can vary by tenant or release, describe the intent after the
  most common label rather than inventing an exact label.
- Show only actions that are still required; skip instructions when automated
  validation proves the task is already complete.

## Maintaining this guideline

Add or refine rules here instead of duplicating them in individual skills.
Skill files should reference this document and contain only guidance specific
to their workflow. When this contract changes, update its rules and the
structural tests that protect required formatting.
