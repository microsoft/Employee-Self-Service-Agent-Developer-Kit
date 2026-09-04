---
mode: agent
description: "Type Enter to review a topic (or a whole module's topics) for issues before publishing"
---

# Review

**Setup-state check.** Read `.local/config.json`. If it does not exist, OR `setup` is not `"complete"`, show:

> Welcome to the ESS Maker Kit. Before running `/review`, type `/setup` to set up your environment.

and STOP. Otherwise proceed with the skill instructions below.

You are helping a customer review authored topics for issues **before they publish them** — either a single
topic, or all the topics for a backend module (e.g. "review all the Workday topics"). This review is
**advisory** — it surfaces findings and lets the customer decide; it never blocks.

Read the skill instructions at `src/skills/topics/review/SKILL.md`, then follow the steps in order.
