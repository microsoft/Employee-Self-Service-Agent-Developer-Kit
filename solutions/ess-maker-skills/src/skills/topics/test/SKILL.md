# Test a topic

This installation supports native topic save and readback, but does not include automated conversation testing. Report conversation acceptance as pending.

Read [experience-contract.md](../experience-contract.md) for the scoped runtime correctness goal and `{topic_test_results}` outcome copy. Report the actual capability gap and unfinished testing against the latest authoring goal, and offer manual testing guidance. This informational report does not need a routine acknowledgement. Do not display runnable testing or activation choices when their required operation is unavailable.

Carry the topic already selected in the authoring request. Keep its saved/readback outcome distinct from employee chat behavior. Preserve supplied evaluation intent and thresholds; a save alone does not establish a passing conversation or resolve review findings.

For separately requested native inspection, use the normal topic owner's current read operation. Saving, activation, publication, and conversation testing retain their separate scopes and approvals.

For separately requested read-only workflow-run inspection, follow `src/skills/workflows/test/SKILL.md` and its target/authentication prerequisites. Power Automate authoring and runtime changes take place outside ADK.
