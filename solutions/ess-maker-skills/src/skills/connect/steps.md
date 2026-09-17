# Connect — Integration Templates

This folder does not use a top-level steps.md. Each integration has its
own steps.md and config.json under its subfolder:

- `servicenow/steps.md` + `servicenow/config.json`
- Workday routes by architecture: CEA uses `connect/workday/` when an
  extension already exists or `src/skills/setup/SKILL.md` for full setup;
  DA uses `src/skills/setup/workday-da/SKILL.md`.

See SKILL.md for routing logic.
