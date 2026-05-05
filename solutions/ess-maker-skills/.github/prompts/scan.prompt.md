---
mode: agent
description: "Type Enter to scan your agent for errors and fix them"
---

# Scan

**Setup-state check.** Read `.local/config.json`. If it does not exist, OR `setup` is not `"complete"`, show:

> Welcome to the ESS Maker Kit. Before running `/scan`, type `/setup` to set up your environment.

and STOP. Otherwise proceed with the skill instructions below.

You are helping a customer fix compile errors in their cloned ESS agent. Be clear about what each error is, why it matters, and what the fix options are. Walk through errors one group at a time — don't overwhelm the user.

Read the skill instructions at `src/skills/cleanup/SKILL.md`, then follow the steps in order.
