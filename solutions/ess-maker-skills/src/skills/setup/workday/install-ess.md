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
  az rest --method GET --resource "{ENV_URL}" --url "{ENV_URL}/api/data/v9.2/systemusers({USER_ID})/systemuserroles_association?%24select=name" --query "value[].name" -o json
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

## P2.1 — Install the ESS base agent (manual portal step)

Installing from AppSource is a portal action — it cannot be automated. First
check whether it is already installed (idempotent re-runs and resumes shouldn't
ask the user to reinstall):

**Message:**

First, let me check whether the Employee Self Service agent is already installed
in this environment.

**End message.**

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

**Message:**

Now I'll confirm the Employee Self Service agent solution actually landed in your
environment.

**End message.**

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
  passes. While it is not yet `PASSED` the row stays `in-progress`; a `FAILED`
  result parks it `blocked` (see P2.3).
- **`WARNING`** (the check couldn't reach Dataverse — expired token or a
  transient error). Re-run once; if it still warns, surface the message to the
  user; the install is unverified, so the row cannot complete and stays
  `in-progress`.

---

## P2.3 — Record S2.1 (prog gate — auto-completes on a passing check)

Row S2.1 is **programmatically gated**: `ESS-SOLN-001` queries Dataverse and
definitively proves whether the ESS solution landed, so a passing check completes
the row on its own — no separate acknowledgement is needed. (The install action
in P2.1 is still a human portal step; only its *outcome* is verified here.)

When `ESS-SOLN-001` is `PASSED`, tell the user and record the row:

**Message:**

The Employee Self Service solution is installed and verified in your environment.

**End message.**

Update **S2.1** via [`checklist-updater.md`](../shared/checklist-updater.md) with:

- `STEP_ID="S2.1"`
- `GATE="prog"`
- `CHECKPOINT_RESULT="PASSED"` (or `"FAILED"` / `"WARNING"` / `null` while still
  verifying)
- Persist the P2.0 `GATE_EVIDENCE`.

Per the updater's U.2 gate table, a `prog` row maps `PASSED` → `done`,
`FAILED` → `blocked`, and `WARNING` / `null` → `in-progress`. Only a `PASSED`
result completes the row — never mark it `done` on an unverified `WARNING`.

---

## Done

**Message:**

The base Employee Self Service agent is installed and verified. Next, we'll set
up the Workday connection (skill 3).

**End message.**

S2.1 is now recorded in the checklist. Stop here — the Workday connection is a
separate skill.
