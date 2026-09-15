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

## Command runtime

The first terminal operation must change to the kit root, which is the directory
containing `scripts/`. Do not rely on the terminal's inherited working
directory. Run every setup command from that location; when shell state may not
persist between commands, prefix the command with an explicit change to
`{KIT_ROOT}`.

Before the first Python command, resolve one working launcher and reuse it for
the rest of setup:

- on Windows, prefer `py -3`; if it is unavailable, use a working `python3` or
  `python`;
- on macOS or Linux, prefer `python3`; if it is unavailable, use a working
  `python`.

Verify the selected launcher with
`{PYTHON} -c "import sys; print(sys.executable)"`. Do not use a setup command as
the launcher probe. If no launcher works, report the missing Python prerequisite
and stop. When child guidance shows `python`, substitute the resolved launcher.

## Interactive authorization

Before starting a command that can open Microsoft sign-in, tell the maker:

> Microsoft sign-in will open. Select the account you use to access this
> environment. If the expected account is not shown, choose **Use another
> account**.

If the terminal returns control while that command is still waiting for the
browser callback, immediately tell the maker:

> **Waiting for authorization**
>
> Complete the Microsoft sign-in in your browser. I will continue automatically
> after authorization finishes.

Do not describe an authorization wait as service processing, do not start a
second command, and do not infer that a remote mutation has started.

---

## Start

Record anonymous usage telemetry best-effort:

```text
python scripts/emit_capability.py setup
```

When the maker has already supplied a native agent package or explicitly asked
to use one, read `src/skills/foundation-setup/da-alm-import.md` and follow it.
That skill owns the explicit package handoff and reads the canonical import
reference. This is an advanced handoff, not a setup option to advertise or
recommend.

For every other request, read
`src/skills/foundation-setup/da-existing-dev.md` and follow it. Existing
editable Dev remains the default setup path.

Do not run the retired Dataverse foundation or onboarding playbooks.

Never route from `/setup` into an integration or topic playbook.
