---
mode: agent
description: "Connect Workday or another supported integration"
---

# Connect

**Setup-state check.** Missing setup does not stop integration selection.
Read `src/skills/connect/SKILL.md`, retain any selected integration and target,
and apply provider availability before following that provider's entry point.
The provider owns prerequisite preparation and any automatic Setup handoff;
do not ask the maker to type `/setup` or repeat their Connect request.

For Workday, entry requires canonical state with `schema_version: 4`, complete
workspace evidence, and `steps.SETUP-07.state: "done"` for the agent whose
`agent.workspace_slug` matches `.local/config.json` `activeAgent`. Do not require
`connect_ready: true`; this command configures the product-extension
connections that may currently block runtime readiness. Missing preparation
automatically invokes Setup at entry and resumes the original request after
materialization succeeds, as defined by the Workday entry point. Do not invoke
Setup between Connect phases or after Connect completes.

Read `src/skills/connect/SKILL.md` (a short
router file) and follow it. It will tell you which step file to read next.
Provider guides contain Message blocks, numbered maker walkthroughs, value
cards, and controller-backed status or recovery guidance. All of these are
valid maker-facing instructions; a Message block is not required.

Rules:
1. Show Message block text to the user EXACTLY as written. Do not rephrase.
2. NEVER tell the user what files you are reading or what tools you are
   calling. The user must never see "Read SKILL.md" or "Calling tool" or
   file names or line numbers. If they see any of that, you have failed.
3. Render the applicable maker walkthrough in full before its confirmation,
   completion, or **Check again** question. Include the target-specific link,
   required click path, and supplied non-secret values. A question is not a
   substitute for instructions. Do not stay silent because a guide has no
   Message block.
4. If the maker asks how to do a step, answer with that step's walkthrough
   before showing another question. On a retry, show the relevant repair
   guidance before **Check again**, not only a completion reminder. Keep
   sequential provider gates; do not display a later step prematurely.
5. Consume controller success and error JSON directly. Show the safe blocker
   and supported next action on failure; do not filter output to success
   fields or invent a successful result. Preserve saved progress and required
   approvals.

After reading `SKILL.md`, follow its integration-specific state and routing
instructions. Do not assume a shared `.local/connect/steps.md` file or a
generic Fresh Start section.
