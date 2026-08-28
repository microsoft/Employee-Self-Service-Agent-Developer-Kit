---
mode: agent
description: "Review authored topics or evaluation test sets tagged for review"
---

# Review

First determine what the user wants to review:

- **Evaluation test sets**, including requests such as "review testsets",
  "show test sets tagged for review", "review assigned evaluations", or acting
  as a judge/SME -> read
  `src/skills/evaluations/review/SKILL.md` and follow it. Do this before any
  setup gate. Workspace-level evaluation sets can be reviewed without a
  configured agent.
- **Topics**, including a whole module's topics -> continue with the topic
  review flow below.
- If the user did not specify, ask whether they want to review **topics** or
  **evaluation test sets**.

Never interpret the word "review" alone as a request to run evaluation quality
validation. Quality validation requires words such as "validate",
"quality-check", or "score", or is invoked after a selected test set is edited.

## Topic review

**Setup-state check.** Read `.local/config.json`. If it does not exist, OR
`setup` is not `"complete"`, show:

> Welcome to the ESS Maker Kit. Before reviewing topics, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

You are helping a customer review authored topics for issues **before they
publish them** — either a single topic, or all the topics for a backend module
(e.g. "review all the Workday topics"). This review is **advisory** — it
surfaces findings and lets the customer decide; it never blocks.

Read the skill instructions at `src/skills/topics/review/SKILL.md`, then follow the steps in order.
