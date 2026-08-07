# UI formatting guidelines

This document is the source of truth for maker-facing guidance rendered by ESS
Maker Skills. It applies to portal navigation, setup instructions, remediation,
troubleshooting, and any message that asks the maker to perform UI actions.

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

Do not use bold for portal controls or code formatting for product names merely
for emphasis. Formatting conveys meaning, not decoration.

Apply the same semantics inside confirmation questions and picker labels. For
example: `Is **Microsoft 365 Self-Help** connected and shared with the
\`Employee Self-Service IT\` agent?`

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
