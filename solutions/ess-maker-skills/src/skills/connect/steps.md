# Connect — Integration Templates

This folder does not use a top-level steps.md. Each integration has its
own steps.md and config.json under its subfolder:

- `servicenow/steps.md` + `servicenow/config.json`
- Workday uses `connect/workday/` when a compatible CEA extension is already
  installed. New installation and Declarative Agent routing remain outside
  this lifecycle.

See SKILL.md for routing logic.
