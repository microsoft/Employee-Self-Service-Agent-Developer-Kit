# Permission Gate (Shared)

A reusable **role check → specific named error → stop** routine. Every Workday
setup skill applies this fragment before it performs role-restricted work, so no
skill duplicates inline role logic.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling.

**Inputs from the calling file:**
- `REQUIRED_ROLE` — the human-readable role name to require (e.g.
  `"Workday Administrator"`, `"Power Platform Administrator"`,
  `"Application Administrator"`).
- `GATE_MODE` — `"programmatic"` or `"attested"` (see "Choosing a mode" below).
- `STEP_ID` — the master-checklist Step ID this gate protects (e.g. `"S4.1"`),
  used only to record evidence.
- `ROLE_QUERY` — *(programmatic mode only)* the command/check that proves the
  caller holds the role (the calling file supplies it; examples below).

**Outputs to the calling file:**
- `GATE_RESULT` — `"pass"` or `"stop"`. On `"stop"`, the calling file must halt.
- `GATE_EVIDENCE` — an object recording how the gate was satisfied; the caller
  persists it under `setupStatus["{STEP_ID}"].verifiedBy` in
  `.local/connect/workday/config.json` (see `config-schema.md`):
  - `verifiedBy` ∈ `"programmatic"` \| `"attested"`.
  - `note` — short free text (e.g. the role-query result, or the user's
    attestation timestamp/identity).

---

## Choosing a mode

The gating mechanism differs by role because not every role has a queryable
directory:

| Role family | Mode | How verified |
|-------------|------|--------------|
| Entra roles (App Admin, Cloud App Admin, Global Admin, Priv Role Admin) | `programmatic` | Microsoft Graph role / privilege query |
| Power Platform Admin | `programmatic` | Power Platform admin API |
| Dataverse maker / system roles | `programmatic` | Dataverse security-role query |
| **Workday Administrator** | `attested` | No directory here → explicit named-role attestation + captured evidence |
| **InfoSec / IT** (firewall allowlisting) | `attested` | No directory here → explicit named-role attestation + captured evidence |

The calling file picks `GATE_MODE` from this table. **Never** silently pass an
attested role — always require the explicit confirmation in section G.2.

---

## G.1 — Programmatic gate

Use when `GATE_MODE` is `"programmatic"`.

Run the `ROLE_QUERY` the calling file supplied. Examples of what a caller passes:

- **Entra role (Graph):**
  ```
  az rest --method GET --url "https://graph.microsoft.com/v1.0/me/memberOf?%24select=displayName" --query "value[].displayName" -o json
  ```
  (OData options are percent-encoded — `%24select` not `$select` — so the URL
  survives PowerShell/bash `$`-expansion and runs first-try on every shell.)
  Pass if the result contains a directory role that grants `REQUIRED_ROLE`
  (e.g. `Application Administrator`, `Cloud Application Administrator`,
  `Global Administrator`).
- **Power Platform Admin / Dataverse role:** the caller supplies the specific
  admin-API or Dataverse query and the expected value.

**If the query proves the role is held:**
- Set `GATE_RESULT = "pass"`.
- Set `GATE_EVIDENCE = { "verifiedBy": "programmatic", "note": "<matched role/query result>" }`.
- Return to the calling file.

**If the query proves the role is NOT held** (or returns an
`Insufficient privileges` / `Authorization_RequestDenied` error — mirror the
existing pattern in `connect/azure/app-registration.md` section B.2):

**Message:**

This step requires the **{REQUIRED_ROLE}** role, and your account doesn't
have it. Ask your administrator to grant this role, then come back and run
this step again.

**End message.**

- Set `GATE_RESULT = "stop"`.
- Return to the calling file. **The caller must halt — do not proceed.**

**If the query itself fails** for an unrelated reason (network, not logged in):
retry once. If it still fails, **do not** assume pass — fall back to the
attestation gate in G.2 (so a check error never silently grants access),
recording `note` = the query error.

---

## G.2 — Attestation gate

Use when `GATE_MODE` is `"attested"` (Workday Administrator, InfoSec/IT), or as
the fallback when a programmatic query errored.

**Message:**

This step requires the **{REQUIRED_ROLE}** role. I can't verify that
automatically for this system, so I need you to confirm you (or the person
doing this step) hold that role before we continue.

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Confirm role",
    "question": "Do you have the {REQUIRED_ROLE} role to perform this step?",
    "options": [
      { "label": "Yes, I have this role", "recommended": true },
      { "label": "No / not sure" }
    ],
    "allowFreeformInput": false
  }
]
```

**If the user chose "Yes, I have this role":**
- Set `GATE_RESULT = "pass"`.
- Set `GATE_EVIDENCE = { "verifiedBy": "attested", "note": "user attested {REQUIRED_ROLE} for {STEP_ID}" }`.
- Return to the calling file.

**If the user chose "No / not sure":**

**Message:**

No problem — this step needs the **{REQUIRED_ROLE}** role. Ask whoever holds
that role to run it, then come back and continue.

**End message.**

- Set `GATE_RESULT = "stop"`.
- Return to the calling file. **The caller must halt — do not proceed.**

> An attested `"pass"` records that the role was **claimed**, not directory-proven.
> It satisfies the *gate*, but it does **not** by itself complete the checklist row
> — the row still needs its own captured evidence/acknowledgement per
> `checklist-updater.md`.
