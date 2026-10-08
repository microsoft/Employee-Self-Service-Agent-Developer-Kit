# GitHub Copilot Chat model settings

This document records the ADK defaults for model version, reasoning effort, and
context-window settings used by GitHub Copilot Chat in the Maker experience.

## ADK defaults

The ADK uses these defaults for skill-driven Copilot Chat work:

| Setting | ADK-controlled? | Classification |
|---|---:|---|
| Model version | Yes | `gpt-6-sol` |
| Reasoning effort | Policy default | Medium |
| Context-window size | Policy default | Standard (do not opt into extended context by default) |

The model is pinned in two supported places: the ADK workspace sets
`sessions.chat.defaultModel`, and every ADK prompt file declares
`model: gpt-6-sol`. The prompt-level declaration is the authoritative setting
when a maker invokes a skill; the workspace setting covers new chat sessions
started outside a prompt.

Medium reasoning is the default policy because ADK skills perform multi-step
tool use, file edits, and validation, but not every request needs maximum
thinking effort. Standard context is the default because it reduces latency and
AI-credit consumption; extended context should be selected for genuinely
large, multi-file investigations.

## Scope distinction

GitHub Copilot Chat settings must not be confused with Copilot Studio agent
configuration. In particular, a Copilot Studio value such as
`modelNameHint`, when present in a Copilot Studio agent configuration, does not
select or pin the model used by GitHub Copilot Chat in VS Code.

## Host-controlled settings

VS Code currently exposes thinking effort and extended-context choices through
the model picker rather than a documented workspace setting. The ADK therefore
cannot enforce Medium reasoning or Standard context with a supported JSON key.
The defaults above are the required operating policy for ADK work:

1. Use `gpt-6-sol` for every ADK prompt.
2. Use Medium thinking effort when the model picker exposes the choice.
3. Use the standard context option unless the task requires extended context.
4. Record any host-side override in validation results.

The model selection is enforceable through repository configuration. The
reasoning and context choices remain explicit operational defaults until VS
Code provides supported workspace-scoped settings for them.

## Revisit criteria

Reconsider these values when model quality, latency, or credit data from ADK
skill evaluations shows a better tradeoff. Any change should update both the
workspace default and every prompt declaration, then include a compatibility
test for the supported setting.

## References

- [AI language models in VS Code](https://code.visualstudio.com/docs/agent-customization/language-models)
- [Prompt files in VS Code](https://code.visualstudio.com/docs/agent-customization/prompt-files)
- [Changing the AI model for GitHub Copilot Chat](https://docs.github.com/en/copilot/how-tos/copilot-in-your-ide/chat-with-copilot/change-the-chat-model)
