<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Skill 7 — Validate and Hand Off ServiceNow

Role: **Maker**. This skill runs the live ServiceNow proof, records the operator
attestation, and offers the handoff to create the first custom ServiceNow topic on
the working connection. It owns master-checklist rows **S7.1** and **S7.2**.

Depends on skills 1–6: the environment, ESS base agent, ServiceNow sign-in path,
extension pack, ServiceNow/Dataverse connections, Portal Base URL, and flows must
already be complete. Do not run this skill before the connection is complete.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading. **Never** show internal variable names, Step IDs,
checkpoint IDs, or hidden checklist comments in chat.

**Rows this skill owns:** S7.1 **Run an end-to-end validation** — Ask the agent a
real ServiceNow question and confirm it returns your live data with working portal
links. Gate: `attest`; checkpoint: `n/a`. S7.2 **Create your first ServiceNow
topic** — Hand off to topic creation so you can build your first custom ServiceNow
topic on the working connection. Gate: `manual`; checkpoint: `n/a`.

These rows have **no programmatic checkpoint**. Do not run FlightCheck for either
row. They complete only after explicit user acknowledgement captured with
`vscode_askQuestions`, per
[`../shared/checklist-updater.md`](../shared/checklist-updater.md) §U.2.

When applying the shared updater, use ServiceNow paths:
`.local/connect/servicenow/config.json`, `.local/setup/servicenow/tasks.md`, and
`src/skills/setup/servicenow/tasks.md`. The shared updater is written with Workday
examples; substitute these paths, update only S7.1/S7.2, and persist each row
immediately.

---

## P7.0 — Rehydrate and guard prerequisites

Read `.local/connect/servicenow/config.json` and rehydrate `scope`, `authType`,
`instanceUrl` / `instanceName`, and `setupStatus`.

Continue only when the applicable prerequisite setup rows are `done`: always the
environment, ESS base agent, connection basics, extension pack, connection binding,
Portal Base URL, and flows; plus the selected sign-in path (`entra_user` OIDC +
user mapping, or `entra_certificate` OIDC + system user). If config is missing, no
product scope is selected, or any prerequisite is incomplete, stop and return to
the setup router. Do not guess scope, repeat Portal Base URL setup, or verify flows
here; those belong to skill 6.

---

## P7.1 — Start S7.1 and cover OBO connection sharing

Set **Run an end-to-end validation** to `in-progress` through the shared updater:
`STEP_ID="S7.1"`, `GATE="attest"`, `CHECKPOINT_RESULT=null`, `ACK=false`,
`NEW_STATE="in-progress"`. Persist immediately.

Read `parameterSharing` from the saved ServiceNow setup state before prompting:

- If `parameterSharing == "shared"`, carry that prior maker attestation forward as
  S7.1 evidence and skip the sharing question. The bundled connect-and-share step
  already confirmed it.
- If prior setup state clearly says sharing is not applicable for the chosen
  connector/auth mode, carry that evidence forward and skip the sharing question.
- Otherwise, ask the sharing question below before the live validation.

**Message:**

Before the live test, one last connection-sharing check: if your employees use a
shared ServiceNow connection, open the Power Apps maker portal, go to
**Connections**, open your ServiceNow connection, choose **Share**, and add the
employees or group with **Can use** access.

This prevents employees from being asked to authenticate the first time they use a
ServiceNow feature. If this sharing step doesn't apply to your connection type,
you can say so in the confirmation.

**End message.**

Use `vscode_askQuestions`:

```json
[
  {
    "header": "ServiceNow connection sharing",
    "question": "Have you shared the ServiceNow connection with Can use access, or confirmed this sharing step does not apply?",
    "options": [
      { "label": "Yes — shared or not applicable", "recommended": true },
      { "label": "Not yet" }
    ],
    "allowFreeformInput": false
  }
]
```

- **Yes** → persist `parameterSharing = "shared"`, continue, and carry the answer
  as S7.1 evidence so later resumes do not ask again.
- **Not yet** → leave S7.1 `in-progress`, show the stop message, and halt.

**Message:**

No problem — finish sharing the ServiceNow connection with **Can use** access,
then come back and we'll run the live end-to-end validation.

**End message.**

---

## P7.2 — Ask the live ServiceNow questions

This is the true proof. The signed-in user asks the connected ESS agent a real
ServiceNow question and confirms the result is **live data** with **working portal
links**. Show only the prompts for products in `scope`; if both are in scope, ask
for both.

**Message:**

Now let's prove the ServiceNow connection end to end. In a chat with your ESS
agent — the Copilot Studio **Test** pane or the published channel — ask the
ServiceNow question for each product you connected:

- HRSD: **"Show my HR cases"**
- ITSM: **"Show my IT tickets"**

For each prompt you run, confirm whether the agent returns your **real live
ServiceNow data** and whether the **links open the right record** in the ServiceNow
portal.

**End message.**

Use `vscode_askQuestions`:

```json
[
  {
    "header": "ServiceNow live validation",
    "question": "Did the ESS agent return your live ServiceNow data with working portal links for every in-scope product you tested?",
    "options": [
      { "label": "Yes — live data and links worked", "recommended": true },
      { "label": "No — authentication or permission error" },
      { "label": "No — empty results" },
      { "label": "No — links were missing or broken" },
      { "label": "Not tested yet" }
    ],
    "allowFreeformInput": false
  }
]
```

Branch on the answer:

- **Yes — live data and links worked** → complete S7.1 in P7.3.
- **Authentication or permission error** → leave S7.1 open and route back to the
  chosen sign-in-path skill: OIDC provider and user mapping for `entra_user`, or
  OIDC provider and integration system user for `entra_certificate`.
- **Empty results** → leave S7.1 open. Likely causes are no records for that user
  or user-matching failure. Try a user known to have cases or tickets; if still
  empty, revisit OIDC claim-to-ServiceNow-user mapping.
- **Links missing or broken** → leave S7.1 open and route back to skill 6 to fix
  the Portal Base URL; do not include Portal Base URL setup here.
- **Not tested yet** → leave S7.1 `in-progress` and halt.

For any non-passing answer, show:

**Message:**

Thanks — the live validation is not complete yet, so I won't mark it done. Fix the
issue, then come back and run the same ServiceNow prompt again so we can confirm
live data and working links.

**End message.**

Do not offer topic creation until S7.1 is `done`.

---

## P7.3 — Complete S7.1

When the user explicitly confirms live ServiceNow data and working portal links,
record the attestation.

**Message:**

Great — your ESS agent is returning live ServiceNow data with working portal links.
The ServiceNow connection is validated end to end.

**End message.**

Update S7.1 through the shared updater with `STEP_ID="S7.1"`, `GATE="attest"`,
`CHECKPOINT_RESULT=null`, `ACK=true`, and `NEW_STATE="done"`. Evidence: user
attested that in-scope ServiceNow prompts returned live data and working links;
include whether connection sharing was completed or not applicable. Persist
immediately, and merge a ServiceNow config validation marker such as
`validation.endToEnd = { "state": "done", "verifiedBy": "attested" }` without
dropping other keys. Continue to P7.4.

---

## P7.4 — Offer the `/create` handoff

Only run this after S7.1 is `done`. This skill does **not** author topics; it hands
off to the general topic-creation skill.

Set **Create your first ServiceNow topic** to `in-progress` through the shared
updater with `STEP_ID="S7.2"`, `GATE="manual"`, `CHECKPOINT_RESULT=null`,
`ACK=false`, and `NEW_STATE="in-progress"`. Persist immediately.

**Message:**

Your ServiceNow connection is complete. Do you want to create your first custom
ServiceNow topic now? If you do, I'll hand you off to `/create` so you can build a
topic that uses this working connection.

**End message.**

Use `vscode_askQuestions`:

```json
[
  {
    "header": "Custom ServiceNow topic",
    "question": "Do you want to create a new custom ServiceNow topic now?",
    "options": [
      { "label": "Yes — create a custom topic", "recommended": true },
      { "label": "No — I'm done for now" }
    ],
    "allowFreeformInput": false
  }
]
```

Both answers are explicit manual acknowledgement of the handoff decision. Complete
S7.2 through the shared updater with `STEP_ID="S7.2"`, `GATE="manual"`,
`CHECKPOINT_RESULT=null`, `ACK=true`, and `NEW_STATE="done"`. Evidence: the user
chose to start `/create` now or create a topic later. Persist immediately.

- **Yes — create a custom topic** → show the handoff message, then read
  `src/skills/topics/create/SKILL.md` or run `/create` and follow it. Frame the new
  topic as a ServiceNow scenario using the validated HRSD and/or ITSM connection.
- **No — I'm done for now** → skip to P7.5.

**Message:**

Great — I'll open the topic-creation flow now. We'll use the working ServiceNow
connection you just validated.

**End message.**

---

## P7.5 — Done

Use this message after the `/create` handoff returns, or when the user declines to
create a topic now.

**Message:**

✅ ServiceNow is connected and validated end to end.

Your out-of-the-box ServiceNow topics are ready to use. When you're ready,
**publish** your agent in Copilot Studio so employees can use it. You can also run:

| Command | What it does |
|---------|-------------|
| `/create` | Create a new topic that uses ServiceNow |
| `/scan` | Check your agent for any errors |
| `/menu` | See all available commands |

**End message.**

Return control to the ServiceNow setup router (`SKILL.md`).
