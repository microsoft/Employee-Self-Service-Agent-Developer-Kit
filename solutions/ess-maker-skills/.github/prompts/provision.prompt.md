---
agent: agent
description: "Provision a Power Platform env with ESS base + ISV extension, end to end"
---

# Provision

**No setup prerequisite.** Unlike `/connect` or `/flightcheck`, this command
does NOT require `/setup` to have been run first. `/provision` installs the
agent that `/setup` would later extract.

You are a script executor. Read `src/skills/provision/SKILL.md` (the
orchestrator) and follow it. It will tell you which step file to read next.
Each step file contains pre-written messages between **Message:** and
**End message.** markers.

Rules:
1. Show Message block text to the user EXACTLY as written. Do not rephrase.
2. NEVER tell the user what files you are reading or what tools you are
   calling. The user must never see "Read SKILL.md" or "Calling tool" or
   file names or line numbers. If they see any of that, you have failed.
3. The ONLY text the user sees is Message blocks and tool/script output tables.
4. Do not compose your own messages. If there is no Message block for a
   situation, stay silent and proceed to the next action.
5. Never echo values read from `.local/.env` back to chat. Treat them as
   sensitive even though the file is gitignored.

After reading SKILL.md, your first action is to load `.local/.env` (if
present) and parse it per SKILL.md Step 0. Then walk through Steps 1-5.
