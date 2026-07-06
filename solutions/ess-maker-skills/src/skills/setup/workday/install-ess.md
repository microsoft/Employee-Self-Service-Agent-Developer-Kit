<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Skill 2 — Install the ESS Base Agent

Role: **Environment Maker**. This skill installs the base **Employee Self
Service** agent into the Power Platform environment that skill 1 provisioned, and
then verifies the solution landed. It owns master-checklist row **S2.1**.

Depends on skill 1 — the environment, Dataverse, and Copilot Studio capacity must
already be verified (rows S1.1 and S1.2 `done`) before this runs.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading.

**Checkpoints this skill drives (run each in isolation):**

- `ESS-SOLN-001` — ESS base agent solution installed in the environment *(minted by this skill)*

Run it with:

```
python scripts/flightcheck/cli.py --checkpoint ESS-SOLN-001
```

The base agent installs a managed solution whose unique name starts with
`msdyn_copilotforemployeeselfservice` (the base, IT, and HR editions all match).

---

## P2.0 — Role gate (Environment Maker)

Apply the shared [`permission-gate.md`](../shared/permission-gate.md) before any
install work, with:

- `REQUIRED_ROLE` = `"Environment Maker"`
- `GATE_MODE` = `"programmatic"`
- `STEP_ID` = `"S2.1"`
- `ROLE_QUERY` = a Dataverse security-role membership check for the signed-in
  user. Read `dataverseEndpoint` from `.local/config.json` (saved by skill 1);
  call it `{ENV_URL}`. Resolve the caller and their roles:

  ```
  az rest --method GET --resource "{ENV_URL}" --url "{ENV_URL}/api/data/v9.2/WhoAmI" --query "UserId" -o tsv
  ```

  ```
  az rest --method GET --resource "{ENV_URL}" --url "{ENV_URL}/api/data/v9.2/systemusers({USER_ID})/systemuserroles_association?$select=name" --query "value[].name" -o json
  ```

  The role is held if the returned role names include **`Environment Maker`**, or
  a superseding role (**`System Customizer`** or **`System Administrator`**).
  Treat an `Insufficient privileges` / `Authorization_RequestDenied` / forbidden
  response as "role not held". If the query errors for an unrelated reason
  (network, not signed in, no `dataverseEndpoint` yet), follow the gate's
  retry-then-attest fallback — never assume pass.

If `GATE_RESULT` is `"stop"`, **halt** — do not continue. Otherwise carry
`GATE_EVIDENCE` forward (it is recorded when S2.1 is updated).

---

## P2.1 — Install the ESS base agent (manual, gated)

Installing from AppSource is a portal action — it cannot be automated. First
check whether it is already installed (idempotent re-runs and resumes shouldn't
ask the user to reinstall):

```
python scripts/flightcheck/cli.py --checkpoint ESS-SOLN-001
```

- **`PASSED`** (the solution is already installed) → skip to **P2.2**.
- Anything else → show the install instructions below.

**Message:**

Let's install the Employee Self Service agent into your environment. Open
[AppSource](https://appsource.microsoft.com/) (or the Microsoft 365 admin
center), find **Employee Self Service**, and deploy it to the environment you
provisioned in the previous step. The install runs as a solution import — wait
until it finishes, then tell me it's done and I'll verify it.

**End message.**

Wait for the user to confirm they've completed the install, then go to **P2.2**.

---

## P2.2 — Verify the install (ESS-SOLN-001)

Run the verification checkpoint (this is the gate — never accept "installed"
without a re-check):

```
python scripts/flightcheck/cli.py --checkpoint ESS-SOLN-001
```

Branch on the result:

- **`PASSED`** (the ESS solution is present) → go to **P2.3**.
- **`FAILED`** (no `msdyn_copilotforemployeeselfservice*` solution found):

  **Message:**

  I can't find the Employee Self Service solution in this environment yet. If the
  install is still importing, give it a minute. Otherwise, double-check you
  deployed it to the correct environment, then tell me when it's ready and I'll
  re-check.

  **End message.**

  After the user confirms, re-run `--checkpoint ESS-SOLN-001`. Loop until it
  passes. While it is not yet passing, keep S2.1 `in-progress` (see P2.3 with
  `ACK=false`).
- **`WARNING`** (the check couldn't reach Dataverse — expired token or a
  transient error). Re-run once; if it still warns, surface the message to the
  user and treat it like `FAILED` (the install is unverified, so the row cannot
  complete).

---

## P2.3 — Record S2.1 (manual gate — needs acknowledgement)

Row S2.1 is **manual-gated**: the AppSource install is a human portal action, so
a passing checkpoint alone does not complete the row — it needs the user's
explicit acknowledgement.

When `ESS-SOLN-001` is `PASSED`, present it as evidence and ask the user to
confirm:

**Message:**

The Employee Self Service solution is installed and verified in your environment.

**End message.**

Then, per [`checklist-updater.md`](../shared/checklist-updater.md)'s manual rule,
ask for an explicit acknowledgement (only `ACK=true` on an explicit "Yes"). Update
**S2.1** via [`checklist-updater.md`](../shared/checklist-updater.md) with:

- `STEP_ID="S2.1"`
- `GATE="manual"`
- `CHECKPOINT_RESULT="PASSED"` (or `"FAILED"` / `null` while still verifying)
- `ACK` = the user's explicit confirmation
- Persist the P2.0 `GATE_EVIDENCE`.

On `ACK=true` with `CHECKPOINT_RESULT="PASSED"`, the row becomes `done`. A
checkpoint pass without acknowledgement leaves the row `in-progress`.

---

## Done

**Message:**

The base Employee Self Service agent is installed and verified. Next, we'll set
up the Workday connection (skill 3).

**End message.**

S2.1 is now recorded in the checklist. Stop here — the Workday connection is a
separate skill.
