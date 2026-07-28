<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Skill 5b (Optional) — Install Ready-Made Workday Topics

Role: **Environment Maker**. This **optional** skill installs the ready-made
Workday **topics** that ship with the kit (vacation balance, time-off requests,
contact info, government IDs, manager cost-center lookups, and more) into the
user's agent. It is offered by the setup router **after skill 5 (the Workday
extension pack)** and **before skill 6 (your first custom topic)**.

**Topics only — not template configs.** Each Workday topic (the conversation
logic) calls a Workday *scenario template* (`msdyn_employeeselfservicetemplateconfigs`)
to reach Workday. Those scenario templates are **managed** components delivered by
the Workday extension pack in skill 5 — they already exist in the environment and
**cannot** be created per-agent (attempting to create one returns HTTP 400). This
installer therefore writes **only** the topic YAML and relies on the extension pack
for the scenario templates each topic references by `scenarioName`. The sample
folders ship the template XML purely as reference; it is never pushed.

It is **opt-in** — the user can decline and go straight to skill 6. It does **not**
own a numbered master-checklist row; it records its own state under `ootbTopics` in
`.local/connect/workday/config.json` (see
[`config-schema.md`](../shared/config-schema.md)) so a resumed setup never
re-prompts once the user has installed or declined.

Depends on skill 5 (the extension pack must be installed and its Workday +
Dataverse connections bound — the shared flow these topics call is part of that
pack) and, transitively, skills 1–4.

This skill **reuses** existing machinery rather than re-implementing it:
- a deterministic converter script, `scripts/install_ootb_topics.py`, that writes
  the selected topics with correct **PascalCase** names and the required
  substitutions (this replaces free-form hand-copying, which previously produced
  mangled file names that corrupted the topics' identity);
- the **scoped push** (`scripts/push.py --only-from ...`) so **only** the topics
  this skill writes are published — nothing else in the working tree is swept in;
  and
- skill 6's two per-topic checkpoint families — `TOPIC-TRIGGER-*` and
  `TOPIC-INTEGRATION-*` — to verify each freshly written topic before it is pushed.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading. **Never** show internal variable names, IDs, file paths, or
checkpoint identifiers in chat.

---

## Source of the ready-made topics

The scenarios live **inside the kit**, already vendored, at:

- `src/examples/ess-samples/Workday/EmployeeScenarios/` — 11 employee scenarios.
- `src/examples/ess-samples/Workday/ManagerScenarios/` — 5 manager scenarios.

Each scenario is a folder containing a `topic.yaml` (the Copilot Studio topic) and
one or more `msdyn_*.xml` files. **Only the `topic.yaml` is installed** — the
`msdyn_*.xml` template configs are reference copies of managed components the
extension pack already registered, so this skill never writes or pushes them.
**Only** use this vendored copy — never the repo-root `samples/` tree, which is
outside the kit workspace and not reachable from here.

The `ExtendedScenarios/` folder (loose topic-only YAMLs with no template config) is
**out of scope** for this installer.

---

## Idempotency & resume

- On entry, read `ootbTopics.state` in `.local/connect/workday/config.json`. If it
  is already `"installed"`, tell the user their ready-made topics are already in
  place and return to the router. (The router only reads this file when the state
  is unset / `"pending"` / `"in-progress"`, so normally you arrive here to do work.)
- **Skip any scenario that is already present** in the agent — if a topic of the
  same name already exists under `{agent.folder}/topics/` or in the pushed baseline,
  do not overwrite it. Report it as "already installed" and move on.
- Persist `ootbTopics` after each phase so an interrupted run resumes cleanly.

---

## O.0 — Role gate (Environment Maker)

Apply the shared [`permission-gate.md`](../shared/permission-gate.md) before any
authoring work, with:

- `REQUIRED_ROLE` = `"Environment Maker"`
- `GATE_MODE` = `"programmatic"`
- `STEP_ID` = `"OOTB.0"` (evidence label only — this installer owns no S-row)
- `ROLE_QUERY` = a Dataverse security-role membership check for the signed-in
  user. Read `dataverseEndpoint` from `.local/config.json`; call it `{ENV_URL}`:

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

  The role is held if the returned names include **`Environment Maker`**,
  **`System Customizer`**, or **`System Administrator`**. Treat an
  `Insufficient privileges` / forbidden response as "role not held"; on an
  unrelated error follow the gate's retry-then-attest fallback.

If `GATE_RESULT` is `"stop"`, **halt** — leave `ootbTopics.state` unchanged
(`"pending"`) so the offer can be made again later. Otherwise carry
`GATE_EVIDENCE` forward and continue.

---

## O.1 — Present the catalog & let the user choose

Read the two vendored scenario folders. For each scenario, derive a short,
plain-language label from its `README.md` (or its topic's `modelDescription`) —
never show folder names, file names, or scenario IDs.

**Message:**

Here are the ready-made Workday topics I can add to your agent. **For employees:**
check a vacation balance, request time off, view job details, look up contact
information, education, government IDs, dependents, emergency contacts, user
profile, update a home address, and give peer feedback. **For managers:** look up a
direct report's company code, cost center, job taxonomy, service anniversary, and
time in position.

Which would you like me to add?

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Ready-made Workday topics",
    "question": "Which ready-made Workday topics should I add to your agent?",
    "options": [
      { "label": "All of them (employee + manager)", "recommended": true },
      { "label": "Employee topics only" },
      { "label": "Manager topics only" },
      { "label": "Let me pick specific ones" }
    ],
    "allowFreeformInput": true
  }
]
```

- **"All of them"** → select all 16 scenarios.
- **"Employee topics only"** → select the 11 employee scenarios.
- **"Manager topics only"** → select the 5 manager scenarios.
- **"Let me pick specific ones"** (or a freeform answer) → confirm the specific
  scenarios the user named, matching their words to the plain-language labels.

Record the selected scenario list. Set `ootbTopics.state = "in-progress"` and
`ootbTopics.selected = [<scenario names>]` in `.local/connect/workday/config.json`
(round-trip merge — never drop other keys).

If the user declines all (empty selection), set `ootbTopics.state = "declined"` and
return to the router.

---

## O.2 — Back up, then write the selected topics into the agent

First save a restore point:

```
python scripts/checkpoint.py "pre-install-ootb-workday-topics"
```

Then run the converter script to write the selected topics. **Do not hand-copy or
name files yourself** — the script derives correct PascalCase file names and applies
both required substitutions (the agent's schema prefix and the Workday `<TENANT_NAME>`),
reading `agent.folder` / `agent.schemaName` from `.local/config.json` and `tenant`
from `.local/connect/workday/config.json`. It skips any topic already present in the
agent (working files or baseline) and writes a push manifest listing exactly what it
wrote.

Map the user's O.1 choice to one flag:

- **All of them** → `--all`
- **Employee topics only** → `--employee`
- **Manager topics only** → `--manager`
- **Specific ones** → `--scenarios "Name1,Name2,..."` (use the scenario folder or
  topic base names; run `--list` first to see the exact names)

```
python scripts/install_ootb_topics.py --list
python scripts/install_ootb_topics.py <selection-flag> --json
```

The script prints the topics it wrote (and any it skipped as already installed) and
the manifest path (`.local/setup/ootb-push-manifest.txt`). It installs **topics
only** — it never writes template configs, because those managed scenario templates
already came with the extension pack. Do not push yet — verification comes first.

---

## O.3 — Wire tenant reference IDs (skill-4 loop-back if scopes are missing)

Most of these scenarios resolve the employee at runtime (via the user-context
lookup skill 5 wired) and need no author-time values. A few need a
tenant-specific reference ID (for example a **Time Off Type ID** from the Workday
*Time Off Types* report). Where a scenario left a reference-ID placeholder, walk
the user through obtaining the real value from their Workday tenant and substitute
it into the topic before pushing. (The `<TENANT_NAME>` substitution is already done
by the O.2 script; this step is only for other tenant-specific reference IDs.)

**If a selected scenario needs a Workday API functional area the registered API
client doesn't grant yet** (a REST/SOAP scope error), loop back to skill 4:

**Message:**

One of these topics needs a Workday permission your API client doesn't grant yet.
We'll jump back to the Workday tenant setup to add the required functional area,
then come back here to finish adding your topics.

**End message.**

Read [`configure-workday-tenant.md`](./configure-workday-tenant.md) and re-run its
**P4.3** (Register the API client) to add the missing functional area(s) — keeping
**Include Workday Owned Scope = Yes** — then return here and continue.

---

## O.4 — Scan & verify the written topics *(reuses skill 6's checkpoints)*

Check the whole agent folder for errors with the diagnostics tool. Fix any error
in a **newly written** file before continuing; mention (but don't block on)
pre-existing errors in other files.

Then verify the freshly written topics — because nothing has been pushed yet, they
count as new against the current baseline, so skill 6's two families cover them:

**Message:**

Now I'll check each topic I added is set up correctly and fully wired to Workday.

**End message.**

```
python scripts/flightcheck/cli.py --checkpoint TOPIC-TRIGGER-*
python scripts/flightcheck/cli.py --checkpoint TOPIC-INTEGRATION-*
```

**After each run, show its result in chat first.** Render the result per
[`shared/checklist-updater.md`](../shared/checklist-updater.md) §U.0–U.0a — the
compact result table and, for any `MANUAL` / `Warning` / `NotConfigured` row, its
full verification steps — **before** you show any later **Message** or ask any
question.

- `TOPIC-TRIGGER-*` — each added topic is a well-formed triggerable definition.
- `TOPIC-INTEGRATION-*` — each added topic's integration wiring resolves with no
  leftover placeholder tokens.

If **any** row `FAILED`, fix it (return to O.2 for a definition problem, or O.3 for
a leftover reference-ID placeholder) and re-run the affected family until it
passes. Do not push topics that still fail.

---

## O.5 — Dry run, then push (scoped)

Preview the change set — **scoped to just the topics this skill wrote** via the
manifest from O.2, so unrelated working-tree changes are never touched:

```
python scripts/push.py --only-from .local/setup/ootb-push-manifest.txt --dry-run
```

Show the user the diff summary (which topics will be added). Then:

**Message:**

I'm ready to add these topics to your live agent. Want me to go ahead?

**End message.**

On confirmation:

```
python scripts/push.py --only-from .local/setup/ootb-push-manifest.txt --yes
```

This creates **only** the topic records in the environment and refreshes just their
baseline entries, so these ready-made topics become part of your agent's baseline
(and won't later be mistaken for a custom topic you author in skill 6). The managed
scenario templates they call are already present from the extension pack, so nothing
else is pushed.

**If the push fails**, show the error and offer to retry, or to revert with
`python scripts/checkpoint.py --revert`.

---

## O.6 — Record state & return

Set, in `.local/connect/workday/config.json` (round-trip merge):

- `ootbTopics.state = "installed"`
- `ootbTopics.installed = [<scenario names actually pushed>]`

Then return control to the setup router (`SKILL.md`) to continue at skill 6.

**Message:**

Done — your ready-made Workday topics are live in your agent. You can try them in
Copilot Studio, or keep going and build your own custom topic next.

**End message.**
