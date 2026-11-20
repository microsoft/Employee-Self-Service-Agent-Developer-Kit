# Diagnostics Topics

These two topics are an experimental aid for Development agents only. `[System] - Record Search Results` records tool calls and search results. `[System] - Diagnose Report` displays the record for a question. While the set is on, every answer that used a tool first calls the record topic, so answers are slower.

The model writes the record, which is not an audit log. Without special settings on the Copilot side, the record topic is rarely offered, so a report may have no recorded search results.

After enabling and publishing the set, ask a question, then type `/diagnose` in the same chat. Microsoft 365 Copilot may take time to serve the new version; one test took 45 minutes.

Promotion carries each topic's on/off state from the published Dev agent to the next agent, and Test and Production can't turn it off for good. Disable the set in Dev and publish before any promotion. Changes made by `/manage-topics` remain in the agent draft until you publish in Copilot Studio.

Report problems with add, enable or disable to the [kit's GitHub Issues](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/issues).

## Source

The YAML files contain the ESSVivaCopilot HR template dialogs at commit `eb423aaea30944b7f8cbf205b424e779ef7f53cf`: each component's `dialog` block with `kind: AdaptiveDialog` prepended, otherwise unchanged. The HR and IT dialogs are identical, so this copy serves every catalog family.
