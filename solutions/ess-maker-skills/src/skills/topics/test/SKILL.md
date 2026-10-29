# Test a topic

This installation supports native topic save and readback, but does not include automated conversation testing. Report conversation acceptance as pending.

Carry the topic already selected in the authoring request. Keep its saved/readback outcome distinct from employee chat behavior. Preserve supplied evaluation intent and thresholds; a save alone does not establish a passing conversation or resolve review findings.

For separately requested native inspection, use the normal topic owner's current read operation. Saving, activation, publication, and conversation testing retain their separate scopes and approvals.

For separately requested read-only workflow-run inspection, follow `src/skills/workflows/test/SKILL.md` and its target/authentication prerequisites. Power Automate authoring and runtime changes take place outside ADK.
