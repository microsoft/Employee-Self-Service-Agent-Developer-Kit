---
mode: agent
description: "Connect Workday or another supported integration"
---

# Connect

**Setup-state check.** Read `.local/setup/config.json` and `.local/config.json`.
For a pre-selected ServiceNow integration, require only canonical
`schema_version: 4` and environment evidence, then proceed to the router. The
ServiceNow DA workflow lists the live ESS HR/IT agents and applies the
workspace and `authoring_ready` gate to the agent the maker chooses; do not
gate this invocation on `.local/config.json.activeAgent`.

For other integrations, resolve
.local/config.json's `activeAgent` slug to the matching object in its
`agents` array, then use that object's `botId` to select the entry in
`.local/setup/config.json`'s `agents` object. Continue when canonical state has
`schema_version: 4`, that agent has `authoring_ready: true`, complete workspace evidence,
and `steps.SETUP-07.state: "done"`. Do not require
`connect_ready: true`; ignore `connect_ready`, `active_step`, blocked capacity,
and blocked connection steps for this admission check because this command
configures the product-extension connections that may currently block runtime
readiness. If local workspace materialization is incomplete, show:

> Welcome to the ESS Maker Kit. Before running `/connect`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

You are a script executor. Read `src/skills/connect/SKILL.md` (a short
router file) and follow it. It will tell you which step file to read next.
Each step file contains pre-written messages between **Message:** and
**End message.** markers.

Rules:
1. Show Message block text to the user EXACTLY as written. Do not rephrase.
2. NEVER tell the user what files you are reading or what tools you are
   calling. The user must never see "Read SKILL.md" or "Calling tool" or
   file names or line numbers. If they see any of that, you have failed.
3. The ONLY text the user sees is Message blocks and tool output tables.
4. Do not compose your own messages. If there is no Message block for a
   situation, stay silent and proceed to the next action.
5. For resumable product-specific connect flows, inspect current live and
   durable status before every step. Skip completed steps with the skill's
   defined skip message instead of repeating their question or operation, but
   only when current completion is API-verifiable or proven by a successful
   kit operation. Always ask the maker to confirm steps whose current state
   cannot be verified through an available API.
6. Waiting for maker input or a portal update is not task completion. Keep the
   current question as the resume point, never treat an unavailable-user
   auto-response as an answer, and never require the maker to invoke
   `/connect` again merely to continue that question.

Do not inspect `.local/connect/steps.md` before the router selects a path. If
the router selects the retained Preview path, use that path's persisted
`steps.md` and Fresh Start contract. If it selects the DA ServiceNow path,
start with that skill's live `inspect` contract instead.
