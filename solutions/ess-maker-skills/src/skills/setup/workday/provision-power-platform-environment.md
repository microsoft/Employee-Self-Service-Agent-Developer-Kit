<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Skill 1 — Provision Power Platform Environment

Role: **Power Platform Administrator**. This skill provisions / verifies the
Power Platform environment (with Dataverse and Copilot Studio capacity) that the
ESS agent and the Workday extension pack are later installed into. It owns
master-checklist rows **S1.1** (environment + Dataverse) and **S1.2** (Copilot
Studio capacity).

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading.

**Checkpoints this skill drives (run each in isolation):**

- `ENV-001` — Power Platform environment exists *(reuse)*
- `ENV-002` — Dataverse database provisioned *(reuse)*
- `ENV-CAPACITY-001` — Copilot Studio message capacity provisioned *(minted by this skill)*

Run any of them with:

```
python scripts/flightcheck/cli.py --checkpoint <ID>
```

**After every checkpoint run, show its result in chat first.** As soon as a
`--checkpoint` run returns, render the result to the user per
[`shared/checklist-updater.md`](../shared/checklist-updater.md) §U.0–U.0a — the
compact result table and, for any `MANUAL` (or `Warning` / `NotConfigured`) row,
its full verification steps — **before** you show any later **Message** or ask any
attestation question. Single-checkpoint runs never open the HTML report, so this
in-chat render is the only place the user sees the manual steps; never ask a user
to attest to steps they have not been shown.

---

## P1.0 — Role gate (Power Platform Administrator)

Apply the shared [`permission-gate.md`](../shared/permission-gate.md) before any
provisioning work, with:

- `REQUIRED_ROLE` = `"Power Platform Administrator"`
- `GATE_MODE` = `"programmatic"`
- `STEP_ID` = `"S1.1"`
- `ROLE_QUERY` = list environments through the Power Platform admin API:

  ```
  python scripts/discover.py --list-environments
  ```

  The role is held if the command returns the tenant's environments (admin-scoped
  listing). Treat an `Insufficient privileges` / `Authorization_RequestDenied` /
  forbidden response as "role not held". If the command errors for an unrelated
  reason (network, not signed in), follow the gate's retry-then-attest fallback —
  never assume pass.

If `GATE_RESULT` is `"stop"`, **halt** — do not continue. Otherwise carry
`GATE_EVIDENCE` forward (it is recorded when S1.1 is updated).

---

## P1.1 — Select or create the environment

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Power Platform environment",
    "question": "Which environment should host the ESS agent?",
    "options": [
      { "label": "Pick an existing environment", "description": "List the environments in your tenant and choose one", "recommended": true },
      { "label": "I need to create a new one", "description": "Create the environment + Dataverse in the admin portal" }
    ],
    "allowFreeformInput": false
  }
]
```

- **"Pick an existing environment"** → go to P1.2.
- **"I need to create a new one"** → go to P1.5, then return here.

---

## P1.2 — Discover and confirm the environment

**Message (do NOT wait for a response — continue immediately):**

Let me list the Power Platform environments in your tenant. A browser window
will open for sign-in...

**End message.**

Run:

```
python scripts/discover.py --list-environments
```

Build a choice per environment row (label = environment name, description = URL +
type) and ask the user to pick one with `vscode_askQuestions`. Then confirm the
selection:

```
python scripts/discover.py --list-environments --select {NUMBER}
```

Parse the `SELECTED_ENV_JSON:` line; take `instanceUrl`, **strip any trailing
slash**, and save it as `dataverseEndpoint` in `.local/config.json` (merge — do
not drop other keys). Go to P1.3.

---

## P1.3 — Verify environment + Dataverse (S1.1)

**Message:**

Now I'll confirm your Power Platform environment exists and has a Dataverse
database set up — that's the foundation your agent runs on.

**End message.**

Run the two reused checkpoints in isolation:

```
python scripts/flightcheck/cli.py --checkpoint ENV-001
python scripts/flightcheck/cli.py --checkpoint ENV-002
```

- **Both `PASSED`** → update **S1.1** via
  [`checklist-updater.md`](../shared/checklist-updater.md) with
  `STEP_ID="S1.1"`, `GATE="prog"`, `NEW_STATE="done"`,
  `CHECKPOINT_RESULT="PASSED"`. Persist the P1.0 `GATE_EVIDENCE`. Go to P1.4.
- **`ENV-002` `FAILED`** (environment exists but no Dataverse):

  **Message:**

  This environment doesn't have a Dataverse database yet. Open the
  [Power Platform admin center](https://admin.powerplatform.microsoft.com/),
  select this environment, and add a Dataverse database, then tell me when it's
  ready and I'll re-check.

  **End message.**

  After the user confirms, re-run `--checkpoint ENV-002`. When it passes, update
  S1.1 as above. While it is not yet passing, update S1.1 with
  `CHECKPOINT_RESULT="FAILED"` (the updater records it as `blocked`).
- **`ENV-001` `FAILED`** (no usable environment) → go to P1.5 (create one).

---

## P1.4 — Verify Copilot Studio capacity (S1.2)

**Message:**

Now I'll check that this environment has Copilot Studio capacity allocated —
without it the agent can't run.

**End message.**

Run the capacity checkpoint:

```
python scripts/flightcheck/cli.py --checkpoint ENV-CAPACITY-001
```

Branch on the result:

- **`PASSED`** (capacity is allocated) → update **S1.2** via
  [`checklist-updater.md`](../shared/checklist-updater.md) with
  `STEP_ID="S1.2"`, `GATE="prog"`, `NEW_STATE="done"`,
  `CHECKPOINT_RESULT="PASSED"`. Go to **Done**.
- **`FAILED` / `WARNING`** (no capacity, or a billing-risk warning):

  **Message:**

  This environment has no Copilot Studio message capacity allocated yet. Open
  [Power Platform admin center → Licensing → Copilot Studio → Manage capacity](https://admin.powerplatform.microsoft.com/billing/licenses/copilotStudio/overview),
  allocate capacity to this environment, then tell me when it's done and I'll
  re-check.

  **End message.**

  After the user confirms, re-run `--checkpoint ENV-CAPACITY-001` (this is the
  verification gate — never accept "done" without a re-check). When it passes,
  update S1.2 as `done` (`GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`).
- **`MANUAL`** (capacity could not be read programmatically — the licensing API
  was unavailable or your role can't read it). This row falls back to
  **attestation**:

  **Message:**

  I can't read this environment's Copilot Studio capacity automatically, so I
  need you to confirm it directly. In
  [Power Platform admin center → Licensing → Copilot Studio → Manage capacity](https://admin.powerplatform.microsoft.com/billing/licenses/copilotStudio/overview),
  check that message capacity is allocated to this environment.

  **End message.**

  Update **S1.2** via [`checklist-updater.md`](../shared/checklist-updater.md)
  with `STEP_ID="S1.2"`, `GATE="attest"`, `CHECKPOINT_RESULT="MANUAL"`, and
  `ACK` set from the user's explicit confirmation (only `ACK=true` on an explicit
  "Yes, it's allocated"). A `MANUAL` result never completes the row on its own.

---

## P1.5 — Create a new environment (manual, gated)

**Message:**

Let's create the environment. Open the
[Power Platform admin center](https://admin.powerplatform.microsoft.com/),
choose **Environments → New**, and create an environment **with a Dataverse
database**. Allocate Copilot Studio message capacity to it as well. Tell me when
it's created and I'll verify it.

**End message.**

After the user confirms, return to **P1.2** to discover and select the new
environment, then continue through P1.3 and P1.4. Creation is never assumed
"done" — every row is completed only by its checkpoint (or, for capacity that
isn't queryable, an explicit attestation).

---

## Done

**Message:**

Your Power Platform environment is ready: the environment and Dataverse are
verified, and Copilot Studio capacity is confirmed. Next, install the ESS base
agent (skill 2).

**End message.**

Both S1.1 and S1.2 are now recorded in the checklist. Stop here — installing the
ESS agent is a separate skill.
