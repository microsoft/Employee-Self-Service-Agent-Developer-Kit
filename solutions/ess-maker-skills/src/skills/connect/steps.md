# Connect — Integration Templates

This folder does not use a top-level steps.md. Each integration has its
own steps.md and config.json under its subfolder:

- `servicenow/steps.md` + `servicenow/config.json`
- Workday has no `connect/workday/` subfolder — it's handled by
  `src/skills/setup/SKILL.md` (CEA) or `src/skills/setup/workday-da/SKILL.md`
  (DA), selected by `step1.md` based on which kind of ESS agent is installed.

See SKILL.md for routing logic.
