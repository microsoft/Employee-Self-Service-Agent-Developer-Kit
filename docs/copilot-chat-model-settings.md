# GitHub Copilot Chat model settings

This document records the ADK investigation for model version, reasoning
effort, and context-window settings used by GitHub Copilot Chat in the Maker
experience.

## Finding

The ADK repository does not currently contain a supported setting that pins
any of these values:

| Setting | ADK-controlled? | Classification |
|---|---:|---|
| Model version | No | Controlled by the GitHub Copilot / VS Code host and the user's available model selection |
| Reasoning effort | No | Controlled by the Copilot Chat host/model experience |
| Context-window size | No | Determined by the selected model and host service |

The installer and Maker Profile configure the workspace layout, extension
behavior, and ADK workflow. They do not own the Copilot Chat model-selection
policy. Adding an undocumented `settings.json` key, environment variable, or
extension manifest value would not reliably pin these settings and could
silently stop working as the host changes.

## Scope distinction

GitHub Copilot Chat settings must not be confused with Copilot Studio agent
configuration. In particular, a Copilot Studio value such as
`modelNameHint`, when present in a Copilot Studio agent configuration, does not
select or pin the model used by GitHub Copilot Chat in VS Code.

## Validation guidance

When model-sensitive validation is required:

1. Record the model shown by the Copilot Chat model picker for the test run.
2. Record the visible reasoning or response-mode selection, if the host exposes
   one.
3. Record the test environment and extension versions.
4. Treat the context window as a host/model property rather than an ADK
   configuration value.

This produces reproducible test metadata without claiming that the ADK can
enforce host-controlled behavior.

## Revisit criteria

An implementation should be reconsidered only when GitHub Copilot or VS Code
documents a supported, workspace-scoped mechanism for pinning these values.
Any future change should cite that authoritative contract and include a
compatibility test for the supported setting.
