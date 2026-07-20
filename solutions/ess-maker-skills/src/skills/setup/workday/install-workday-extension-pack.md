<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Skill 5 — Install the Workday Extension Pack

Role: **Environment Maker**. This skill installs the Workday extension pack into
the ESS agent, binds its connection references, verifies the Workday and Dataverse
connections and the captured REST base URL, confirms the cloud flows are on, wires
the user-context redirect topic, and records the firewall allowlisting the Workday
managed connectors need. It owns master-checklist rows **S5.1 through S5.8**.

Depends on skill 4 (the Workday tenant must already be configured — this skill
consumes the `oauthClientId` / `tokenEndpoint` / `restBaseUrl` / `soapBaseUrl` /
`appIdUri` skill-4 captured) and, transitively, skills 1–3 (the environment,
Dataverse, ESS base agent, and Workday Entra app must all exist).

This skill **reuses** three checkpoints already owned by
`checks/workday.py` — `WD-PKG-001` (S5.1), `WD-CONN-012` (S5.2), and `WD-FLOW-*`
(S5.6) — and **mints** five new ones in `checks/workday_extension.py`:
`WD-CONN-AUTH-001` (S5.3), `DV-CONN-001` (S5.4), `WD-REST-001` (S5.5),
`WD-REST-002` (S5.7), and `WD-NET-001` (S5.8).

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading. **Never** show internal variable names or IDs in chat.

**Checkpoints this skill drives (run each in isolation):**

| Step | Checkpoint | Gate |
|------|-----------|------|
| S5.1 | `WD-PKG-001` *(reuse)* — extension pack installed (connection references present) | manual |
| S5.2 | `WD-CONN-012` *(reuse)* — Workday connection reference (`ff0df`) bound to an active connection | prog |
| S5.3 | `WD-CONN-AUTH-001` — Workday connection authentication is **Microsoft Entra ID Integrated** | attest |
| S5.4 | `DV-CONN-001` — Dataverse connection reference (`92b66`) bound, active, own account | prog |
| S5.5 | `WD-REST-001` — REST base URL present and trimmed to `/api` | prog |
| S5.6 | `WD-FLOW-*` *(reuse)* — Workday cloud flows enabled | prog |
| S5.7 | `WD-REST-002` — user-context redirect topic wired (rollback checkpoint first) | prog w/ rollback |
| S5.8 | `WD-NET-001` — Workday REST + SOAP endpoints allowlisted at the firewall | attest |

Run any one with:

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

`WD-CONN-AUTH-001` and `WD-NET-001` always report `MANUAL`: the first echoes the
observed connection auth parameter set for the operator to confirm (the Power
Platform admin API exposes no kit-verifiable fingerprint for the
"Microsoft Entra ID Integrated" auth type), and the second echoes the endpoints
InfoSec/IT must allowlist (the kit has no reliable outbound-path probe). A
`MANUAL` result is **never** completion on its own — those attest rows also need
the user's explicit acknowledgement (enforced by
[`shared/checklist-updater.md`](../shared/checklist-updater.md)).

**Build order.** The rows are worked in number order, but note that `WD-PKG-001`
(P5.1) must run **first**: it hydrates the cached Workday connection references and
the install-flavor verdict that `WD-CONN-012` (P5.2) and `WD-CONN-AUTH-001` (P5.3)
read. Each section states which checklist row it completes.

**On every resume, always re-run P5.0 (role gate) first** — it is read-only — then
**re-run P5.1 (`WD-PKG-001`)** before working the first incomplete row, because the
downstream connection checks depend on the cached references it populates. After
re-running P5.0 and P5.1, skip any row whose `setupStatus` state is already `done`.

---

## P5.0 — Role gate (Environment Maker)

Apply the shared [`permission-gate.md`](../shared/permission-gate.md) before any
extension-pack work, with:

- `REQUIRED_ROLE` = `"Environment Maker"`
- `GATE_MODE` = `"programmatic"`
- `STEP_ID` = `"S5.1"`
- `ROLE_QUERY` = a Dataverse security-role membership check for the signed-in
  user. Read `dataverseEndpoint` from `.local/config.json` (saved by skill 1);
  call it `{ENV_URL}`. Resolve the caller and their roles:

  ```
  az rest --method GET --resource "{ENV_URL}" --url "{ENV_URL}/api/data/v9.2/WhoAmI" --query "UserId" -o tsv
  ```

  ```
  az rest --method GET --resource "{ENV_URL}" --url "{ENV_URL}/api/data/v9.2/systemusers%28{USER_ID}%29/systemuserroles_association?%24select=name" --query "value[].name" -o json
  ```

  (Percent-encode the key-lookup parentheses — `%28`/`%29`, not `(`/`)` — and the
  OData `$` — `%24select`. On Windows the `az` launcher is a `cmd.exe` batch
  wrapper: a raw `)` closes a batch block and the call fails with
  `... was unexpected at this time`, so the encoded form runs first-try on every
  shell.)

  The role is held if the returned role names include **`Environment Maker`**, or
  a superseding role (**`System Customizer`** or **`System Administrator`**).
  Treat an `Insufficient privileges` / `Authorization_RequestDenied` / forbidden
  response as "role not held". If the query errors for an unrelated reason
  (network, not signed in, no `dataverseEndpoint` yet), follow the gate's
  retry-then-attest fallback — never assume pass.

If `GATE_RESULT` is `"stop"`, **halt** — do not continue. Otherwise carry
`GATE_EVIDENCE` forward (it is recorded when the S5 rows are updated).

---

## P5.1 — Install the extension pack & verify it landed (WD-PKG-001) *(completes S5.1)*

Installing the Workday extension pack is a Copilot Studio **Settings → Customize**
action — it cannot be automated. First check whether it is already installed
(resumes and idempotent re-runs must not ask the user to reinstall):

**Message:**

First, let me check whether the Workday extension pack is already installed in
your agent.

**End message.**

```
python scripts/flightcheck/cli.py --checkpoint WD-PKG-001
```

- **`PASSED`** (the pack's Workday connection references are present) → the pack is
  installed; go to **record S5.1** below.
- **`NotConfigured`** / **`FAILED`** → the pack isn't installed yet. First surface
  the connection values the user will paste into the extension pack's connection
  form, then show the install steps.

  Read the captured values from `.local/connect/workday/config.json`: `tenant`
  (persisted by skill-3/4), and `tokenEndpoint`, `oauthClientId`, `soapBaseUrl`,
  and `restBaseUrl` (persisted by skill-4). Build the **Microsoft Entra resource
  URL** as `http://www.workday.com/{tenant}` — the Workday tenant short name (the
  same one in the Workday tenant URL, e.g. `acme_dpt1`), **not** the Entra App ID
  URI. Present each with its Copilot Studio form label — never the internal field
  names. If `tenant` is blank, derive it from the Workday tenant URL (the
  `{tenant}` segment of `soapBaseUrl` / `oauthTokenUrl`); if any other value is
  blank, it was not captured — go back to skill-4 (the Workday tenant
  configuration, P4.3) to capture it before installing.

  **Message:**

  Before we install, here are the Workday connection values you'll need during
  setup. Keep them handy — you'll paste them into the connection form when the
  installer prompts you:

  - **Workday tenant name:** {tenant}
  - **Microsoft Entra resource URL:** http://www.workday.com/{tenant}
  - **Workday OAuth token URL (Token Endpoint):** {tokenEndpoint}
  - **Client ID:** {oauthClientId}
  - **SOAP base URL:** {soapBaseUrl}
  - **REST base URL:** {restBaseUrl}

  **End message.**

  **Message:**

  Now let's install the Workday extension pack into your Employee Self-Service
  agent:

  1. In Copilot Studio, open your agent.
  2. Go to **Settings**, then select **Customize** in the left navigation.
  3. Find **Workday** in the list and choose **Install**.
  4. When the installer prompts you to set up connections, create each one by
     selecting the ellipses (**...**) on its right and signing in — use the
     connection values above where the form asks for them.

  The install runs as a solution import — wait until it finishes, then tell me it's
  done and I'll verify it.

  **End message.**

  Wait for the user to confirm, then re-run `--checkpoint WD-PKG-001`. Loop until
  it passes. While it is not yet passing, keep S5.1 `in-progress`.

**Record S5.1 (manual gate — needs acknowledgement).** When `WD-PKG-001` is
`PASSED`, present it as evidence:

**Message:**

The Workday extension pack is installed and its connection references are present
in your environment.

**End message.**

Then, per [`checklist-updater.md`](../shared/checklist-updater.md)'s manual rule,
ask for an explicit acknowledgement and update **S5.1** via
[`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S5.1"`,
`GATE="manual"`, `CHECKPOINT_RESULT="PASSED"`, `ACK` = the user's explicit
confirmation. Persist the P5.0 `GATE_EVIDENCE`. Then continue to P5.2.

---

## P5.2 — Verify the Workday connection reference is bound (WD-CONN-012) *(completes S5.2)*

**Message:**

Now I'll check the Workday connection is bound to an active, signed-in connection.

**End message.**

```
python scripts/flightcheck/cli.py --checkpoint WD-CONN-012
```

`WD-CONN-012` reads the cached references from P5.1 and confirms the expected
Workday reference(s) for the detected install flavor are each bound to an active
connection.

- **`PASSED`** → update **S5.2** via
  [`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S5.2"`,
  `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`. Continue to P5.3.
- **`FAILED`** (a reference is unbound or inactive — the result names which):

  **Message:**

  Your Workday connection isn't fully bound yet. In Copilot Studio, open your
  agent's **Connections**, find the Workday connection, and either create it or
  re-authenticate it so it shows as connected. Then tell me and I'll re-check.

  **End message.**

  After the user confirms, re-run `--checkpoint WD-CONN-012`. Loop until it
  passes; leave S5.2 `in-progress` until then.

---

## P5.3 — Confirm the Workday connection authentication type (WD-CONN-AUTH-001) *(completes S5.3)*

**Message:**

Now I'll read how the Workday connection signs in so you can confirm it uses
Microsoft Entra ID.

**End message.**

```
python scripts/flightcheck/cli.py --checkpoint WD-CONN-AUTH-001
```

This is an **attest** row: `WD-CONN-AUTH-001` always reports `MANUAL`. It reads the
cached Workday connection reference and echoes the observed connection auth
parameter set (and owner) for you to confirm — the simplified extension pack's
Workday connection must use **Microsoft Entra ID Integrated** (Entra SSO), not
Basic/ISU or a client-secret grant.

You will already have rendered the checkpoint's result in chat (the
post-checkpoint display, U.0a). Ask the user to confirm the auth type:

**Message:**

Please confirm your Workday connection's authentication type. In Copilot Studio (or
the Power Platform **Connections** list), open the Workday connection and check that
its authentication is **Microsoft Entra ID Integrated**. Is it?

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Workday connection auth",
    "question": "Is the Workday connection's authentication 'Microsoft Entra ID Integrated'?",
    "options": [
      { "label": "Yes", "recommended": true },
      { "label": "No / not sure" }
    ],
    "allowFreeformInput": false
  }
]
```

- **"Yes"** → update **S5.3** via
  [`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S5.3"`,
  `GATE="attest"`, `CHECKPOINT_RESULT="MANUAL"`, `ACK=true`. Continue to P5.4.
- **"No / not sure"** → leave S5.3 `in-progress`. Have the user delete the Workday
  connection, re-create it choosing **Microsoft Entra ID Integrated**, and re-bind
  the connection reference (re-run P5.2), then re-attest here.

---

## P5.4 — Verify the Dataverse connection reference (DV-CONN-001) *(completes S5.4)*

**Message:**

Now I'll check the Dataverse connection is bound to an active connection owned by
your account.

**End message.**

```
python scripts/flightcheck/cli.py --checkpoint DV-CONN-001
```

`DV-CONN-001` confirms the extension pack's Dataverse connection reference
(`…_92b66`) is bound to an **active** connection and echoes its owner so you can
confirm it is your own account.

- **`PASSED`** → present the echoed owner and update **S5.4** via
  [`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S5.4"`,
  `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`. Continue to P5.5.
- **`FAILED`** (unbound or inactive) / **`NotConfigured`** (reference missing):

  **Message:**

  The Dataverse connection for the Workday pack isn't bound to an active connection
  you own yet. In Copilot Studio, open your agent's **Connections**, find the
  Dataverse connection, and bind or re-authenticate it with your own account. Then
  tell me and I'll re-check.

  **End message.**

  After the user confirms, re-run `--checkpoint DV-CONN-001`. Loop until it passes;
  leave S5.4 `in-progress` until then.
- **`Skipped`** (Dataverse token unavailable) → re-authenticate and re-run; do not
  complete the row on a skip.

---

## P5.5 — Verify the REST base URL (WD-REST-001) *(completes S5.5)*

**Message:**

Now I'll confirm the Workday REST address is captured and trimmed correctly.

**End message.**

```
python scripts/flightcheck/cli.py --checkpoint WD-REST-001
```

`WD-REST-001` is a pure-config check: the captured `restBaseUrl` must be present and
trimmed to end at `/api` (e.g. `https://<host>/ccx/api`) — a trailing path or
version segment breaks the simplified pack's REST `/workers/me` call.

- **`PASSED`** → update **S5.5** via
  [`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S5.5"`,
  `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`. Continue to P5.6.
- **`FAILED`** (present but not trimmed) → the captured URL has extra path. Re-run
  the shared [`connection-fields.md`](../shared/connection-fields.md) REST-URL
  trimming (or correct `restBaseUrl` in `.local/connect/workday/config.json`), then
  re-run the checkpoint. Leave S5.5 `in-progress` until it passes.
- **`NotConfigured`** (no `restBaseUrl` captured) → go back to skill-4's connection
  capture (P4.3) to capture it, then re-check.

---

## P5.6 — Verify the Workday cloud flows are on (WD-FLOW-*) *(completes S5.6)*

**Message:**

Now I'll confirm the Workday cloud flows are all turned on.

**End message.**

```
python scripts/flightcheck/cli.py --checkpoint WD-FLOW-*
```

`WD-FLOW-*` (reused from `checks/workday.py`) expands to one row per Workday cloud
flow and confirms each is enabled.

- **All `PASSED`** → update **S5.6** via
  [`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S5.6"`,
  `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`. Continue to P5.7.
- **Any `FAILED`** (a flow is off — the result names which):

  **Message:**

  One or more of the Workday cloud flows is turned off. In Power Platform, open
  **Solutions → the Workday solution → Cloud flows**, and turn on any flow that's
  off. Then tell me and I'll re-check.

  **End message.**

  After the user confirms, re-run `--checkpoint WD-FLOW-*`. Loop until all pass;
  leave S5.6 `in-progress` until then.

---

## P5.7 — Wire the user-context redirect topic (WD-REST-002) *(completes S5.7)*

The agent's **User Context** topic must redirect to the Workday user-context system
topic, or every Workday topic fails at runtime with "This feature isn't available
yet." On the simplified pack this is the REST V2 topic
(`WorkdaySystemGetUserContextV2`); on the legacy path this row is **not applicable**
and `WD-REST-002` reports `Skipped`.

First check the current state:

**Message:**

Now I'll check whether the user-context redirect is already wired into your agent.

**End message.**

```
python scripts/flightcheck/cli.py --checkpoint WD-REST-002
```

- **`PASSED`** (the redirect is already wired) → update **S5.7** via
  [`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S5.7"`,
  `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`. Continue to P5.8.
- **`Skipped`** (legacy install path) → this row does not apply; record it as
  `Skipped` and continue to P5.8.
- **`FAILED`** (redirect not wired) / **`NotConfigured`** (agent not extracted
  locally) → wire it, following the same rule as the connect skill (step 3, §3.5d).

**Before writing to the live agent, surface the consent** — this changes the
agent and is hard to undo without the checkpoint:

**Message:**

I'll wire the **User Context** topic to call the Workday flow on every
conversation. Without this, Workday topics fail with "This feature isn't available
yet." I'll save a rollback checkpoint named `Add User Context redirect to Workday`
first so you can undo it if anything looks off.

**End message.**

Save a rollback checkpoint:

```
python scripts/checkpoint.py "Add User Context redirect to Workday"
```

Resolve the installed Workday "Set User Context" system topic's dialog id under
`.local/agents/{slug}/topics/` (do **not** assume the legacy name on a simplified
install — use the actual `WorkdaySystemGetUserContextV2` topic), then set the
agent's `workspace/agents/{slug}/topics/user-context-setup.mcs.yml` `OnRedirect` to
a `BeginDialog` calling that dialog id:

```yaml
kind: AdaptiveDialog
beginDialog:
  kind: OnRedirect
  id: main
  priority: 0
  actions:
    - kind: BeginDialog
      id: bfT9Kx
      displayName: Redirect to Workday System Get User Context
      dialog: {USER_CONTEXT_DIALOG}
```

Push the change:

```
python scripts/push.py --yes
```

Then re-verify:

```
python scripts/flightcheck/cli.py --checkpoint WD-REST-002
```

On `PASSED`, update **S5.7** via
[`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S5.7"`,
`GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`, and continue to P5.8. If it still
fails, roll back with the checkpoint you saved and re-attempt; leave S5.7
`in-progress` until it passes.

---

## P5.8 — Record the firewall allowlisting (WD-NET-001) *(completes S5.8)*

**Message:**

Now I'll list the Workday endpoints your firewall needs to allow — this is a
record-keeping step, not a live test.

**End message.**

```
python scripts/flightcheck/cli.py --checkpoint WD-NET-001
```

This is an **attest** row: `WD-NET-001` always reports `MANUAL`. The kit cannot
verify corporate firewall rules (a local probe would only prove this machine's
egress, not the managed-connector outbound path), so it echoes the Workday REST and
SOAP hosts that InfoSec/IT must allowlist for the Power Platform managed connectors.

You will already have rendered the echoed REST + SOAP hosts in chat (the
post-checkpoint display, U.0a). Ask the user to confirm the allowlisting is in place:

**Message:**

The last step is a network one. Your InfoSec/IT team needs to allowlist outbound
access from the Power Platform Workday managed connectors to your Workday REST and
SOAP hosts (shown above). Has that firewall allowlisting been put in place?

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Firewall allowlisting",
    "question": "Have the Workday REST + SOAP endpoints been allowlisted at the firewall?",
    "options": [
      { "label": "Yes", "recommended": true },
      { "label": "Not yet" }
    ],
    "allowFreeformInput": false
  }
]
```

- **"Yes"** → update **S5.8** via
  [`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S5.8"`,
  `GATE="attest"`, `CHECKPOINT_RESULT="MANUAL"`, `ACK=true`. Persist the P5.0
  `GATE_EVIDENCE`.
- **"Not yet"** → leave S5.8 `in-progress`. Give InfoSec/IT the echoed REST and
  SOAP hosts to allowlist, and re-attest once the change is in place.

---

## P5.9 — Full Workday readiness report (`--scope workday`, HTML) *(report only — no checklist row)*

Once S5.1–S5.8 are all `done` (or S5.7 `Skipped` on the legacy path), run the
**full Workday-scope** FlightCheck once. Unlike the per-row `--checkpoint` runs
above — which never open a report — the full-scope run **writes and opens the
consolidated HTML readiness report** at `workspace/flightcheck/`, so the maker has
a single Workday summary to review and share.

**Message:**

Now I'll run a full Workday readiness check to bring all of these results together
into one report you can review and share.

**End message.**

This run also exercises the Workday SOAP workflow tests, which need the Workday
**password**. **Never** ask for it in chat — the CLI prompts for it securely in the
terminal (masked `getpass`), or reads it from the `WORKDAY_PASSWORD` environment
variable, so the secret never lands in the transcript. Run it in the terminal:

```
python scripts/flightcheck/cli.py --scope workday
```

The run writes the report to `workspace/flightcheck/` and opens it in the browser.
This report is **advisory**: it never blocks setup and never changes any S5 row's
state — rows S5.1–S5.8 were already completed by their own checkpoints above. If
the report shows a row regressed, send the user back to the owning step to
re-verify; do not silently flip its checklist state here.

---

## Done

When S5.1–S5.8 are all `done` (or S5.7 `Skipped` on the legacy path) and the P5.9
Workday readiness report has been generated, return control to the setup router
(`SKILL.md`) to resume at the next unverified row.

**Message:**

Your Workday extension pack is installed and wired — the connections are bound and
authenticated, the REST endpoint and cloud flows are verified, the user-context
redirect is in place, and the network allowlisting is recorded. Next up is creating
your first custom Workday topic.

**End message.**
