# UI formatting guidelines

This document is the source of truth for maker-facing guidance rendered by ESS Maker Skills. It applies to authoring reviews, decisions and outcomes, portal navigation, setup instructions, remediation, troubleshooting, and any message that asks the maker to perform UI actions.

## Goals

- Make the next action obvious.
- Make instructions easy to scan while the maker works in another window.
- Distinguish destinations, UI controls, selected values, and product names.
- Use known context instead of asking the maker to translate generic guidance.

## Current-state language

No historicity means maker-facing text describes only a current observed fact, a decision the maker must make, an action the maker must take, or a supported outcome. Authoring rationale and UX meta-intentions remain instruction-only: response cadence, narration strategy, template selection, render policy, and commentary about what the conversation will or will not say.

Resolve a UX concern by defining the positive response at its owning boundary:

- successful internal work continues to the next defined maker interaction;
- a required decision uses its defined question and choices;
- a blocked operation states the observed blocker and one supported recovery;
- a completed path uses its defined final handoff.

Terms such as "chatter," "noise," "narration," "render point," "surface," "template," "maker-facing," and "UX" describe authoring policy. They are not setup status, evidence, or instructions for the maker.

## Formatting semantics

Use formatting consistently according to what the text represents:

| Content                                                 | Format        | Example                                         |
| ------------------------------------------------------- | ------------- | ----------------------------------------------- |
| Portal or web destination                               | Markdown link | [Power Apps](https://make.powerapps.com)        |
| Environment, agent, or selected value                   | Code          | `ESS combined`                                  |
| Menu, tab, field, button, command, or keyboard shortcut | Code          | `Connections`, `New connection`, `Ctrl+Shift+P` |
| Product, connector, or service name                     | Bold          | **Microsoft 365 Self-Help**, **Dataverse MCP**  |
| Chat choice the maker must select                       | Bold          | **Check again**                                 |

Do not use bold for portal controls or code formatting for product names merely for emphasis. Formatting conveys meaning, not decoration.

Apply the same semantics inside confirmation questions and picker labels. For example: `Is **Microsoft 365 Self-Help** connected and shared with the \`Employee Self-Service IT\` agent?`

## Procedural guidance

1. Use a numbered list for any sequence of UI actions.
2. Put one action on each numbered line.
3. Start with a clickable destination when a portal must be opened.
4. Identify the environment or agent immediately after opening the portal.
5. Use the exact visible label and casing for every control.
6. End with the action that returns control to the skill, when one is required.

Use actual values from setup state or discovery whenever available. Render a known environment as `ESS combined`, for example, rather than "the target environment." Never show unresolved placeholders such as `{ENVIRONMENT_NAME}` to the maker.

## Native task progress

For topic authoring, deletion, Push, testing and cleanup, use [Status update markers](../skills/topics/experience-contract.md#status-update-markers) and the operation-linked definitions instead of native task progress. Delegated entry points reuse the performing owner's updates. Other operations retain the rules below when their owner calls for native progress.

Use the native todo tool exposed by the current chat, such as `manage_todo_list`. Use its actual schema and supported states; do not assume that another harness exposes the same tool. If no native todo tool is available, continue with the operation's normal previews, decisions and outcome reports. Do not substitute Markdown progress checklists, shell output or a progress-only tool.

Track user-visible milestones, not every file read, command or telemetry call. Resolve titles from the selected topic, agent and approved work; never display unresolved placeholders. Keep stable item IDs and earlier completed milestones within the current request. When the tool replaces the list, send the full current list rather than only changed items.

Mark one item in progress immediately before working on it and mark it completed only when its stated completion condition is observed. Combine save and verification in one milestone when the owning operation returns them together. Do not announce an internal verification phase that has not been observed. Update at meaningful boundaries, not on a timer or after every read.

Add conditional work only after the relevant choice or existing scoped authorization establishes it. A todo is not consent. Finish preparation updates before showing the existing preview and separate decision control; do not leave a preparation item running while waiting for the maker. Do not add a review or approval task that creates another question.

On a pause or failure, preserve completed work and the truthful operation outcome. Do not mark unfinished work completed or invent failed, blocked or cancelled states unsupported by the tool. When work is no longer running, make the remaining action pending with an explicit condition in its title, such as `Verify topic push (outcome unconfirmed)`. Report attempted work and uncertainty in normal chat. On cancellation, remove unattempted work from the active plan and report it as cancelled, not completed.

Native progress supplements the owning outcome report; it never replaces per-component results, local-workspace issues or runtime evidence. Do not duplicate native updates with Markdown snapshots or repeated status messages.

## Progress checklists

Use this Markdown mechanism only when an operation explicitly defines its own progress-checklist Message block, such as foundation setup. Topic authoring, deletion, Push, testing and cleanup use their status update markers instead.

Render a maker-facing progress snapshot as an ordinary, single-level Markdown bullet list. Every item begins with exactly one status emoji in the same position so completed, current, blocked, and pending stages retain one consistent visual shape:

```text
- ✅ Completed stage
- 🔄 Current stage
- ⛔ Blocked stage
- ⬜ Pending stage
```

Keep the full ordered list in every snapshot. The Markdown list is the maker-facing progress surface.

Send each progress snapshot as its own complete chat message. Finish that message before opening the next question or interactive control. The next control begins with its own decision prompt, explanation, and choices.

## Authoring pattern

Use normal chat for open-ended requirements and revisions, not free-text-only structured questions. Keep structured controls for genuine choices. Present summaries and previews in normal chat before a separate short decision control, not inside a long question description.

Template quote blocks contain only literal response/control copy and simple substitution placeholders. Keep definitions, conditions, omission/repetition rules and rendering instructions outside them. Resolve every displayed placeholder from actual context; unresolved information is not an empty section.

Render the contents of an applicable template quote block or exact **Message** block verbatim after resolving its documented placeholders. Preserve wording, labels, punctuation, emphasis, quotation structure, order and paragraph breaks. Apply an owning reference's explicitly defined label treatment. The [topic-workflow presentation contract](../skills/topics/experience-contract.md#presentation-and-scope) uses uppercase level-five fields and nested level-six child labels, while preserving literal response and outcome text. Setup and other operations retain their owning presentation.

Resolve each placeholder according to its binding and insert the resolved value verbatim. Referenced template blocks retain their own copy and bindings. Compose text only where a binding calls for it, such as a behavior description or contextual trailer, and keep that composition within its slot. Apply the documented omission, repetition and conditional-choice rules.

Additional context uses an explicitly templated slot or message. A flexible contextual trailer changes only that slot, not the surrounding template.

When the owning skill supplies no fixed copy, compose UI guidance from runtime context:

1. Link directly to the closest available destination.
2. Identify the selected environment, agent, or other scoped object.
3. Name each UI control required to reach the target.
4. Identify the product, connector, or service being acted on.
5. Describe the required state or action.
6. End with the save, confirmation, retry, or return action.

The steps above describe the structure of composed guidance, not text to display. Keep workflow-specific messages and walkthroughs in their owning skills.

## Avoid

- Dense navigation sentences such as "Open Power Apps, select the environment, go to Connections, and click New connection."
- Raw portal host names when a descriptive Markdown link can be used.
- Vague values such as "the target environment" when the selected value is known.
- Multiple UI actions on one numbered line.
- Arrows as a substitute for a numbered sequence when the maker must switch pages or perform several actions.
- Formatting every noun for emphasis.
- Internal implementation terms, state paths, tool names, or placeholders in maker-facing messages.
- Authoring rationale or UX-policy language presented as setup progress.

## Accessibility and resilience

- Do not rely on color, icon position, or screen position alone.
- Keep sentences short and use descriptive link text.
- Preserve official product names and visible UI labels.
- If a UI label can vary by tenant or release, describe the intent after the most common label rather than inventing an exact label.
- Show only actions that are still required; skip instructions when automated validation proves the task is already complete.

## Maintaining this guideline

Add or refine rules here instead of duplicating them in individual skills. Skill files should reference this document and contain only guidance specific to their workflow. When this contract changes, update its rules and the structural tests that protect required formatting.
