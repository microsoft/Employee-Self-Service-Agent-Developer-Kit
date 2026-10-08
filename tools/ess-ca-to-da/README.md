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
  placed in a text file you edit, save and close). Each contested spot is answered
  on its own. Your choice is
  baked straight into the package. Pass `--non-interactive` (the default in CI /
  when output isn't a terminal) to skip the prompts: conflicts then keep the ESS
  version and are listed in the report for a human. Nothing is ever silently
  picked or thrown away.

Given how much ESS rewrote, expect a real number of conflicts on edited
out-of-box topics. That is the honest answer, and the report — a precise worklist
of what needs a human — is as much the deliverable as the package is.

---

## Install

### Clean machine, one command

On a machine with **nothing installed** — no Git, no Python, no clone of this
repo — a single command fetches the tool and leaves you ready to run it. It
ensures Git, shallow-clones the repository (which brings the tool and its
vendored reference data), and drops you in the tool folder with the exact
command to run next. It does **not** start a migration for you.

```powershell
# Windows (PowerShell) — leaves you in the tool folder, ready to run
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/tools/ess-ca-to-da/bootstrap.ps1)
```

```bash
# macOS / Linux — prints the `cd` command to copy (a piped script can't move your shell)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/tools/ess-ca-to-da/bootstrap.sh)"
```

The repository is cloned to `~/Employee-Self-Service-Agent-Developer-Kit` by
default. Override with `ESS_CA_TO_DA_ROOT`, pick a branch with `ESS_ADK_BRANCH`,
or a fork with `ESS_ADK_SOURCE_URL`. From there, `run.ps1` / `run.sh` (below)
takes care of Python and the tool itself.

### Already have the repo

The quickest path needs **nothing installed first** — not even Python. A launcher
resolves (and, if missing, installs) Python 3.11+, creates a private `.venv`, and
installs the tool into it on first run, then forwards your arguments straight to
`essmig`:

```powershell
# Windows
cd tools\ess-ca-to-da
.\run.ps1 migrate --environment-url https://contoso.crm.dynamics.com --out out
```

```bash
# macOS / Linux
cd tools/ess-ca-to-da
./run.sh migrate --environment-url https://contoso.crm.dynamics.com --out out
```

Every command below that starts with `python -m essmig ...` can be run as
`.\run.ps1 ...` / `./run.sh ...` instead. On Windows the launcher auto-installs
Python via `winget`; on macOS via Homebrew. Force the tool to reinstall into the
`.venv` after a code change with `.\run.ps1 -Reinstall` (or `ESSMIG_REINSTALL=1
./run.sh`).

> **Windows "running scripts is disabled on this system"?** A clean Windows
> client blocks `.ps1` files by default. The one-command bootstrap above relaxes
> this for you. If you cloned manually, either allow local scripts once —
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` — or run the launcher
> without changing anything:
> `powershell -ExecutionPolicy Bypass -File .\run.ps1 inspect --environment-url ...`.


If you would rather manage Python yourself:

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
`out/customizations.json`, `out/customizations.md`, `out/customizationsMade.md`, and
`out/assessment.json`. `customizations.md` is a per-component diff of what you changed
from the ESS baseline, with each component tagged **✅ migratable now**,
**⚠️ migratable but needs you**, or **⛔ not supported yet**.
`customizationsMade.md` is the mirror-image audit — see [§3a](#3a-audit-what-the-migration-changed).
This is the fast way to answer "is this customer ready to migrate, and if not, what is
in the way?" and it touches nothing.

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
  flows.zip
  migration-report.md
  migration-report.json
  customizationsMade.md
```

`flows.zip` is written only when the migrated topics invoke **customer-authored
cloud flows** (a `--from-package` capability — see the note in
[§3b](#3b-cloud-flows-the-customer-authored)). It is a second, separate artifact:
the agent package can *reference* a flow but not *contain* one, so the flows travel
as their own unmanaged solution that must be imported **before** the agent package.

#### 3a. Audit what the migration changed

`customizationsMade.md` (written by both `inspect` and `migrate`) is a per-component
diff of the Declarative Agent **as ESS shipped it** against the **package this tool
produced** — the same layout as `customizations.md`, but answering the reviewer's
question instead of the Maker's: *what did the tool actually write onto the DA?*

- **Changed** — a template component the migration edited, shown as a unified diff
  (shipped → produced): a merged topic, or the GPT gaining a `knowledgeSources`
  pointer, for example.
- **Added** — a component the produced package has that the template did not: the
  customer's own net-new topics and any carried knowledge source, shown in full.
- **Removed** — a template component the package dropped (migration does not normally
  remove, so this is for completeness).

A leading **Agent settings** section calls out a changed display name or description.
Components the migration left byte-for-byte identical are omitted. This is the file to
hand a reviewer who must sign off on exactly what changed before the package is
published.

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

### 3a. No Dataverse access? Migrate from an exported solution package

Some customers cannot run the tool's Dataverse queries — no CLI access, a locked-down
tenant, or a separation of duties where the person exporting is not the person
migrating. They can still hand over an **exported customization solution** instead of
a live connection. In make.powerapps.com, open **Solutions**, select the
customization solution, choose **Export solution** (unmanaged is fine), and download
the `.zip`.

Point `inspect` or `migrate` at that `.zip` (or an already-unpacked folder) with
`--from-package` instead of `--environment-url`. Everything else is identical — same
detection, same classification, same package, same report:

```powershell
# Read-only: what did they customize?
python -m essmig inspect --from-package .\EmployeeSelfServiceCustomization.zip

# Produce the package + report from the export
python -m essmig migrate --from-package .\EmployeeSelfServiceCustomization.zip --out out
```

`--from-package` and `--environment-url` are mutually exclusive (the export is the
source). Omit `--vertical` and the tool detects which of Core/HR/IT the package
carries, exactly as it does against a live environment. `--preferred-solution` is
ignored — the export already *is* the set of components the customer chose to ship.

Two limitations of the package path, both reported rather than silent:

- The agent's shipped **Overview description** is not present in the vendored
  baseline, so an *edited* description is surfaced for review rather than migrated
  automatically. A renamed agent (display name) still migrates normally.
- **Environment variables** the solution also contains are not carried into the
  package yet (cloud flows *are* carried — see below).

#### 3b. Cloud flows the customer authored

A migrated topic can *call* a cloud flow (a `- kind: InvokeFlowAction` with a
`flowId`), and the Declarative Agent declares each flow it uses in a top-level
`flows:` block — the flow's *interface* (id, input and output parameters). But the
DA package has nowhere to hold the flow's *definition*: a cloud flow is a Power
Platform environment component, installed by a **solution import**, not a part the
agent package can carry.

So when the migrated topics invoke a customer-authored flow (read from a
`--from-package` export — the live-Dataverse path cannot read a flow definition),
the tool:

- synthesises the `agent.yml` `flows:` interface entry for each referenced flow
  from the flow's own trigger/response schemas, and registers the flow id in
  `app.config.dev.json`'s `flows` map — the two places the ESS template declares
  its own runtime flows, so the agent knows the flow's shape and can resolve it at
  publish time; and
- re-emits the customer's flows as `out/flows.zip`, a small unmanaged solution that
  *creates* the flows in the target — near-verbatim from their export, so the flow
  definitions and their connection references carry across exactly.

**Import `flows.zip` first, then the agent package.** The flow ids are preserved,
so once the flows exist the agent's `InvokeFlowAction` references resolve. Import in
the other order and the flow registrar rejects the agent package with *"a referenced
flow could not be registered because it was deleted or you do not have access."* The
report's **Cloud flows** section lists what was carried, the import order, and any
connection references the operator must rebind. A flow a topic references but the
tool cannot carry (e.g. on the live-Dataverse path) is reported as **dangling** — a
hard import blocker — never silently dropped.

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

> **This `--import` path reaches the Dev ring only.** The `minimalBots/alm/import`
> endpoint is a development-ring bulk ALM promote and is **not available on the
> production rings**, so it cannot deliver to a customer's production agent. For a
> prod-capable write, use `--deliver-minimalbot` (below).

### 4b. Deliver the customizations into a *live* agent (prod-capable)

To apply the migrated customizations straight into a running Declarative Agent —
on any ring, **including production** — use `--deliver-minimalbot`. It delivers the
**delta** (only what the migration could carry) through the MinimalBot components
API, the same authoring data plane Copilot Studio uses, as a **hybrid**:

- **Your edits to shipped topics** (modelDescriptions, GPT instructions, input
  descriptions, …) are **overlaid live** onto the agent's existing components.
- **Brand-new topics you authored** can't be compiled to the live runtime form, so
  they're **routed to the ALM package import** (`--import` or a manual import) and
  listed in the report instead.
- A handful of **formula-level edits** (changes to Power Fx expressions/conditions)
  can't be auto-applied; they're reported with the before/after values so you can
  apply them by hand.

```powershell
python -m essmig migrate --environment-url https://contoso.crm.dynamics.com --vertical hr `
  --deliver-minimalbot `
  --target-agent-url "https://copilotstudio.microsoft.com/environments/<env>/copilots/<botId>/details"
```

You identify the target agent by its **Copilot Studio URL** — open the DA in
Copilot Studio and copy the browser address; the tool reads both the environment
id and the botId from it. The shipping ESS DA GA is a Cosmos-backed agent, which
is **not listable** by any supported API, so the botId cannot be auto-discovered
— it must come from the URL (or be supplied explicitly). Instead of the URL you
may pass `--target-environment-id <guid>` together with `--target-bot-id <guid>`.

It is **dry-run by default**: it reads the target, builds the overlays and prints
the exact change set (topics edited live, topics routed to the package, and any
edits it couldn't overlay), and **writes nothing**. Review that, then add
`--deliver-apply` to actually write:

```powershell
python -m essmig migrate … --deliver-minimalbot `
  --target-agent-url "<copilot-studio-url>" --deliver-apply
```

Only your edits to **shipped topics** (outcome **MERGED**) are overlaid live;
**CARRIED_NEW** topics you authored are routed to the package import. Everything
left on the template, un-carryable, or conflicted is untouched.

| flag | meaning | default |
| --- | --- | --- |
| `--deliver-minimalbot` | deliver the delta into the live agent via the components API | off |
| `--target-agent-url` | the DA's Copilot Studio URL (supplies env id + botId) | required (or use the two flags below) |
| `--target-environment-id` | the agent's Power Platform environment GUID | required if no `--target-agent-url` |
| `--target-bot-id` | GUID (botId) of the live target agent | required if no `--target-agent-url` |
| `--target-ring` | ring the agent lives on (`test`/`preprod`/`prod`) | `prod` |
| `--target-tenant-id` | target tenant GUID | source tenant (`--environment-url`), else interactive sign-in |
| `--deliver-apply` | actually write (otherwise dry-run preview only) | off (dry-run) |

> **Verified live.** Sending the raw `agent.yml` component forms is rejected by the
> service (a dialog's expressions must be expanded runtime objects, not strings);
> the overlay sidesteps this by starting from the live component and substituting
> only your plain-text edits. Against a real Cosmos-backed ESS DA GA it applies the
> ServiceNow modelDescription edits + GPT instructions and leaves the agent's dialog
> logic intact. **Do a dry-run first to review the plan, then `--deliver-apply`.**
> See `DEV_DESIGN.md` §9.2.


Knowledge sources **do** ride in the package: a SharePoint (or other) source is
carried as a `KnowledgeSourceComponent`, marked customer-owned, and the GPT is
pointed at it (`knowledgeSources: SearchAllKnowledgeSources`) so it is actually
searched after import. A **ServiceNow knowledge source** reaches its content
through a Graph-connector connection that the source names *indirectly*, by an
environment variable: the component's `connectionId.schemaName` points at an
`envVar.*`, and `app.config.dev.json`'s `values` block binds it under an
`envvar:<schema>` key whose value is the Graph connector's connection id. Two
things the platform would normally wire are reproduced for it, or the source
silently disappears after import:

- the **connection binding** — the `envvar:` entry is written into the config,
  carrying the value from the customer's exported environment-variable definition.
  That value names a Graph connector in the *source* tenant, so it is a starting
  point the operator must **rebind** in the target; the report's **Knowledge
  sources** section lists each source and its connection for exactly that.
- the **rename fix** — a net-new knowledge source is renamed to the DA-valid
  `knowledge.<Name>` schema, and any migrated topic that searches it has its
  `SearchSpecificKnowledgeSources` references repointed at the new name so the
  action does not dangle.

Custom metrics, Copilot settings, file attachments,
evaluations (test cases) and skills cannot ride in the package, but they are no
longer dropped silently: every one is **detected and reported** under *Re-create
these in the agent's settings* (with its configuration reproduced) or, where the DA
has no equivalent yet, as *not supported yet*.

**Connected agents** (the hub's `TaskDialog` delegations to the HR/IT/Facilities
agents — CA type-9 `InvokeConnectedAgentTaskAction`) are handled the same way. The
DA wires connected agents up in the agent's *Agents* settings, not in the importable
package, so the tool reports each delegation as a reconnect task that **names the
target agent** (and its DA schema name when the agent ships in this release) rather
than crashing or dropping it.

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

If the migration produced a `flows.zip` (see [§3b](#3b-cloud-flows-the-customer-authored)),
**import it first** — as an unmanaged solution into the same environment — then
import the agent package. The agent references the flows by id, so they must exist
before the agent import runs.

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

#### Auto-upgrading `AnswerQuestionWithAI`

Before a topic is disabled, `convert.py` inspects each `AnswerQuestionWithAI`
("create generative answers") node — a construct the DA has no equivalent for —
and classifies how the CA actually used it:

| class | what happens |
| --- | --- |
| *response composition* over an all-scalar parsed record | **auto-upgraded** to a deterministic `SetVariable` that renders the record, exactly how the GA templates compose `InvokeFlow → ParseValue → SendActivity`. The output variable the next `SendActivity` reads is preserved, so the topic stays active |
| *response composition* over tabular/nested data | left in place and flagged — a deterministic template cannot reproduce a table losslessly |
| *intent classification* (output drives a branch) | left in place; route it with the agent's native intent routing instead |
| *knowledge grounded* / *general knowledge* | left in place with guidance to connect a knowledge source or fold it into instructions |

A topic un-deprecates (stays active) only when **every** unsupported construct in
it was converted. A topic that mixes a convertible composition node with, say, an
intent classifier keeps the composition upgrade but still lands on the worklist
for the classifier. Every upgrade is listed in the report's *Automatically
upgraded to supported building blocks* section.

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
  package_source.py read an exported CA solution package (--from-package) as a source
  reference.py    vendored base + theirs
  projection.py   CA botcomponent → agent.yml component shape
  merge.py        three-way merge + Overlays policy
  flows.py        carry customer cloud flows (interface + flows.zip solution)
  knowledge.py    wire carried Graph-connector knowledge sources (bind + rename fix)
  instructions.py model-backed reconciliation of edited agent instructions
  llm.py          minimal GitHub Copilot API client (gh auth token)
  rules.py        constructs the DA does not support, and who must act on each
  convert.py      classify AnswerQuestionWithAI nodes; auto-upgrade the convertible ones
  assessment.py   the eligibility verdict: blockers, worklist, employee impact
  packaging.py    emit the ALM package
  deliver.py      import the ALM package into a target DA's Dev ring (opt-in, dev-ring only)
  minimalbot_deliver.py  deliver the delta into a live agent via the components API (opt-in, prod-capable, dry-run default)
  report.py       the report
  made.py         diff shipped DA vs produced package (customizationsMade.md)
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
| R3 | Prepare and validate without affecting production | partial — read-only against the source; `--deliver-minimalbot` is **dry-run by default** (reads, prints the change set, writes nothing) so you can validate without touching the agent; it does not yet create an isolated draft or run evals |
| R4 | Publish directly; ALM optional | **met (ALM optional)** — `--deliver-minimalbot` overlays your edits to shipped topics directly through the components API with **no ALM package**, on any ring incl. production; brand-new topics route to `--import` (the ALM-package path, Dev ring only). The live overlay of shipped-topic edits is verified against a Cosmos DA GA |
| R5 | Employees experience no required action or visible disruption | not addressed — out of reach for a package-generating CLI; the report names the impact instead |
| R6 | Hub migration with incremental domain migration | partial — Core (the hub) and each domain agent are first-class `--vertical` targets you migrate independently; there is no single command that orchestrates the hub plus its spokes in one pass |

R4 and R5 are scope decisions, not defects. Take them up before this is
offered to a customer.

> Update: R4's non-ALM publish path now exists (`--deliver-minimalbot`, see
> §4b and `DEV_DESIGN.md` §9.2) as a **hybrid**: your plain-text edits to shipped
> topics are overlaid onto the live agent (verified against a Cosmos DA GA), while
> brand-new topics route to the ALM package import. Gated behind a dry-run.

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
