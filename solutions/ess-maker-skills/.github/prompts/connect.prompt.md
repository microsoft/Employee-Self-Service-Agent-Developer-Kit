---
mode: agent
description: "Check DA-GA product extension setup availability"
---

# Connect

**Setup-state check.** Read `.local/setup/config.json` and `.local/config.json`.
Resolve `.local/config.json`'s `activeAgent` slug to the matching object in its
`agents` array, then use that object's `botId` to select the entry in
`.local/setup/config.json`'s `agents` object. If setup does not have
`schema_version: 4`, or that canonical agent entry does not have
`authoring_ready: true`, show the message below and STOP. Ignore
`connect_ready`, `active_step`, blocked capacity, and blocked connection steps
for this admission check; capacity and the product connection itself may still
need attention.

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
