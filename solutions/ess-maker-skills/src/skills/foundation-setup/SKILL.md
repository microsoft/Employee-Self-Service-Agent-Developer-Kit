<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# ESS Foundation Setup

Every **Message** block is exact user-facing text. Do not expose internal step IDs,
checkpoint IDs, state paths, or tool narration.

Follow `src/reference/ui-formatting-guidelines.md` for every user-facing
instruction in this flow. Resolve its examples with the actual environment,
agent, product, and connector names before displaying them.

This is the DA-GA `/setup` entry point. It owns only:

- maker authentication;
- Power Platform environment and editable Dev agent selection;
- native DA identity and ALM-family validation;
- local workspace materialization;
- resumable setup state and completion reporting.

Workday, ServiceNow, SAP SuccessFactors, authentication, extension packs, and topics
are explicitly outside this skill.

---

## Start

Record anonymous usage telemetry best-effort:

```text
python scripts/emit_capability.py setup
```

Read `src/skills/foundation-setup/da-existing-dev.md` and follow it. This is the
only supported setup path in the current DA-GA implementation. Do not run the
retired Dataverse foundation or onboarding playbooks.

Never route from `/setup` into an integration or topic playbook.
