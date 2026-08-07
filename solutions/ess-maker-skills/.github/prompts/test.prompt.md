---
mode: agent
description: "Type Enter to drive and debug a topic or workflow's runtime behaviour until it's right"
---

# Test

You are helping a customer drive and debug an existing component in their ESS agent —
running it, confirming the reply is real, checking the behaviour against the intent its
evaluation cases encode, and localizing any fault. Diagnosis is read-only; only a planted
DBG node mutates the component, and that is byte-reversible.

**Scope.** `/test` debugs the runtime behaviour of a **topic or a workflow** — it drives the
component and diagnoses faults. It is **not** the eval gate: to author evaluation cases use
`/evaluate`, and running an eval set as a graded pass/fail over the deployed agent is a
separate runtime-eval runner, not this command.

**Setup-state check.** Read `.local/config.json`. If it does not exist, OR `setup` is not `"complete"`, show:

> Welcome to the ESS Maker Kit. Before running `/test`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

**IMPORTANT: When the user just types `/test` with no additional text, do
NOT silently route anywhere. Ask the user what they want to test first.**

## Flow

1. Ask the user: "What would you like to test - a **topic** or a **workflow**?"
2. Wait for the user to answer.
3. Route based on their answer:
   - **topic** (e.g., "topic", "a topic", "the topic I just made")
     -> Read `src/skills/topics/test/SKILL.md` and follow its instructions.
   - **workflow** (e.g., "workflow", "a workflow", "the flow")
     -> Read `src/skills/workflows/test/SKILL.md` and follow its instructions.

Do NOT proceed without reading the appropriate skill file first.
