# Connect Script

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling
or what files you are reading.

---

## Start

Record anonymous usage telemetry (best-effort, non-blocking — no user-facing
message, and it never fails the step): `python scripts/emit_capability.py connect`

If the user specified an integration as an argument (e.g., the user said
"servicenow" or "workday", or the prompt was invoked as `/connect servicenow`),
pass it to step1 as PRE_SELECTED_INTEGRATION. Step1 will skip the
"which system" question and go directly to routing for that integration.

Read `src/skills/connect/step1.md` and follow it.

(Step 1 asks which integration, detects existing state, and dispatches —
each integration delegates to its setup orchestrator
`src/skills/setup/<product>/SKILL.md`.)

---

## Routing

Each integration delegates to its setup orchestrator, which sequences the setup
skills using a master checklist as a resume-aware spine:

- **ServiceNow**: handled by the **ServiceNow setup orchestrator**
  (`src/skills/setup/servicenow/SKILL.md`), not a `connect/servicenow/` step
  sequence. `src/skills/connect/step1.md` routes the ServiceNow branch straight
  there. The orchestrator sequences the ServiceNow setup skills (environment, ESS
  install, connection basics, Entra sign-in app — user or certificate path,
  extension pack + connection, portal URL + flows, validation) using the master
  checklist as a resume-aware spine, and persists state under
  `.local/setup/servicenow/tasks.md` + `setupStatus` in
  `.local/connect/servicenow/config.json`.
  - Auth scope (spec §0): only `entra_user` + `entra_certificate` are supported.
    The legacy `oauth2`/`basic`/`federated` (Graph) paths were retired along with
    the old `connect/servicenow/` step files (removed), matching the Workday
    migration (see `setup/servicenow/capture-servicenow-config.md`, S3.1).

- **Workday**: handled by the **setup orchestrator**
  (`src/skills/setup/SKILL.md`), not a `connect/workday/` step sequence.
  `src/skills/connect/step1.md` routes the Workday branch straight there. The
  orchestrator sequences the six Workday setup skills (environment, ESS install,
  Entra app, tenant config, extension pack, topic) using the master checklist as
  a resume-aware spine, and persists state under `.local/setup/workday/tasks.md`
  + `setupStatus` in `.local/connect/workday/config.json`.

Each integration's tasks.md and config.json persist after completion.
Running `/connect` again lets the user add a different integration
without losing existing ones.
