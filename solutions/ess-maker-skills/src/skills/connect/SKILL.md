# Connect Script

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling
or what files you are reading.

---

## Availability

This DA release offers **Workday only**, subject to the existing active-agent
architecture gates. ServiceNow connect is unavailable for every target in this
release; saved state cannot enable it.

Treat case-insensitive `servicenow`, `service now`, `snow`, `hrsd`, and `itsm`
as ServiceNow. This includes explicit arguments, PRE_SELECTED_INTEGRATION,
connection setup inferred from topic/workflow requests, reconnect, change-auth,
resume/continue, and repair, with complete, incomplete, stale, or absent
ServiceNow state. Use the requested provider or prior conversation context to
classify follow-ups; generic `/connect` never reads or advertises saved
ServiceNow state.

For a ServiceNow request, show this Message and STOP before reading or writing
provider state, asking for credentials, emitting connect telemetry, configuring
MCP, or loading or executing retained provider files. Leave existing state
unchanged. Do not substitute Workday for a requested ServiceNow operation.

**Message:**

ServiceNow integration isn't supported in this DA release. Please contact
your administrator.

**End message.**

---

## Start

Apply **Availability** before any setup check or other connect action.

If the user specified a supported integration as an argument (e.g., "workday"),
pass it to step1 as PRE_SELECTED_INTEGRATION. Step1 will skip the
"which system" question and go directly to routing for that integration.

Read `src/skills/connect/step1.md` and follow it. That file records anonymous
usage telemetry after routing knows which integration was chosen, so the
Connect capability event carries the supported `connector` attribution.

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

Workday retains only the state artifacts listed above. Running `/connect`
again follows the same availability contract without changing other saved
integrations.
