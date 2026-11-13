---
mode: agent
description: "Review topic deletion or check another component's deletion options"
---

# Delete

Use the selected component's owner. Topic deletion can be pushed to the agent,
kept local for a later Push, or limited to discarding an unsaved draft.

**Setup-state check.** Read `.local/setup/config.json` and `.local/config.json`. If canonical state does not have `schema_version: 4` and an `agents` entry matching the active workspace slug with `connect_ready: true`, show:

> Welcome to the ESS Maker Kit. Before running `/delete`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

**IMPORTANT: When the user just types `/delete` with no additional text, do
NOT silently route anywhere. Ask the user what they want to delete first.**

## Flow

1. Infer the component type from the request when unambiguous. Otherwise ask what the maker wants to delete.
2. Carry a known selection forward. For topics, let the delete owner resolve missing or ambiguous identity through its shared selection control. For other components, resolve a missing selection before continuing.
3. Route based on their answer:
   - **topic**
     -> Read `src/skills/topics/delete/SKILL.md` and follow its instructions.
   - **workflow**
     -> Read `src/skills/workflows/delete/SKILL.md` and follow its instructions.
   - **evaluation**
     -> Read `src/skills/evaluations/delete/SKILL.md` and follow its instructions.

Do NOT proceed without reading the appropriate skill file first.

For topics, carry existing scoped authorization and reporting context to the delete owner. Reuse its status updates, reviews and decisions without emitting a second copy.

Topic support does not enable deployed workflow or evaluation-set deletion.
Preserve those owners' availability boundaries and do not fall back to Dataverse.
