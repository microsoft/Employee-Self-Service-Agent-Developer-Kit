<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Skill 6 — Create a New Workday Topic

Role: **Environment Maker** (with a **Workday SME** for tenant reference-ID
values). This skill creates a new custom Workday scenario beyond the OOTB set
(for example *Request Time Off*): it authors the topic and its template
configuration with the **Template Config + Shared Flow** pattern, wires the
tenant-specific reference IDs, verifies the result with two per-topic checkpoint
families, runs an advisory review over the finished topic, and auto-generates a
matching evaluation set. It owns master-checklist rows **S6.1**, **S6.2**, and
**S6.3**.

Depends on skill 5 (the Workday extension pack must be installed and wired — its
connections bound, the REST endpoint verified, the cloud flows on, and the
user-context redirect in place) and, transitively, skills 1–4.

This skill is a Workday-specialised wrapper: it **delegates the topic/template
authoring** to [`src/skills/topics/create/SKILL.md`](../../topics/create/SKILL.md)
(the general create-topic skill, which already implements the Template Config +
Shared Flow pattern, the checkpoint → write → scan → dry-run → push → verify
pipeline, and the Dataverse template-config creation) and **owns** the role gate,
the two new checkpoints, the checklist rows, the skill-4 loop-back when the new
scenario needs API scopes the tenant doesn't grant yet, and the eval generation.

It **mints** two **family** checkpoints in `checks/topics.py`, one row **per new
topic** — `TOPIC-TRIGGER-*` (S6.1) and `TOPIC-INTEGRATION-*` (S6.2). Both are
pure local-file checks (they read the extracted working copy, no API call).

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading. **Never** show internal variable names or IDs in chat.

**Checkpoints this skill drives (run each in isolation):**

| Step | Checkpoint | Gate |
|------|-----------|------|
| S6.1 | `TOPIC-TRIGGER-*` — each new topic is a well-formed AdaptiveDialog with a trigger (and trigger phrases when intent-routed) | prog |
| S6.2 | `TOPIC-INTEGRATION-*` — each new topic's integration wiring resolves (no unresolved tenant reference-ID placeholders) | prog (+ SME for ID values) |

> **S6.3 is advisory — not a checkpoint.** After S6.1 and S6.2 pass, this skill
> runs an advisory **topic review** over the finished topic (P6.5) and shows the
> findings to the user. It has no flightcheck checkpoint and **never blocks** —
> its row completes once the report has been shown. See
> [`topics/review/SKILL.md`](../../topics/review/SKILL.md).

Run either family with:

```
python scripts/flightcheck/cli.py --checkpoint TOPIC-TRIGGER-*
python scripts/flightcheck/cli.py --checkpoint TOPIC-INTEGRATION-*
```

**After every checkpoint run, show its result in chat first.** As soon as a
`--checkpoint` run returns, render the result to the user per
[`shared/checklist-updater.md`](../shared/checklist-updater.md) §U.0–U.0a — the
compact result table and, for any `MANUAL` (or `Warning` / `NotConfigured`) row,
its full verification steps — **before** you show any later **Message** or ask any
attestation question. Single-checkpoint runs never open the HTML report, so this
in-chat render is the only place the user sees the manual steps; never ask a user
to attest to steps they have not been shown.

Each family expands to **one row per new/custom topic** found under the extracted
agent — a topic is "new" when it differs from the OOTB `.baseline/` snapshot the
extension-pack push mirrored. When no custom topic exists yet, both checkpoints
report a single `NotConfigured` "nothing to verify yet" row.

`TOPIC-INTEGRATION-*` is a **prog** row whose checkpoint proves the placeholder
tokens were resolved, but the *correctness of the tenant reference-ID values*
(e.g. the Time Off Type ID) cannot be verified locally — so S6.2 also carries a
**Workday SME attestation** (the `prog (+ SME for IDs)` gate). A checkpoint pass
is necessary but not sufficient for S6.2; the SME must confirm the wired values.

**On every resume, always re-run P6.0 (role gate) first** — it is read-only —
then continue at the first incomplete row. If the user is authoring another topic
in the same session, re-run the whole skill for that topic (the checkpoints
expand to cover every custom topic).

---

## P6.0 — Role gate (Environment Maker)

Apply the shared [`permission-gate.md`](../shared/permission-gate.md) before any
topic-authoring work, with:

- `REQUIRED_ROLE` = `"Environment Maker"`
- `GATE_MODE` = `"programmatic"`
- `STEP_ID` = `"S6.1"`
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
`GATE_EVIDENCE` forward (it is recorded when the S6 rows are updated).

---

## P6.1 — Author the topic & template config *(delegated to the create-topic skill)*

The topic YAML and its Dataverse template-config record are authored by the
general create-topic skill, which already implements the Workday **Template Config
+ Shared Flow** pattern and the full mutation pipeline. Do not re-implement it
here.

Set **S6.1** and **S6.2** `in-progress` (via
[`checklist-updater.md`](../shared/checklist-updater.md), `GATE="prog"`,
`CHECKPOINT_RESULT=null`), then read and follow
[`src/skills/topics/create/SKILL.md`](../../topics/create/SKILL.md) end to end for
the new Workday scenario. When you interview the user in that skill's Step 1,
frame the scope as a **Workday** scenario so it takes the template-config path:

**Message:**

Let's create a new Workday topic. Tell me what it should do — for example
"request time off", "show my remaining vacation balance", or "look up my job
profile". Describe the conversation you want employees to be able to have.

**End message.**

The create-topic skill will select the Workday sample pattern, write
`workspace/agents/{slug}/topics/{TopicName}.mcs.yml`, create the matching
template-config record in Dataverse, scan, dry-run, and push. When it returns,
the new topic exists locally and in the environment. Continue to P6.2 to wire and
verify the tenant reference IDs.

**Do NOT run any topic review during this P6.1 authoring delegation** — the
create-topic skill's own review sub-step (its step 6.5) must not fire here. The
tenant reference IDs are not wired yet (P6.2 does that), so a review now would
false-flag the unresolved placeholders. There is **no** review at S6.1/P6.1; the
one and only topic review runs later at **P6.5 (row S6.3)**, once the integration
wiring is verified.

---

## P6.2 — Wire the tenant reference IDs (skill-4 loop-back if scopes are missing) *(prepares S6.2)*

A Workday scenario resolves tenant-specific values at author time — the Workday
tenant name and the reference IDs the scenario needs (e.g. the **Time Off Type
ID** from the Workday *Time Off Types* report, a **Job Profile ID**, etc.). The
create-topic skill leaves these as placeholder tokens (`{{PLACEHOLDER}}` or
`<UPPERCASE>` slots) when it can't resolve them. They must be replaced with real
tenant values before the topic works.

Walk the user through obtaining and wiring each reference ID from their Workday
tenant, then update the topic YAML (and template-config record) with the real
values and re-push with the create-topic skill's pipeline
(`python scripts/push.py --yes`).

**If the new scenario needs a Workday API functional area the registered API
client doesn't grant yet** (the REST/SOAP call returns an authorization or
scope error), this is a tenant-configuration gap — loop back to skill 4:

**Message:**

This scenario needs a Workday permission your API client doesn't grant yet. We'll
jump back to the Workday tenant setup to add the required functional area to the
API client, then come back here to finish wiring this topic.

**End message.**

Read [`configure-workday-tenant.md`](./configure-workday-tenant.md) and re-run its
**P4.3** (Register the API client) to add the missing functional area(s) — keeping
**Include Workday Owned Scope = Yes** — then return here and continue. Do not try
to wire around a missing scope locally.

When every reference ID is wired and the topic pushes cleanly, continue to P6.3.

---

## P6.3 — Verify the topic trigger & definition (TOPIC-TRIGGER-*) *(completes S6.1)*

**Message:**

Now I'll check each new topic is properly set up with a trigger so Copilot knows
when to use it.

**End message.**

```
python scripts/flightcheck/cli.py --checkpoint TOPIC-TRIGGER-*
```

`TOPIC-TRIGGER-*` expands to one row per new/custom topic and confirms each is a
well-formed `AdaptiveDialog` with a trigger — plus trigger phrases
(`modelDescription` / `triggerQueries`) when the topic is intent-routed.

- **All `PASSED`** → update **S6.1** via
  [`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S6.1"`,
  `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`. Persist the P6.0 `GATE_EVIDENCE`.
  Continue to P6.4.
- **Any `FAILED`** (the result names the topic and what's missing — no
  `kind: AdaptiveDialog`, no trigger, or an intent-routed topic without trigger
  phrases):

  **Message:**

  Your new topic isn't fully triggerable yet. I'll fix its definition — it needs
  to be a proper topic with a trigger and, if it's AI-routed, some example
  phrases so Copilot knows when to use it. Give me a moment.

  **End message.**

  Go back to [`topics/create`](../../topics/create/SKILL.md) to add the missing
  trigger / trigger phrases, re-push, and re-run `--checkpoint TOPIC-TRIGGER-*`.
  Loop until all pass; leave S6.1 `in-progress` until then.
- **`NotConfigured`** ("no custom topics found" / "no agent workspace") → the
  topic wasn't authored or the agent isn't extracted locally. Return to P6.1
  (author the topic) or extract the agent first, then re-check.

---

## P6.4 — Verify the integration wiring + SME attestation (TOPIC-INTEGRATION-*) *(completes S6.2)*

**Message:**

Now I'll confirm each new topic's integration wiring is fully resolved, with no
leftover placeholders.

**End message.**

```
python scripts/flightcheck/cli.py --checkpoint TOPIC-INTEGRATION-*
```

`TOPIC-INTEGRATION-*` expands to one row per new/custom topic and confirms each
topic's integration wiring resolves — no unresolved `{{PLACEHOLDER}}` scaffolding
or `<UPPERCASE>` tenant reference-ID tokens remain. (A topic with no external
wiring is a benign pass — there is nothing to resolve.)

- **Any `FAILED`** (the result lists the leftover placeholder tokens):

  **Message:**

  This topic still has some tenant values that haven't been filled in — it won't
  work against your Workday instance until they're wired. Let's finish those now.

  **End message.**

  Return to P6.2 to wire the remaining reference IDs, re-push, and re-run
  `--checkpoint TOPIC-INTEGRATION-*`. Loop until no placeholders remain; leave
  S6.2 `in-progress` until then.
- **All `PASSED`** → the placeholders are resolved, **but** S6.2 is a
  `prog (+ SME for IDs)` row: the checkpoint proves the tokens were replaced, not
  that the tenant reference-ID *values* are correct. Get the Workday SME's
  attestation before completing the row.

  **Message:**

  The integration wiring for your topic is complete — every tenant value has been
  filled in. One last confirmation: please have someone with Workday expertise
  verify the reference IDs (for example the Time Off Type ID) match your Workday
  tenant's configuration. Are the wired reference-ID values correct?

  **End message.**

  Use the `vscode_askQuestions` tool:

  ```json
  [
    {
      "header": "Workday reference IDs",
      "question": "Has a Workday SME confirmed the wired tenant reference-ID values are correct?",
      "options": [
        { "label": "Yes, confirmed", "recommended": true },
        { "label": "Not yet / not sure" }
      ],
      "allowFreeformInput": false
    }
  ]
  ```

  - **"Yes, confirmed"** → update **S6.2** via
    [`checklist-updater.md`](../shared/checklist-updater.md) with
    `STEP_ID="S6.2"`, `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`, and record the
    SME confirmation as the captured evidence. Continue to P6.5.
  - **"Not yet / not sure"** → leave S6.2 `in-progress`. The checkpoint passes but
    the values are unconfirmed; have the Workday SME verify (and, if a value is
    wrong, correct it in P6.2 and re-push) before re-attesting here.

---

## P6.5 — Review the finished topic *(completes S6.3)*

Now that the topic is authored, wired, and its trigger and integration are
verified, run an **advisory** review over it to surface any remaining authoring
issues before the user relies on it. This never blocks — it shows findings and
lets the user decide.

**Message:**

Your topic is set up and verified. Let me do a quick review of it and flag
anything worth tidying up before you rely on it.

**End message.**

Set **S6.3** `in-progress` via
[`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S6.3"`,
`GATE="advisory"`, `NEW_STATE="in-progress"`.

Invoke the review by calling `runSubagent` (the VS Code Copilot Chat tool),
pointing the subagent to read
[`src/skills/topics/review/SKILL.md`](../../topics/review/SKILL.md) as its first
action — do not run its detectors yourself. Tell it this is a **single-topic**
review of the topic just created (pass the agent slug from `.local/config.json`
and the topic stem — the filename without `.mcs.yml`), and ask it to present the
**maker-facing report** (its Step 9). Wait for the subagent to return, then
**paste its full report into chat verbatim** — the verdict line, the findings
table, and the close. Do NOT summarize or re-word it.

- **If the report lists findings**, pause and ask the user how to proceed:
  - **Fix now** → run [`topics/update`](../../topics/update/SKILL.md) (`/update`)
    on the topic to apply the fixes, then re-run this review before completing
    S6.3.
  - **Continue** → the findings are advisory; leave them for later.
- **If the report is clean**, say so briefly.

Once the report has been shown and the user has chosen how to proceed, complete
**S6.3** via [`checklist-updater.md`](../shared/checklist-updater.md) with
`STEP_ID="S6.3"`, `GATE="advisory"`, `NEW_STATE="done"` — the review is advisory,
so showing the report completes the row regardless of findings. Then continue to
P6.6.

**If the review can't run** (the subagent or its detector scripts fail), tell the
user the review was skipped, complete **S6.3** as `done` (advisory rows never
block the setup), and continue to P6.6.

---

## P6.6 — Auto-generate a matching evaluation set *(delegated to the evaluate skill)*

Every new topic should ship with coverage, so generate a matching evaluation set
automatically — the user should not have to run a separate step.

**Message:**

Now I'll generate an evaluation test set for your new topic so you can measure how
reliably it triggers and answers. I'll write it, dry-run it, and push it to your
environment.

**End message.**

Read [`src/skills/evaluations/create/SKILL.md`](../../evaluations/create/SKILL.md)
and follow it, scoped to the topic just created. It writes the test set to
`workspace/agents/{slug}/evaluations/` as
`{set-name}-{short-slug}.mcs.yml` and runs the same
checkpoint → write → scan → dry-run → push → verify pipeline. Generate a
**Topic Triggering** set from the new topic's trigger phrases / model description;
if the topic calls Workday, add an **Integration Data** set — but assert against a
sanitized golden test user, not generic placeholders.

---

## Done

When S6.1, S6.2, and S6.3 are all `done`, return control to the setup router
(`SKILL.md`).

**Message:**

Your new Workday topic is live — its trigger and definition are verified, the
tenant reference IDs are wired and confirmed, and a matching evaluation set has
been generated and pushed. You can create another topic any time, or type `/menu`
to see what else you can do.

**End message.**
