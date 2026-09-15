---
mode: agent
description: "Type Enter to review and harden your agent's instructions against ungrounded or over-committing answers"
---

# Harden

**Setup-state check.** Read `.local/config.json`. If it does not exist, OR `setup` is not `"complete"`, show:

> Welcome to the ESS Maker Kit. Before running `/harden`, type `/setup` to set up your environment.

and STOP. Otherwise proceed with the skill instructions below.

You are helping a maker review their agent's **system instructions** — the standing guidance the agent
follows on every turn — for internal contradictions and for the gaps that let an agent answer confidently
from something other than its knowledge sources, or offer to do things it cannot do.

Every change is **proposed, never applied silently**: the maker sees the exact before-and-after text and
approves it.

Read the skill instructions at `src/skills/instructions/harden/SKILL.md`, then follow the steps in order.
