# Sources

The external guides behind this skill's rules, in target-platform-first order. Read one when the maker asks where a rule comes from, or when you need more detail than the other references give.

1. **Microsoft 365 Copilot documentation first:** authoritative for supported capabilities, platform limits, packaging and documented runtime behavior. Use Copilot Studio documentation only for the host and authoring experience it describes; do not assume every Microsoft host has the same behavior.
2. **Agent Skills specification and best-practice guides next:** the format, portable conventions and authoring practices, applied within the target host's documented constraints.
3. **Anthropic and OpenAI authoring guides after that:** transferable techniques, not evidence that Claude, ChatGPT, Codex or API-host capabilities exist in Copilot.

If portable guidance assumes an unsupported capability, adapt or omit it. Keep **Observed** findings from ESS testing separate from documented requirements: they inform safeguards, not platform guarantees. `limitations.md` records their status. When documentation and testing disagree, report the discrepancy rather than treating an observation as a new platform contract.

## Contents

- Microsoft 365 Copilot declarative agents
- Copilot Studio
- Agent Skills open standard
- Anthropic
- OpenAI
- Model Context Protocol

## Microsoft 365 Copilot declarative agents

- [Skills in declarative agents](https://learn.microsoft.com/microsoft-365/copilot/extensibility/declarative-agent-skills): support matrix, file types, script sandbox, sensitivity and storage. The main source for `limitations.md`.
- [Add skills in Agent Builder](https://learn.microsoft.com/microsoft-365/copilot/extensibility/agent-builder-add-skills): the `.zip` package and upload steps.
- [Add skills with Microsoft 365 Agents Toolkit](https://learn.microsoft.com/microsoft-365/copilot/extensibility/build-declarative-agents-add-custom-skills): `atk add skill`, the `TEAMSFX_AGENT_SKILLS` setting and manifest version 1.9.
- [Write effective instructions for declarative agents](https://learn.microsoft.com/microsoft-365/copilot/extensibility/declarative-agent-instructions): how agent instructions should refer to skills.
- [MCP apps in Microsoft 365 Copilot](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-mcp-apps): widgets rendered by MCP tools.
- [User experience guidelines for MCP apps](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-mcp-apps-ui-guidelines): how widget replies and forms should behave.
- [Plugin manifest schema 2.4](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-manifest-2.4): MCP server runtimes, functions and confirmation settings such as `isNonConsequential`.

## Copilot Studio

These pages cover Copilot Studio agents built with the GitHub Copilot harness, which also accept uploaded skills.

- [Create a skill for an agent](https://learn.microsoft.com/microsoft-copilot-studio/agents-experience/skills-create): creating from blank or generating with AI.
- [Add and manage an uploaded skill](https://learn.microsoft.com/microsoft-copilot-studio/agents-experience/skills-add-existing): accepted formats and why a skill is skipped at load time.

## Agent Skills open standard

- [Agent Skills overview](https://agentskills.io/home): what skills are and the general loading model; Microsoft documentation determines Copilot support.
- [Specification](https://agentskills.io/specification): folder layout, front matter fields and their limits. Read for any naming or structure question.
- [Quickstart](https://agentskills.io/skill-creation/quickstart): a first skill end to end.
- [Best practices for skill creators](https://agentskills.io/skill-creation/best-practices): scoping, calibrating detail, gotchas, starting from real expertise. Read before drafting.
- [Optimizing skill descriptions](https://agentskills.io/skill-creation/optimizing-descriptions): writing descriptions that trigger, and trigger evals with train and validation sets.
- [Evaluating skill output quality](https://agentskills.io/skill-creation/evaluating-skills): eval-driven iteration, assertions, grading, baselines.
- [Using scripts in skills](https://agentskills.io/skill-creation/using-scripts): when a script helps and how to design one.
- [How to add skills support to your agent](https://agentskills.io/client-implementation/adding-skills-support): general host discovery, loading and activation patterns; not evidence of Copilot's implementation or why a particular skill was not read.

## Anthropic

- [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview): progressive disclosure and how skills load.
- [Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices): conciseness, degrees of freedom, naming, descriptions, fully qualified MCP tool names, workflows and evaluation.
- [skill-creator skill](https://github.com/anthropics/skills/tree/main/skills/skill-creator): a reference skill builder with an eval and benchmark loop.

## OpenAI

- [Build skills (ChatGPT and Codex)](https://learn.chatgpt.com/docs/build-skills): authoring skills for ChatGPT and Codex.
- [Skills and plugins (ChatGPT)](https://learn.chatgpt.com/docs/skills-and-plugins): how skills relate to plugins and connectors.
- [Using skills (OpenAI Academy)](https://openai.com/academy/skills/): an introduction to identifying, writing and sharing skills.
- [Skills (OpenAI API)](https://developers.openai.com/api/docs/guides/tools-skills): uploading, attaching and versioning skills in the API.
- [skill-creator skill](https://github.com/openai/skills/tree/main/skills/.system/skill-creator): OpenAI's reference skill builder.

## Model Context Protocol

- [Tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools): tool definitions, input schemas and annotations such as `readOnlyHint` and `destructiveHint`.
- [MCP Apps](https://github.com/modelcontextprotocol/ext-apps): interactive UI for MCP tools, including app-only tools.
