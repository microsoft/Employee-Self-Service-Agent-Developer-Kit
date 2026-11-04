# Enter ServiceNow Connect

This is the ServiceNow-specific entry point selected through `integration.json`.
Generic integration selection belongs in `src/skills/connect/SKILL.md`; the
router has already emitted Connect telemetry, so do not emit it again here.

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not narrate tools, files, or internal routing.

## Admit the workspace

Check whether `.local/setup/config.json` exists before reading it, then read it
together with `.local/config.json` when present. A missing `.local` directory
or `Path does not exist` result is expected unprepared state, not a terminal
Connect failure. Do not retry the missing read or show the global
setup-required welcome message.

ServiceNow Connect applies to Declarative Agents prepared in this workspace.
It does not depend on `.local/config.json.activeAgent`, does not change it, and
does not require `connect_ready: true`; the agent chooser applies the
`authoring_ready: true` gate to the exact selected agent. If canonical state has
`schema_version: 4` but an agent entry lacks `authoring_ready`, run
`python scripts/setup_existing_da.py sync-authoring-readiness --kit-root .`
and reread `.local/setup/config.json` before deciding.

## Choose the agent

Read `src/skills/connect/servicenow-da/SKILL.md` and follow it. It offers the
prepared HR and IT agents for this workspace, accepts one pasted Copilot Studio
link, returns a typed `/setup` handoff for an agent that is new to this
workspace, and dispatches to the selected HR or IT Dev lifecycle.

**STOP — render before acting.** After every `resume-handoff`, your very next assistant message — before any other tool call — must contain `transport.ordinaryReply.text` verbatim (first run or group change) or `progress.checklistText` (transitions), and `progress.currentPhase.startText` before each action or checkpoint. Never summarize it or write "render the plan" instead. This overrides the Message-block silence rule above.

**Hard rules.** Read `src/skills/connect/shared/lifecycle-runner.md` before the first action. When `resume-handoff` returns `renderBlock`, emit `renderBlock.text` verbatim as an assistant message; terminal output does not count. Never edit `lifecycle.json` by hand; record results with `record-checkpoint-results`. Run every command with the `/setup` launcher (`py -3`), never bare `python`.

Do not use the legacy `step*.md` files in this directory, and do not run
`list-agents` or scan the environment before the chooser returns a selection.
