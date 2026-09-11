---
mode: agent
description: "Check DA-GA product extension setup availability"
---

# Connect

**Setup-state check.** Read `.local/setup/config.json`. If it does not have `schema_version: 1` and `status: "complete"`, show:

> Welcome to the ESS Maker Kit. Before running `/connect`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

If `.local/config.json` has `transport: "agentbuilder"`, show:

> DA-GA connector setup requires the corresponding product extension. Extension setup is not yet available in this release.

and STOP.

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

After reading SKILL.md, your first action is to check for
`.local/connect/steps.md`. If starting fresh, your first message to the user
is the checklist table from the Fresh Start section.
