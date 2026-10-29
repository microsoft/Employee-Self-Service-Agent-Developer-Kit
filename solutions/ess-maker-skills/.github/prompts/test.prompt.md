---
mode: agent
description: "Check availability and run supported saved-topic testing"
---

# Test

Carry an already selected topic from the authoring request. Ask for the target only when it is genuinely unknown. Evaluation generation and graded evaluation execution retain their separate owners.

**Setup-state check.** Read `.local/setup/config.json` and `.local/config.json`. If canonical state does not have `schema_version: 4` and an `agents` entry matching the active workspace slug with `connect_ready: true`, show:

> Welcome to the ESS Maker Kit. Before running `/test`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

## Topic testing

Check `scripts/native_topic_test.py` directly. If it is absent, explain that this installation does not include bounded conversation testing, report conversation acceptance as pending, and stop.

When installed, read `src/skills/topics/test/SKILL.md` and follow its saved-topic compatibility, active-state, browser-preparation, approval, and evidence requirements. Saving/readback is separate from conversation acceptance. Do not activate or publish to make a test runnable.

## Workflow requests

Power Automate authoring and runtime changes take place outside ADK. For separately requested read-only run inspection, follow `src/skills/workflows/test/SKILL.md` and its independent target/authentication prerequisites. Do not route backend conversations through the bounded topic test.
