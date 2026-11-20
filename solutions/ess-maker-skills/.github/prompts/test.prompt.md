---
mode: agent
description: "Debug and fix a topic toward the latest authoring goal when runtime testing is available"
---

# Test

Carry an already selected topic and the latest authoring goal from the request. Ask for the target only when it is genuinely unknown. Evaluation generation and graded evaluation execution retain their separate owners.

**Setup-state check.** Read `.local/setup/config.json` and `.local/config.json`. If canonical state does not have `schema_version: 4` and an `agents` entry matching the active workspace slug with `connect_ready: true`, show:

> Welcome to the ESS Maker Kit. Before running `/test`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

## Topic testing

Read [Testing experience](../../src/skills/topics/testing-experience.md) for the scoped runtime correctness goal and `{topic_test_results}` outcome copy. The testing owner loads the shared foundation and the operational references needed for the current phase.

Check `scripts/native_topic_test.py` directly. If it is absent, explain that this installation does not include conversation testing, report conversation acceptance as pending using `{topic_test_results}`, offer manual testing guidance, and stop.

When installed, read `src/skills/topics/test/SKILL.md` and follow its phase-specific procedure and evidence requirements. Carry the intended behavior, selected topic, any valid test/fix authorization and declined corrections. Do not repeat an already-requested testing offer; missing activation permission still requires an explicit choice. Saving/readback is separate from conversation acceptance. Honor no-activation and test-only requests; never publish.

Carry reporting context to the testing owner. Reuse its status updates, readiness controls and outcome report without emitting a second copy; delegated fixes retain their performing owner's updates.

## Workflow requests

Power Automate authoring and runtime changes take place outside ADK. For separately requested read-only run inspection, follow `src/skills/workflows/test/SKILL.md` and its independent target/authentication prerequisites.
