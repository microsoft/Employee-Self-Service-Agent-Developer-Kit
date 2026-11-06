# Connect integrations

This is a provider-neutral router, not an integration setup procedure.
Provider names, availability, aliases, entry points, state rules, prerequisites,
and lifecycle instructions belong in each provider's own directory.

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not narrate tools, files, or internal routing.

## Start

If the user or calling prompt already selected an integration, pass that
selection to `step1.md` as `PRE_SELECTED_INTEGRATION`. An unambiguous selection
from the current conversation also counts; do not ask the same question again.
Preserve the original request and target intent through routing and any
required foundation setup. Provider-specific follow-ups belong to that
provider's entry point.

Read `src/skills/connect/step1.md` and follow it.

## Boundaries

- Discover providers from their `integration.json` registrations, not from a
  hard-coded provider list or the existence of retained step files.
- Apply the selected provider's availability before provider state,
  credentials, telemetry, MCP, or lifecycle actions. This applies equally to
  preselection, repair requests, follow-ups, and saved-state resume.
- Do not inspect, reset, copy, or migrate provider state here. Let the selected
  provider own readiness and resume decisions.
- There is no shared connection checklist or generic Fresh Start operation.
- New integrations belong in their own child directories with their own
  registrations and entry points.
