---
name: workday-oss-import-draft
description: Draft an experimental import of selected Workday DA GA OSS topics and the shared template-config setup topic into an existing editable agent using the Copilot Studio browser components API. Use for OSS import planning or reviewing this prototype, not ordinary topic creation or published-agent deployment.
---

# Workday OSS topic import - draft

**Experimental design, not a released importer.** This skill defines the native
browser-API workflow and includes a working **read-only local planner**. It does
not implement a create-topic client or change the released `/create` or `/push`
gates. Do not execute live writes until the creation contract, compatibility
checks and explicit experimental opt-in below have been implemented and reviewed.

The intended customer flow is: import the shared template-config setup topic
once, then import only the selected scenario topics. Configure it after OOB
Workday initialization on Conversation Start. No per-scenario Dataverse
template-configuration records, new flows or publish operation are involved.

## Inputs and boundaries

- Use the user-selected environment, tenant, ring, editable **Dev** agent and
  Microsoft work account. Read canonical setup/configuration through the existing
  setup/auth helpers; confirm the target if it differs from that selection.
- Ask which employee/manager scenarios to add. Never infer "all" from "OSS".
- Source files come from `samples/WorkdayDeclarativeAgentGA` in the ADK checkout,
  not a fresh cross-repository download or the legacy reference mirror.
  The root has `WorkdayOSSTemplateConfigurationSetup.yaml`; each scenario has
  `topic.yaml`. A packaged kit without that folder needs the matching reviewed
  sample checkout supplied explicitly.
- Record the source Git commit and file hashes. Do not silently change the source,
  rewrite unsupported nodes, change XML casing/API versions, or import Preview.
- Never modify OOB scenarios, flows, connections, permissions, auth settings or
  global-variable definitions. Never publish, test Workday writes, delete a topic,
  deactivate an overlapping topic or bulk-replace the agent.
- Existing topics/configuration are preserved by default. An update or activation
  requires a separate, exact diff and approval. Names alone are not identity.
- Follow [the observed protocol and unresolved gates](references/browser-api-contract.md).
  This private authoring surface can change; Microsoft Learn is not its API spec.

## 1. Build the local plan - no credentials or network

From the Maker Kit workspace, run the bundled planner:

```powershell
python src\skills\topics\import-oss-draft\scripts\plan_import.py `
  --samples-root <ADK-checkout>\samples\WorkdayDeclarativeAgentGA `
  --topics EmployeeGetVacationBalance WorkdayGetEducation
```

Use `--all` instead of `--topics ...` only when the user explicitly selected all
scenarios. The planner prints hashes, action kinds, child-dialog dependencies,
template mappings and blockers, not XML values or customer data. It never applies
the plan. Errors go to stderr with a nonzero exit code.

Resolve local blockers before any import. In particular, treat
`AnswerQuestionWithAI` as **not approved for this DA GA prototype**. Do not claim
all other kinds are supported merely because YAML parses or the editor saves.
Inspect every nested `actions` and `elseActions` branch, card, Power Fx expression
and output type against evidence for the selected platform/version.

Retain separate Workday runtime review for emergency-contact API compatibility,
manager `Cost_Center` XPath casing and response-group exclusions. Do not call the
sample release-ready based on this plan.

## 2. Read the target and reconcile dependencies

This stage is read-only. Reuse `scripts/agentbuilder.py` for selected-tenant
authentication, ring/host validation and `fetch_components()`. Keep credentials
in memory/existing protected caches; do not harvest cookies, log bearer tokens or
write HAR/auth headers. An API 401/403 or consent prompt is a stop, not a reason to
switch accounts, hosts, endpoints or Dataverse paths to get around the failure.

Capture a private local baseline of component identities, versions, content and
the current change token outside tracked files. Resolve scenario `BeginDialog`
references to actual target HR system topics; reject missing/ambiguous matches.
Do not blindly replace schema prefixes or alter caller/callee bindings.

Verify initialized employee context and existing common execution/access topics.
Manager selections also require initialized manager status and organization.
`msdyn_WorkdayHCMRuntimeEmployeeGetWorkAddress` and
`msdyn_WorkdayHCMRuntimeEmployeeGetWorkContactInformation` are OOB dependencies,
not templates supplied by the shared OSS file.

Match prior imports using a verified receipt's component ID/schema and content.
Without a receipt, inspect both identity and content; a similarly named topic may
be a customer customization. Preserve it and ask rather than duplicate/overwrite.
Apply the same rule to a manually installed shared template-config setup topic.

## 3. Present the exact mutation plan and get approval

Show the target agent/environment/account, selected scenario names, source commit
and hashes, proposed new identities, existing components to preserve, compatibility
findings, and any setup/Conversation Start update. Explain that importing all
template values can override matching OOB keys, while unrelated keys survive.

Confirm this exact experimental write scope. Drafting this skill, a previous
agent import, or having a signed-in browser is not permission to apply it.
If the create contract or support gate is unresolved, stop at the plan.

## 4. Intended apply workflow - implementation/review gate

After the prototype is implemented, reviewed and explicitly approved:

1. Convert selected YAML with `scripts/agentbuilder_object_model.py`'s
   `yaml_to_object_models()`. Require every result to succeed as `AdaptiveDialog`.
   Round-trip with `object_models_to_yaml()` and compare semantics; stop on loss
   or unsupported conversion. Never rename YAML `kind` keys to `$kind` yourself.
2. Verify the current browser's creation envelope using the first **approved real
   topic**, if no reviewed capture for this API version exists. Normal code-editor
   paste/save must be scope-approved. Do not create dummy/probe topics.
3. Use the observed components PUT protocol for subsequent creates. Take IDs and
   create/update wrappers from the current contract, not this draft's guesses.
   Use a fresh change token, minimal scoped changes and sequential writes.
4. Preserve an existing shared template-config setup topic. For a new one, create
   it once. Never automatically replace its customer XML/configuration.
5. Preserve correct existing Conversation Start wiring. If missing, propose the
   smallest approved redirect after OOB Workday configuration initialization and
   before scenario execution. Use one wiring path; do not guard it behind cached
   user-profile refresh. Do not silently add a second call.
6. After each write, reconcile with a fresh component read before continuing.
   A timeout/ambiguous result is **not** permission to retry creation. On drift,
   conflict, auth failure or unexpected changes, stop and report partial progress.

The existing scoped `update_dialog_components()` helper supports **existing**
dialogs; `/push` rejects new topics. Do not remove those guards or pass creations
to that helper. A create-capable client is an explicit remaining implementation
deliverable, not something this draft pretends already exists.

## 5. Verify, record and hand off

Verify nonzero unique IDs, expected schemas, canonical dialog content, selected
activation state and per-component diagnostics. Confirm all pre-existing
components outside the approved scope still match the baseline. Check the shared
lookup mappings and the single OOB-before-OSS initialization path.

Store a private receipt with source hashes, target identity, created/preserved
component IDs, verification status and diagnostics. Never store auth headers or
employee responses. Checkpoint only verified imported paths, not unrelated pending
edits. On rerun, re-read identities/content; skip verified equivalents and surface
drift. No automatic rollback/deletion; remediation needs a new approved plan.

Report `planned`, `blocked`, `partially imported` or `imported and read back`
accurately. Distinguish parse, authoring, dependency, wiring and runtime results.
Do not describe "saved" as "works", or "imported" as "published". Runtime testing
in a fresh conversation remains a separate approved step.

## Microsoft documentation

Use Microsoft Learn for current authoring/authentication context, not to infer
the private browser API or DA node compatibility:

| Need | Lookup |
|---|---|
| Topic/code-editor workflow | `microsoft_docs_search(query="Copilot Studio create edit topic code editor YAML")` |
| Authenticated user context | `microsoft_docs_fetch(url="https://learn.microsoft.com/microsoft-copilot-studio/advanced-end-user-authentication")` |

If Learn MCP is unavailable, use the CLI fallback:

| MCP tool | CLI |
|---|---|
| `microsoft_docs_search(query)` | `npx @microsoft/learn-cli search "<query>"` |
| `microsoft_docs_fetch(url)` | `npx @microsoft/learn-cli fetch "<url>"` |
| `microsoft_code_sample_search(query, language)` | `npx @microsoft/learn-cli code-search "<query>" --language <language>` |
