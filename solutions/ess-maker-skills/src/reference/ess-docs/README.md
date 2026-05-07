# ESS Reference Docs (Vendored Snapshot)

This folder contains a **vendored snapshot** of the official Microsoft Learn
documentation for the Employee Self-Service (ESS) agent in Microsoft 365
Copilot.

## Why these docs are vendored

The ESS Maker Kit is a Copilot Chat grounding workspace. The kit's value
depends on the agent reading these references **first** (per the
**Grounding Priority** section of `solutions/ess-maker-skills/.github/copilot-instructions.md`),
before falling back to web fetches or general training knowledge. Without
the vendored copies in the cloned repo, the agent quietly grounds on
generic Copilot Studio guidance and the per-topic / per-workflow output
quality drops.

That is the explicit tradeoff: yes, this duplicates content that is also
on the open web; the duplication is what makes the kit produce
domain-correct topics and workflows on the first turn.

## Snapshot details

- **Snapshot taken**: 2026-04-29
- **Source**: <https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service>
- **Upstream repository**: <https://github.com/MicrosoftDocs/microsoft-365-docs/tree/public/copilot/employee-self-service>
- **Refresh policy**: hand-PR by a kit maintainer when an upstream change
  is worth pulling in. The previous automated `scripts/sync_docs.py` was
  removed in slice PR #3 because it ran against the GitHub anonymous
  rate limit on customer corp NATs and silently overwrote any local doc
  edits during refresh.

## What is *not* in scope here

- This is **not** a fork of the docs. Customer edits to these files will be
  blown away on the next refresh.
- This is **not** the place to add kit-specific guidance. Add that to
  `src/skills/` (operational guidance) or to a sibling folder under
  `src/reference/` (durable reference).

## Layout

```
ess-docs/
  customization/      Topic / variable / starter-prompt customization patterns
  deployment/         Deploy-overview-alm + admin guidance
  flightcheck/        FlightCheck usage guide (paired with scripts/flightcheck/)
  integrations/       ServiceNow + Workday integration guides
  operations/         Evaluations, usage analytics, run-tests guidance
```

Each subfolder is a copy of the corresponding section on Microsoft Learn,
trimmed to the markdown body (front-matter and Learn-specific includes
removed).
