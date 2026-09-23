# ESS Custom Engine Agent → Declarative Agent migration

A standalone tool that takes what a customer changed in the **ESS Custom Engine
Agent (CA)** and carries it onto the **ESS Declarative Agent (DA)**.

It reads the customer's Dataverse environment, works out what they customized,
merges those customizations onto the current ESS DA template, and emits an ALM
package plus a report. It **never writes anything** — not to Dataverse, not to the
customer's tenant. The customer's CA keeps running, untouched, and the customer
imports the package themselves when they are ready.

### One agent at a time

ESS is not a single agent. It is a **hub-and-spoke** of three first-class agents,
each shipped as its own CA solution and its own DA template:

| `--vertical` | agent | role |
| --- | --- | --- |
| `core` | Core | the standalone **hub / router** — greets the employee and delegates to a domain agent |
| `hr` | HR | the HR domain agent |
| `it` | IT | the IT domain agent |

You run the tool **once per agent** the customer has customized, choosing the
matching `--vertical` — or **omit `--vertical` entirely** and the tool detects
every ESS agent installed in the environment and migrates each into its own
subfolder of `--out` (`out/core/`, `out/hr/`, `out/it/`). Core is not shared
plumbing folded into HR/IT — it is a separate agent with its own instructions,
topics and package. The domain integrations (ServiceNow, Workday, …) are *not*
separate agents: they layer into HR/IT, and the ones ESS has ported to a DA are
carried inline. A customization that belongs to an integration ESS has **not** yet
ported to a DA is reported as `blocked`, named, with its configuration reproduced,
so nothing is lost silently.

---

## Why this is a merge, not a copy

The two agents are not the same content in different wrappers.

| | Custom Engine Agent | Declarative Agent |
| --- | --- | --- |
| Stored in | Dataverse (`botcomponent` rows in a managed solution) | Cosmos, via the Agent Builder Service |
| Shipped as | a managed solution | an ALM *templated package* (`agent.yml` + `app.config.<realm>.json`) |
| Schema prefix | `msdyn_…` | `gptagent_…` |
| Customer edits live as | unmanaged solution layers | overlays governed by `Overlays.json` |

ESS did not re-wrap the CA to build the DA; much of the content was rewritten.
Measured across the shipping HR template, of the components that have a CA
ancestor only a minority are identical after normalisation, some are 50–90%
similar, and a few were rebuilt outright. Around half the DA's components have no
CA ancestor at all.

That rules out both naive strategies:

- **Copy the customer's topics over the DA** — destroys every ESS improvement.
- **Keep the DA and discard customer edits** — destroys the customer's work.

So the tool does what the platform's own *Upgrade* does for templated agents: a
**three-way merge**. The platform can't run it for a CA customer — they have no
Git Repository Service repo, no base commit and no `templateBaseVersion`, so
there's no merge base — but all three inputs can be reconstructed from sources ESS
owns:

| input | meaning | where it comes from |
| --- | --- | --- |
| **base** | the CA component as ESS shipped it | ESSVivaCopilot `sources/dev/solutions/**/botcomponents/*/data` |
| **ours** | the customer's edit of it | the customer's Dataverse environment |
| **theirs** | the DA component ESS ships today | ESSVivaCopilot `sources/dev/AgentTemplates/**/agent.yml` |

`base` and `theirs` are **vendored** into `reference/`, so a migration run needs
nothing but the customer's environment.

Everything is joined on the **schema-name suffix** — the part after the agent
prefix. `msdyn_…hr.topic.ConversationStart` and `gptagent_…hr.topic.ConversationStart`
both reduce to `topic.ConversationStart`.

### What the merge guarantees

- A change only the customer made is **kept**.
- A change only ESS made is **taken**.
- A change both made, differently, is a **conflict**. By default at a terminal,
  `migrate` **asks you** to resolve each one on the spot — it shows *what you
  changed* (a plain diff against the version ESS originally shipped, so you see
  just your edit) and ESS's current version, then you pick **keep ESS's** (press
  Enter), **keep mine**, or **open an editor to merge by hand** (both versions are
  placed in a text file you edit, save and close). An "apply to the rest of this
  topic" shortcut avoids answering a repetitive rename twenty times. Your choice is
  baked straight into the package. Pass `--non-interactive` (the default in CI /
  when output isn't a terminal) to skip the prompts: conflicts then keep the ESS
  version and are listed in the report for a human. Nothing is ever silently
  picked or thrown away.

Given how much ESS rewrote, expect a real number of conflicts on edited
out-of-box topics. That is the honest answer, and the report — a precise worklist
of what needs a human — is as much the deliverable as the package is.

---

## Install

```powershell
cd tools\ess-ca-to-da
python -m pip install -e ".[dev]"
```

## Use

### 1. Vendor the reference data (maintainers, once per ESS release)

```powershell
python -m essmig vendor --ess-root C:\ESSVivaCopilot
```

Extracts the CA baseline and the DA templates into `reference/`, stamped with the
template version they came from. Re-run whenever ESS ships a new template, and
commit the result — customers never need an ESSVivaCopilot clone.

### 2. See what a customer customized (read-only)

```powershell
python -m essmig inspect --environment-url https://contoso.crm.dynamics.com --vertical hr
```

Prints each customization, gives an **eligibility verdict**, and writes
`out/customizations.json`, `out/customizations.md`, and `out/assessment.json`. The
`.md` is a per-component diff of what you changed from the ESS baseline, with each
component tagged **✅ migratable now**, **⚠️ migratable but needs you**, or
**⛔ not supported yet**. This is the fast way to answer "is this customer ready to
migrate, and if not, what is in the way?" and it touches nothing.

The verdict is one of:

| verdict | meaning |
| --- | --- |
| `ready` | everything carried across; test and publish |
| `needs-work` | migratable, but conflicts to resolve or topics to rebuild first |
| `blocked` | something the customer relies on cannot be migrated at all |

It is deliberately conservative. `ready` means the tool found nothing needing a
human — only the customer's own testing establishes that the agent is correct.

Sign-in opens a browser once. The tenant is taken from the environment's own
`WWW-Authenticate` challenge, so signing in to a customer environment as a guest
works without extra flags. To pin it by hand, set `ESSMIG_MSAL_AUTHORITY`,
`ESSMIG_MSAL_SCOPE` or `ESSMIG_MSAL_CLIENT_ID`.

You need a Dataverse role that can read `solutions`, `solutioncomponents` and
`msdyn_componentlayers` and call `RetrieveDependenciesForUninstallWithMetadata` —
System Customizer or System Administrator.

### 3. Produce the package and the report

```powershell
python -m essmig migrate --environment-url https://contoso.crm.dynamics.com --vertical hr --out out
```

Produces:

```
out/
  Plugin/
    package.json
    Agents/gptagent_copilotforemployeeselfservicehr/
      agent.yml
      app.config.dev.json
  gptagent_copilotforemployeeselfservicehr.zip
  migration-report.md
  migration-report.json
```

**Omit `--vertical`** to migrate every ESS agent the environment actually has —
the tool detects which of Core/HR/IT are installed and writes each into its own
subfolder (`out/core/`, `out/hr/`, `out/it/`), each with the layout above:

```powershell
python -m essmig migrate --environment-url https://contoso.crm.dynamics.com --out out
```

(The same applies to `inspect`.) With `--import`, auto mode delivers each detected
agent under its own default schema name; pass `--vertical` to override a single
agent's `--target-schema-name`.

Add `--preferred-solution <uniquename>` to scope the run to one unmanaged solution
(the ALM path — run once per preferred solution). Add
`--snapshot out/customizations.json` to re-run the merge offline against an earlier
`inspect`, which is also how the end-to-end tests work.

### 4. Deliver it into a target Declarative Agent

By default `migrate` stops at the package and the customer imports it themselves
(step 5). To have the tool import it for you, add `--import` and name the target:

```powershell
python -m essmig migrate --environment-url https://contoso.crm.dynamics.com --vertical hr `
  --import --target-environment-id <power-platform-environment-guid>
```

This builds the package exactly as before, then POSTs it to the target's
`minimalBots/alm/import` endpoint — a **clean replace into that environment's Dev
ring only**; Test and Production are untouched. The delivery outcome (success, or
the failure reason) is written into the report, and a failed import exits non-zero
without having changed the target.

Target addressing:

| flag | meaning | default |
| --- | --- | --- |
| `--target-environment-id` | the Power Platform environment GUID to import into | required with `--import` |
| `--target-tenant-id` | target tenant GUID | the source environment's tenant (source and target share a tenant) |
| `--target-schema-name` | schema name of the target agent | the template's (`gptagent_copilotforemployeeselfservice<vertical>`); override only for a renamed install |
| `--target-api-base` | base URL of the Copilot Studio ALM import API | `https://api.powerplatform.com` (or `ESSMIG_TARGET_API_BASE`) |

The import token audience defaults to the Power Platform API; override it with
`ESSMIG_TARGET_SCOPE` (and the client id with `ESSMIG_MSAL_CLIENT_ID`) if a live
environment requires it. The import contract is from a draft design — see *Open
questions* — so the endpoint and scope are deliberately overridable.

Knowledge sources **do** ride in the package: a SharePoint (or other) source is
carried as a `KnowledgeSourceComponent`, marked customer-owned, and the GPT is
pointed at it (`knowledgeSources: SearchAllKnowledgeSources`) so it is actually
searched after import. Custom metrics, Copilot settings, file attachments,
evaluations (test cases) and skills cannot ride in the package, but they are no
longer dropped silently: every one is **detected and reported** under *Re-create
these in the agent's settings* (with its configuration reproduced) or, where the DA
has no equivalent yet, as *not supported yet*.

The agent's own **display name and description** migrate too. If the customer
renamed or re-described the agent on the CA, the new name is written to the emitted
config (`botName`/`gptDisplayName`) and the new description to `agent.yml`
(`entity.description`), and the change is shown in `customizations.md` under **Agent
name & description**. The tool compares against the shipped ESS baseline so an
untouched agent is left alone; when it cannot read the baseline it reports the
difference for review rather than overwriting the template's own name/description.

Agent **instructions** are migrated with a language model. The CA and DA ship the
*same* instructions worded differently, so a structural merge of the `instructions`
text can only ever conflict. Instead, when the customer has edited their CA
instructions, the tool extracts that delta (customer CA vs the shipped CA baseline)
and re-applies it onto the DA's wording via the GitHub Copilot API — reusing
`gh auth token` exactly as the ESS Maker Kit's evaluation judge does, so no API
keys or endpoints are needed. Pass `--keep-instructions` to skip the model (keep the
DA's shipped instructions and report the edit as a conflict) when `gh` Copilot
access is unavailable or deterministic output is required; if the model can't be
reached at run time, the tool falls back to that behaviour automatically.

### 5. Or the customer imports the package

```
POST .../copilotstudio/tenants/{tid}/environments/{eid}/minimalBots/alm/import
```

with the zip as the payload and `schemaName` set to the existing agent (without it
the API returns 409 when the agent already exists). Import is a **clean replace
into the development environment only** — Test and Production are untouched until
the customer promotes.

Connection ids and secrets are deliberately **not** in the package: they belong to
the destination environment and are bound there. A connection is left *Unbound* by
setting its `connectionId` to `null` — the ESS template ships exactly this shape and
the import binding step relies on the key being present; removing it entirely makes
the package fail to bind. Secret literals are dropped (only `kv://` key-vault
references may travel).

---

## How it decides

Every customization ends up in exactly one bucket, and every bucket appears in the
report.

| outcome | meaning |
| --- | --- |
| `merged` | edited out-of-box component, merged cleanly onto the new template |
| `carried-new` | customer-authored component with no template counterpart; carried wholesale and marked customer-owned |
| `conflicted` | the customer and ESS changed the same thing differently — needs a human |
| `locked` | `Overlays.json` marks it read-only; the edit could not be carried |
| `unchanged` | identical to what ESS shipped; nothing to carry |
| `no-target` | the component type has no DA equivalent the tool recognises |
| `blocked` | belongs to a domain integration ESS has not ported to a DA; there is no agent for it to attach to. Named and reproduced in the report, never carried |
| `failed` | could not be projected or merged; the reason is in the report |

Independently of the above, any carried topic that uses a construct the DA does
not support is **disabled but preserved**: all of its logic is carried across
intact, then marked `Inactive` with a `[DEPRECATED]` title. Nothing is ever
deleted. Each gap is labelled with who has to act on it:

| owner | meaning |
| --- | --- |
| *Handled for you* | carried or reconfigured automatically; just verify it |
| *You need to rebuild this* | real work, with the ADK command that does it |
| *Cannot be preserved* | no equivalent exists and none is planned; the capability is lost |

Only the last kind makes a migration `blocked`. The rest is a worklist.

### What the report will not tell you

The report covers *content*. Three things change for employees that no amount of
merging fixes, and all three are called out in the report so they are not
discovered after cutover:

- **Conversation history does not move.** The DA starts empty.
- **Usage analytics start from zero.** Reporting is per-agent, so the DA does not
  continue the CA's adoption trend line. Export what leaders need first.
- **This tool does not move employees between agents.** It prepares the DA's
  content; cutover and distribution are decided elsewhere.

### Merge policy — `Overlays.json`

The ALM package format carries `Overlays.json`, which classifies each path as
author-locked, template-default-but-customizable, or customer-owned. The tool
consumes it as its merge policy, so the same classification drives this one-time
migration *and* every future platform upgrade.

ESS has not authored one yet. Until it does, every path defaults to a three-way
merge — the most common real classification, and the safest: it can produce a
conflict for a human to resolve, but it never silently discards either side.

---

## Layout

```
src/essmig/
  ess.py          ESS constants: solution names, schema prefixes, component types
  auth.py         MSAL public-client auth (in-memory cache only)
  dataverse.py    read-only Dataverse Web API client
  discovery.py    what did the customer change?
  reference.py    vendored base + theirs
  projection.py   CA botcomponent → agent.yml component shape
  merge.py        three-way merge + Overlays policy
  instructions.py model-backed reconciliation of edited agent instructions
  llm.py          minimal GitHub Copilot API client (gh auth token)
  rules.py        constructs the DA does not support, and who must act on each
  assessment.py   the eligibility verdict: blockers, worklist, employee impact
  packaging.py    emit the ALM package
  deliver.py      import the package into a target DA (the one write path; opt-in)
  report.py       the report
  cli.py          vendor / inspect / migrate
reference/        vendored reference data (committed)
tests/
```

## Develop

```powershell
python -m pytest tests -q
python -m ruff check .
python -m mypy
```

---

## Things worth knowing

These are the details that are easy to get wrong; they are also commented at the
point of use.

- **`msdyn_componentlayers` is a virtual table.** Its filter must pair
  `msdyn_componentid` with `msdyn_solutioncomponentname`, and it will *not* honour
  an `OR` over several component ids — OR-ing silently returns a couple of rows.
  One query per component is mandatory.
- **`msdyn_overwritetime` is not a customization signal.** A net-new unmanaged
  topic reads `1900-01-01`. Classification is by solution layer instead.
- **Solution unique names ≠ folder names.** `EssHRWorkdayHCM` is
  `msdyn_EssHRWorkday`; `EssHRADPHCM` is `msdyn_EssHRADP`. Getting this wrong makes
  the tool read untouched out-of-box content as a customization. Always read
  `<UniqueName>` from the manifest.
- **HR, IT and core are separate baselines.** The same suffix — `gpt.default`, say
  — exists under all three with materially different content. Pooling them would
  diff an HR customer's edit against IT's shipped version.
- **Prefix rewrites must be longest-first.** `msdyn_copilotforemployeeselfservice`
  is a proper prefix of `…servicehr`.
- **Preferred-solution membership can't be read from layers** — every unmanaged
  solution shares the one `Active` layer. It comes from `solutioncomponents`.

## Against the migration spec

Measured against *ESS CA to DA Migration* (`specs/ess/ca-da-migration/spec.md`,
`ideas-exp` PR 5631640):

| | requirement | status |
| --- | --- | --- |
| R1 | Outcomes explicit for every scenario; nothing dropped silently | met |
| R2 | Actionable guidance for gaps, including ADK configuration | met |
| R3 | Prepare and validate without affecting production | partial — read-only against the source, and delivery targets the Dev ring only; it does not create the isolated draft or run evals |
| R4 | Publish directly; ALM optional | partial — `migrate --import` now delivers directly by importing the ALM package into the target; ALM is not yet *optional*, so there is no non-ALM publish path |
| R5 | Employees experience no required action or visible disruption | not addressed — out of reach for a package-generating CLI; the report names the impact instead |
| R6 | Hub migration with incremental domain migration | partial — Core (the hub) and each domain agent are first-class `--vertical` targets you migrate independently; there is no single command that orchestrates the hub plus its spokes in one pass |

R4 and R5 are scope decisions, not defects. Take them up before this is
offered to a customer.

## Open questions

- The ALM design this is built against (*ALM for Declarative Agents — Technical
  Design*, 2026-06-28) is a draft and is still changing. The package contract and
  the import endpoint should be re-confirmed before a customer-facing release.
- Who authors `Overlays.json` — ESS or the platform team?
- The unsupported-construct catalog in `rules.py` was compiled against the DA
  *preview*. Some entries may no longer be restrictions; re-validate it on each
  template refresh, because a stale entry needlessly disables a working topic.
- Nothing here has been run against a live customer CA environment yet. Discovery
  is covered by tests against synthetic Dataverse responses, not by a real run.

## Relationship to `tools/ess-nextgen-migration-toolkit`

That is the earlier attempt. It targeted the DA *preview*, which was still a
Dataverse solution, so it worked by PATCHing `botcomponent` rows in place — a
write path that cannot reach the current Cosmos-backed DA at all. Its discovery
algorithm was sound and is carried forward here; the rest does not apply. It is
left untouched.
