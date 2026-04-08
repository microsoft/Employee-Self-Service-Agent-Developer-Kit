---
mode: agent
description: "Type Enter to set up your ESS customization environment"
---

# Setup

**Do NOT check for my/config.json. The user is running setup because it
doesn't exist. Proceed immediately.**

You are a script executor. Read `src/skills/onboarding/SKILL.md` (a short
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
`my/onboarding/tasks.md`. If starting fresh, your first message to the user
is the checklist table from the Fresh Start section.
