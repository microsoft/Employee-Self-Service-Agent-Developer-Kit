---
mode: agent
description: "Test a saved active text-response topic, or inspect an existing workflow run"
---

# Test

You are helping a customer test an existing component in their ESS agent. For a native DA-GA workspace, test a saved fixed-response topic through the operator-confirmed embedded chat and compare the real reply with its approved saved response. This path does not change, activate, publish or deploy content.

**Scope.** `/test` tests one saved, active, compatible trigger/literal-response topic, or routes separately requested read-only workflow-run inspection. It is **not** the eval gate: to author evaluation cases use `/evaluate`, and running an eval set as a graded pass/fail over the deployed agent is a separate runtime-eval runner, not this command.

**Setup-state check.** Read `.local/setup/config.json` and `.local/config.json`. If canonical state does not have `schema_version: 4` and an `agents` entry matching the active workspace slug with `connect_ready: true`, show:

> Welcome to the ESS Maker Kit. Before running `/test`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

The topic path supports response-only text dialogs, not unsaved drafts, arbitrary branches, cards, backend-fault simulation or debug instrumentation. Read its owning skill before selecting a browser operation. Do not activate, publish, reset, reload or replay a send to make testing pass. Exact response equality is not proof of exact-topic invocation.

Existing workflow-run inspection remains read-only and requires its own confirmed Flow API target and authentication. Do not infer those prerequisites from native agent setup or start a conversation to produce a run.

Carry forward the selected component from the current conversation. When the user types only `/test` and no component is established, ask what they want to test. Do not repeat a known topic or component-type selection.

## Flow

1. If neither the request nor current context identifies the component type, ask the user: "What would you like to test - a **topic** or a **workflow**?"
2. Wait for an answer when needed. An explicit topic request or an established selected topic already answers this question.
3. Route based on their answer:
   - **topic** (e.g., "topic", "a topic", "the topic I just made") -> Read `src/skills/topics/test/SKILL.md` and follow its instructions.
   - **workflow** (e.g., "workflow", "a workflow", "the flow") -> Read `src/skills/workflows/test/SKILL.md` for supported read-only inspection of an existing run. Report unavailable prerequisites explicitly; do not offer automated backend-topic testing.

Do NOT proceed without reading the appropriate skill file first.
