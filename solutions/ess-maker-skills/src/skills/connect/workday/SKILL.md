# Connect Workday (already installed)

Entry point for connecting this agent to a Workday extension that is
**already installed** somewhere in this environment. If no Workday extension
exists yet, the caller (`src/skills/connect/step1.md`) routes to the setup
orchestrator (`src/skills/setup/SKILL.md`) instead — this file is never
reached in that case.

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## W.1 — Run the lifecycle

Read `src/skills/connect/shared/lifecycle-runner.md` and follow it with
`PROVIDER = "workday"` and `AGENT_SLUG` resolved from `.local/config.json`
(`activeAgent`, falling back to `agent.slug`).

That file loads `src/skills/connect/workday/contract.json`, resumes any
in-progress state from
`.local/connect/workday/agents/{AGENT_SLUG}/lifecycle.json`, shows the
plan and collects attestation on a first run, live-re-verifies anything
already recorded done, then runs whichever phase is next — confirming the
extension and its connections, wiring the agent's Workday topics, and
validating the end-to-end connection.

---

## W.2 — After completion

Once the lifecycle runner reports Workday connected, return control to the
caller. Do not repeat the runner's completion message or add your own.
