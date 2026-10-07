# Connect Script

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling
or what files you are reading.

---

## Availability

For ServiceNow guided setup or repair (including SNOW and follow-ups), show the Message and
STOP before provider state, credentials, telemetry, MCP, or retained steps.
This includes preselection and saved-state resume.

**Message:**

Guided ServiceNow setup is not yet available in ADK. You can configure the ServiceNow connection manually in Copilot Studio or contact admin.

**End message.**

---

## Start

If the user specified an integration as an argument (e.g., "workday"),
pass it to step1 as PRE_SELECTED_INTEGRATION. Step1 will skip the
"which system" question and go directly to routing for that integration.

Read `src/skills/connect/step1.md` and follow it. That file records anonymous
usage telemetry after routing knows which integration was chosen, so the
Connect capability event carries the correct `connector` attribution
(workday vs servicenow) rather than being a generic "connect" wedge.

(Step 1 asks which integration, detects existing state, and dispatches —
Workday first by agent architecture, then
DA to its package/Entra/tenant checklist or CEA to either the lightweight
already-installed lifecycle or the existing unsupported-install boundary.)

---

## Routing

Workday routes by architecture before package detection:

- **Workday**:
  - **CEA simplified extension already installed** — use
    `src/skills/connect/workday/SKILL.md`, driven by the generic
    `src/skills/connect/shared/lifecycle-runner.md` and
    `src/skills/connect/workday/contract.json`.
  - **CEA full/legacy package or no package** — stop at the current unsupported
    installation boundary without changing state.
  - **Native DA HR agent** — use `src/skills/setup/workday-da/SKILL.md` for the
    resumable six-phase controller lifecycle.
  - **Classic DA HR, DA IT, or another DA agent** — unsupported for this
    Workday lifecycle; stop before creating state.

  CEA per-agent lifecycle state is stored at
  `.local/connect/workday/agents/{agent-slug}/lifecycle.json`. DA Workday state
  is stored only in `.local/connect/workday-da/config.json`.

Each integration retains only the state artifacts listed above. ServiceNow
uses its `steps.md` and `config.json`; CEA Workday uses per-agent
`lifecycle.json`; native DA Workday uses only its `config.json`. Running
`/connect` again lets the user add a different integration without losing
existing ones.
