# Employee Self-Service Agent

Copilot Studio topics for employee self-service scenarios integrating with Workday and facilities management systems.

## Contents

| Folder | Description |
|--------|-------------|
| [ESSEvaluationSamples/](./ESSEvaluationSamples/) | Evaluation test sets for ESS agent scenarios |
| [Facilities/](./Facilities/) | Facilities management topics (tickets, dining, guests, vehicles) |
| [Workday/](./Workday/) | Workday HR integration topics (employee and manager scenarios) |

---

## ESS Maker Kit Snapshot Notice

This folder is a **vendored snapshot** of the official Microsoft Copilot
Studio sample content for the Employee Self-Service agent. It is included
in this repository so the kit's Copilot Chat agent grounds on it first
when creating or extending topics, workflows, and evaluations (per the
**Grounding Priority** section of `solutions/ess-maker-skills/.github/copilot-instructions.md`).

That is the explicit tradeoff: yes, this duplicates content that lives
upstream in `microsoft/CopilotStudioSamples`; the duplication is what
makes the kit produce domain-correct YAML/JSON on the first turn rather
than the fifth.

- **Snapshot taken**: 2026-04-29
- **Source**: <https://github.com/microsoft/CopilotStudioSamples/tree/main/EmployeeSelfServiceAgent>
- **Refresh policy**: hand-PR by a kit maintainer when an upstream change
  is worth pulling in. The previous automated `scripts/sync_samples.py`
  was removed in slice PR #3 because it ran against the GitHub anonymous
  rate limit on customer corp NATs and silently overwrote any local
  edits during refresh.
- **Customer edits**: do **not** edit these files directly. They will be
  blown away on the next refresh. Add customer-specific scenarios under
  `workspace/agents/{agent-slug}/topics/` instead; the `/create` skill
  walks through that flow.

The `ServiceNow/` folder under this tree is not in the upstream sample
set; it was added by the kit team to round out the integration coverage
and is treated identically to the other folders for grounding purposes.
