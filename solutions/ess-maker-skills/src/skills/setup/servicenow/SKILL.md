<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# ServiceNow Setup Orchestrator

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading.

This router sequences the ServiceNow setup skills using the master checklist as a
**resume-aware spine**: it renders the working checklist on first run, resumes at
the first unverified step, and dispatches to the owning skill's playbook. It
**never** advances past a `MANUAL` / attestation row on a flightcheck pass alone —
those require explicit user acknowledgement (enforced by
[`shared/checklist-updater.md`](../shared/checklist-updater.md)).

Groups 1–2 (Power Platform environment, ESS base agent) are the same shared
prerequisites the Workday setup verifies; if they are already `done` from a prior
setup, this router resumes past them. Groups 4 and 5 are the **mutually-exclusive
sign-in paths** — see **Auth path** below.

---

## Handling ServiceNow credentials — never put secrets in chat

Some ServiceNow sign-in paths involve secrets (a certificate private key, or a
client secret on the legacy paths). **Never** ask for a secret with a chat question
(`vscode_askQuestions`, or a plain "paste your …" message) — the chat question tool
has no masked-input option, so anything typed is recorded verbatim in the transcript.

- Certificate material is generated and referenced by **file path**; the private key
  (`.pfx`) is **never** pasted into chat or written into `config.json` (see
  `setup/servicenow/provision-servicenow-certificate.md`).
- Non-secret connection identifiers (instance URL, Entra app/client IDs, scope,
  Application ID URI) are safe to capture in chat.

The default supported paths (`entra_user`, `entra_certificate`) use Microsoft Entra
sign-in and do **not** require a ServiceNow password in chat.

---

## Auth path — pick the group to render (S3.1 output)

ServiceNow has two supported sign-in paths. **S3.1** captures the choice into
`authType` in `.local/connect/servicenow/config.json`:

- `authType == "entra_user"` → render **group 4** (user sign-in); **omit group 5**.
- `authType == "entra_certificate"` → render **group 5** (certificate); **omit group 4**.

Until S3.1 has been completed and `authType` is set, render **neither** group 4 nor
group 5 — only groups 1–3, plus 6–7 shown as upcoming. Once `authType` is known,
always render the matching group and never the other. The omitted group's Step IDs
are treated as not-applicable: they are neither shown nor counted toward completion.

---

## Start

1. **Working copy.** If `.local/setup/servicenow/tasks.md` does not exist, render it
   by copying the template `src/skills/setup/servicenow/tasks.md`, dropping the
   auth-path group that does not match `authType` (see **Auth path**; if `authType`
   is not set yet, keep both variant groups out of the rendered copy for now and add
   the matching one once S3.1 runs), and dropping the **group-6 per-product rows**
   (the install sub-block **6b** and the flows-and-finish sub-block **6d**) for any
   product not in `scope` — keep only the always-on **6a. Create connections** and
   **6c. Shared connection** sub-blocks until `scope` is known, then add the in-scope
   product's **6b**/**6d** rows. Do not hand-edit its status markers — the shared
   checklist-updater writes them.

2. **Resume point.** Read `setupStatus` **and** `productStatus` in
   `.local/connect/servicenow/config.json` (the durable source of truth; the tasks
   file is only the view). If the file or a key is missing, treat every row as
   `pending`. A **shared** row counts as complete only when
   `setupStatus["{Step}"].state` is `"done"`; a **per-product** row (the install
   `S6.1`, turn-on-flows `S6.3`, connect-invoker `S6.4`, share `S6.5`, and portal
   `S6.6`, one set per in-scope product) counts as complete only when
   `productStatus["{product}"]["{Step}"].state` is `"done"`. A product is fully set
   up only when the shared steps **and** that product's own steps are all `done`.

3. **Show the checklist, then find where to resume.** Determine each item's state
   using the **same routing as step 2**: a shared row from `setupStatus["{Step}"]`,
   and a per-product row from `productStatus["{product}"]["{Step}"]` (never from
   `setupStatus`). In both cases: ✅ = `done`, 🔄 = `in-progress`, ⛔ = `blocked`,
   ⬜ = `pending` or unset. Show the checklist **grouped exactly as in the template** —
   the group headings and item titles below are verbatim from
   `src/skills/setup/servicenow/tasks.md`; render every group and every item that
   applies to the selected `authType`, replacing each `{m}` with that item's marker.
   **Never show Step IDs or checkpoint IDs.**

   **Message:**

   Here's the checklist of steps:

   **1. Power Platform environment**
   - {m} Set up your Power Platform environment
   - {m} Confirm Copilot Studio capacity

   **2. Employee Self-Service base agent**
   - {m} Install the Employee Self-Service agent

   **3. ServiceNow connection basics**
   - {m} Capture your ServiceNow instance and scope
   - {m} Confirm your maker permissions
   - {m} Confirm your ServiceNow user record

   **4. ServiceNow single sign-on (user sign-in)** — _shown only for the user sign-in path_
   - {m} Create the ServiceNow sign-in app
   - {m} Grant admin consent
   - {m} Register the ServiceNow OIDC provider
   - {m} Map the sign-in identity to a ServiceNow user

   **5. ServiceNow single sign-on (certificate)** — _shown only for the certificate path_
   - {m} Create the certificate sign-in apps
   - {m} Upload the signing certificate and trust it
   - {m} Register the ServiceNow OIDC provider and system user

   **6. ServiceNow extension pack and connection**
   - {m} Create the ServiceNow and Dataverse connections
   - {m} Install the ServiceNow extension pack
   - {m} Connect ServiceNow and Dataverse
   - {m} Turn on the ServiceNow flows
   - {m} Connect ServiceNow to your agent's flows
   - {m} Set the Portal Base URL

   **7. Validate and hand off**
   - {m} Run an end-to-end validation
   - {m} Create your first ServiceNow topic

   Picking up at: {title of the first item whose state is not `done`}.

   **End message.**

   (When rendering, show **only** the auth-path group that matches `authType`. Before
   S3.1 sets `authType`, show groups 4 and 5 headings as "coming up once you pick a
   sign-in method" or omit them — do not present both as active.)

   Then walk the applicable items in Step order (S1.1, S1.2, S2.1, S3.1 … S7.2 —
   these IDs are internal only), pick the first whose state is not `done`, and
   dispatch by that Step in **Dispatch** below. A skill's playbook may re-run its own
   idempotent foundation steps (role gate, resource lookup) ahead of the resume item
   to rehydrate in-memory state — follow the playbook's stated build order.

4. If **every** applicable item is `done`:
   - If **both** ServiceNow products (HRSD **and** ITSM) are already in `scope`, show
     the **All done** message and stop.
   - If **exactly one** product is in `scope`, the other can still be added to this
     same agent without redoing the shared setup — show the **All done** message's
     *add-a-product* variant and, if the maker accepts, run the **Add a product**
     transition below. Otherwise stop.

---

## Dispatch

**Persist each row the moment its checkpoint passes.** Every skill calls
[`shared/checklist-updater.md`](../shared/checklist-updater.md) per row, inline —
updating both the working checklist and the durable state mirror (shared rows in
`setupStatus`, per-product rows in `productStatus.<product>`, per
[`shared/checklist-updater.md`](../shared/checklist-updater.md)) immediately — and
**must not** batch those writes to the end of its run. This keeps
progress crash-safe: if a skill errors midway, the rows already verified stay
complete and this router resumes at the first row that isn't.

### S1.1 or S1.2 — Provision Power Platform environment (skill-1)

Read `src/skills/setup/servicenow/provision-power-platform-environment.md` and follow
it. That playbook role-gates (Power Platform Administrator), verifies or creates the
environment + Dataverse (`ENV-001`, `ENV-002`), verifies Copilot Studio message
capacity (`ENV-CAPACITY-001`), and updates rows **S1.1** and **S1.2** through the
shared checklist-updater. These are the same shared checkpoints the Workday setup
uses; if they already passed, the playbook confirms and moves on.

When it returns, go back to **Start** to resume at the next unverified row.

### S2.1 — Install the ESS base agent (skill-2)

Read `src/skills/setup/servicenow/install-ess.md` and follow it. That playbook
role-gates (Environment Maker), guides the manual AppSource install of the base
Employee Self Service agent, verifies the solution landed (`ESS-SOLN-001`), and
updates row **S2.1** through the shared checklist-updater (prog gate — auto-completes
on a passing `ESS-SOLN-001`).

When it returns, go back to **Start** to resume at the next unverified row.

### S3.1 through S3.3 — Capture ServiceNow connection basics (skill-3)

Read `src/skills/setup/servicenow/capture-servicenow-config.md` and follow it. That
playbook applies the legacy scope gate, captures the instance URL, in-scope products
(HRSD / ITSM), connector, and **sign-in method** (`authType`) into
`.local/connect/servicenow/config.json` (`SN-CONFIG-001`, **S3.1** — and once
`authType` is set, adds the matching auth-path group to the working checklist),
probes maker permissions (`SN-PERM-001`, **S3.2**), and confirms the signed-in
person exists as an active ServiceNow user (`SN-USER-001`, **S3.3** — attest; this is
the user-presence check the spec omits). It updates rows S3.1–S3.3 through the shared
checklist-updater.

When it returns, go back to **Start**. The next unverified row now belongs to the
auth-path group selected in S3.1.

### S4.1 through S4.4 — ServiceNow single sign-on, user path (skill-4)

**Only when `authType == "entra_user"`.** Read
`src/skills/setup/servicenow/provision-servicenow-entra-user.md` and follow it. That
playbook role-gates (App / Cloud Application Administrator), creates the ServiceNow
sign-in Entra app and exposes the scope (`SN-ENTRA-SCOPE-001`, **S4.1**), grants and
consents the Graph permissions (`SN-ENTRA-CONSENT-001`, **S4.2**), then guides — and
**attests**, never automates — the ServiceNow-side OIDC provider registration
(`SN-CONN-OIDC-001`, **S4.3**) and the claim → user mapping (`SN-USERMAP-001`,
**S4.4**). S4.3/S4.4 are attest rows: the spec forbids the agent from automating
ServiceNow-internal OIDC. On resume it always re-runs its role gate and the app
lookup first — both idempotent — before the first incomplete row.

When it returns, go back to **Start** to resume at the next unverified row.

### S5.1 through S5.3 — ServiceNow single sign-on, certificate path (skill-5)

**Only when `authType == "entra_certificate"`.** Read
`src/skills/setup/servicenow/provision-servicenow-certificate.md` and follow it. That
playbook role-gates (App / Cloud Application Administrator), creates the certificate
sign-in Entra apps (`SN-ENTRA-CERT-001`, **S5.1**), uploads the signing certificate
and records the SNI trust (`SN-ENTRA-CERT-001`, **S5.2**), then guides — and
**attests** — the ServiceNow OIDC provider registration and integration system-user
creation (`SN-CONN-OIDC-001`, `SN-SYSUSER-001`, **S5.3**). The certificate private
key stays on disk and never enters chat or `config.json`. S5.3 is attest by design.
On resume it always re-runs its role gate and the app lookup first before the first
incomplete row.

When it returns, go back to **Start** to resume at the next unverified row.

### S6.0 through S6.6 — Install the ServiceNow extension pack and connect (skill-6)

Read `src/skills/setup/servicenow/install-servicenow-extension-pack.md` and follow
it. That playbook role-gates (Environment Maker), has the maker create the shared
ServiceNow and Dataverse connections up front and verifies both are connected
(`SN-CONN-OBJECTS-001`, **S6.0**), guides the
extension-pack install for each in-scope product and verifies it (`SN-PKG-001`,
**S6.1**), guides the maker to bind the ServiceNow and Dataverse connection
references to those connections (`SN-DV-CONN-001`, **S6.2**), turns on the ServiceNow
cloud flows (`SN-FLOW-*`,
**S6.3**), connects the ServiceNow flow invoker connection to the agent's flows
(maker-attested, **S6.4**), shares the connection parameters onto the portal-owned
   reference (**S6.5**), and sets the confirmed Portal Base URL for each pack
(`SN-BASEURL-001`, **S6.6**). Connect (S6.4) and share (S6.5) have no checkpoint and
are attested by the maker, so a resume continues from
whichever is incomplete. The pack install (**S6.1**), turn-on-flows (**S6.3**),
connect-invoker (**S6.4**), share (**S6.5**), and portal (**S6.6**) rows are
recorded **per product** under `productStatus.<product>`; only the shared bind
(**S6.2**) and the up-front connection creation (**S6.0**) mirror under the flat
`setupStatus`.
Every step is performed by the maker by hand and verified by the read-only
flightcheck checkpoint (connect-invoker and share are maker-attested). The chain runs
create connections → install → bind → turn on flows → connect and share → portal, in
that order: connection *creation* needs only the sign-in method (no pack), but the
connection *references* and flows ship inside the pack, so a flow can only hold
activation once its references are bound and the invoker binding
must land on the activated flow. On resume it re-runs the role gate and the pack
lookup first.

When it returns, go back to **Start** to resume at the next unverified row.

### S7.1 through S7.2 — Validate and hand off (skill-7)

Read `src/skills/setup/servicenow/validate-and-handoff.md` and follow it. That
playbook runs a live end-to-end validation against the connected agent and has the
user attest the agent returned their real ServiceNow data with working portal links
(**S7.1**, attest), then offers the topic-creation handoff to `/create` (**S7.2**,
manual). Neither is backed by a programmatic checkpoint.

When it returns, go back to **Start** to resume at the next unverified row.

## All done

Decide which variant to show from `scope`:

- **Both** HRSD and ITSM in `scope` (or the maker declines to add the other) → show:

**Message:**

Your ServiceNow setup checklist is complete. Type `/menu` to see what you can do next.

**End message.**

- **Exactly one** product in `scope` → the other product can still be added to this
  same agent, reusing the sign-in, connections, and Dataverse binding you already set
  up. With `{current}` = the in-scope product name (**ServiceNow HR** for HRSD /
  **ServiceNow IT** for ITSM) and `{other}` = the not-yet-in-scope product name, show:

**Message:**

Your ServiceNow setup for {current} is complete. Type `/menu` to see what you can do
next — or, if you like, I can add {other} to this same agent now. It reuses your
existing sign-in, connections, and Dataverse binding, so you'd only install the
{other} pack, turn on its flows, connect and share them, and set its portal URL.

**End message.**

Use the question tool with options **Add {other} now** and **No, I'm done**. On
**No, I'm done**, stop. On **Add {other} now**, run the **Add a product** transition
below.

---

## Add a product (scope expansion after completion)

Use this transition **only** when the ServiceNow setup is otherwise complete for the
currently in-scope product and the maker chose to add the other product (HR→Both or
IT→Both). It preserves all completed state, initializes **only** the new product, and
resumes at that product's install step. **Do not re-run skill-3 capture (P3.3) to add
a product** — its first-run merge template resets scope and writes `portalBaseUrl:
null` and empty status blocks, which would wipe the completed product's state.

Let `{new}` be the product being added (`hrsd` or `itsm`).

1. **HRSD prerequisite.** If `{new}` is `hrsd`, first run the `sn_hr_core` plugin gate
   from `capture-servicenow-config.md` **P3.2b**. If it isn't satisfied, stop there
   until the maker confirms the plugin — do not expand scope yet.

2. **Expand scope safely — merge ONLY these keys**, preserving every other field in
   `.local/connect/servicenow/config.json` exactly as-is (never overwrite
   `portalBaseUrl`, `makerPermissions`, `authType`, `entra`, `connections`, existing
   `setupStatus`, or the already-completed product's `productStatus.<product>`):
   - Set `scope.{new} = true`.
   - Set `usage = "both"`.
   - Set `packs.{new} = "pending"` (unless a more advanced value already exists).
   - Create `productStatus.{new} = {}` **only if it is absent** — never clear an
     existing product's status.

3. **Insert only the new product's checklist rows.** Add the new product's group-6
   sub-block rows to `.local/setup/servicenow/tasks.md` from the canonical template
   `src/skills/setup/servicenow/tasks.md`, in template order — its install row
   (**S6.1**) and its flows/invoker/share/portal rows (**S6.3–S6.6**). The shared
   connection-create (**S6.0**), shared Dataverse bind (**S6.2**), auth-path group,
   and the other product's rows already exist — **leave them and their status markers
   untouched**. Do not re-render or drop any existing group.

4. **Invalidate only cross-product validation.** The end-to-end validation
   (**S7.1**) only exercised the previously in-scope product, so it must re-run to
   cover the new product. Through [`../shared/checklist-updater.md`](../shared/checklist-updater.md)
   set **S7.1** back to `pending` (`NEW_STATE="pending"`, `CHECKPOINT_RESULT=null`).
   Leave **S7.2** (topic handoff) and every other `done` row — shared steps and the
   existing product's per-product steps — untouched. Reset nothing else.

5. **Resume at the new product's install step.** Go back to **Start**. The first
   unverified row is now the new product's **S6.1** (install): the maker already has
   the connections (S6.0), the bound shared Dataverse reference (S6.2), and the
   sign-in path done, so skill-6 picks up the existing connections and only installs
   the new pack, turns on its flows, connects and shares them, sets its portal URL,
   then S7.1 re-validates across both products.
