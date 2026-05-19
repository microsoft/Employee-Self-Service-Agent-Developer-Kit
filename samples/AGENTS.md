# Agent Guidance — `samples/`

You are working inside the `samples/` folder of the Employee Self-Service Agent Developer Kit. This file is the authoritative briefing for any AI agent making changes here. For changes scoped to `samples/`, follow this file unless higher-priority system, security, or repository instructions say otherwise.

## What this folder is

Reference samples for the Microsoft Copilot Studio Employee Self-Service (ESS) agent. Each sample is a Copilot Studio **topic** plus its **ESS Template Configuration** XML(s). Samples are reference content — not a shipped product. See [`SUPPORT.md`](../SUPPORT.md).

## Layout (source of truth: this repo)

Top-level areas under `samples/` today:

| Area | Sub-grouping | Notes |
|---|---|---|
| `Facilities/` | flat (`<TopicFolder>/` directly) | Office/dining/guest/vehicle topics. |
| `WorkdayCustomEngineAgent/` | `Employee/`, `Manager/`, `Extended/` | Workday Custom Engine Agent (CEA) topics. |
| `WorkdayDeclarativeAgent/` | `Employee/`, `Manager/` | Workday Declarative Agent (DA) topics. |
| `ServiceNow/` | empty placeholder | Currently empty. Only add a ServiceNow topic when an issue explicitly requests one and provides enough details. |

Topic path patterns:

- `samples/Facilities/<TopicFolder>/`
- `samples/WorkdayCustomEngineAgent/{Employee|Manager|Extended}/<TopicFolder>/`
- `samples/WorkdayDeclarativeAgent/{Employee|Manager}/<TopicFolder>/`

## A topic folder typically contains

- `topic.yaml` — Copilot Studio AdaptiveDialog (`kind: AdaptiveDialog`). Defines `inputs`, `modelDescription`, `beginDialog`, etc.
- One or more `*.xml` files — ESS Template Configuration. Filenames start with `msdyn_` by convention.
- `README.md` — *expected for new topics; preserved as-is for existing topics that already have one or don't.* See **README expectations** below.
- Optional assets (screenshots, diagrams, sample payloads) referenced by the README. Use lowercase, hyphenated filenames (e.g., `get-vacation-balance.png`).

### README expectations (for new topics)

The README should read as one continuous, easy-to-follow explanation — not a checklist of headings. Write it so a reader who has never seen the topic before can understand *what it does*, *how it works*, and *how to customize it*, in a single read.

Cover the following naturally, in roughly this flow:

- **What the topic does** — one short paragraph in plain language: the user scenario, the persona, and the outcome.
- **How it works** — a brief walkthrough of the topic's behavior: trigger style, inputs it collects or receives, downstream calls (sibling XML, flows, child topics), and what the user sees back. Keep it conceptual; do not paste the full YAML.
- **Customization points** — the realistic things a consumer would change, each with a small concrete example. Typical examples:
  - Trigger phrases or `modelDescription` adjustments for a different vocabulary.
  - Input bindings (e.g., where employee ID or manager org ID comes from in the customer's environment).
  - Endpoint / environment values that come from `Env.*`.
  - Adaptive card field labels, ordering, or optional fields.
  - Localization or tone changes in user-facing messages.
- **Assets** — reference any images or sample payloads inline at the point where they help the reader (e.g., a screenshot right after describing the card).
- **Related topics or dependencies** — name any sibling topics, flows, or XML configs the topic relies on, with relative links.

Style guidance:

- Write in second person, present tense.
- Prefer short paragraphs over long bullet lists; use bullets only where they genuinely clarify (e.g., a list of inputs).
- Show small, copy-pasteable snippets for customizations rather than abstract descriptions.
- Do not duplicate the YAML or XML verbatim — link or excerpt only what the reader needs to understand the customization.
- No internal URLs, customer-specific IDs, or secrets.

For **existing topics** without a README, do not retrofit one as part of an unrelated change. A README can be added when the topic itself is being modified for another reason, or via a dedicated documentation issue.

## Naming conventions (observed)

- Folders: PascalCase, action-oriented (`EmployeeGetVacationBalance`, `EmployeeInviteGuest`).
- XML: `msdyn_<Area><Action>.xml`.
- **Documented inconsistencies — do NOT "fix" these:**
  - Some `WorkdayDeclarativeAgent/Employee` folders use lowercase / run-together names (e.g., `WorkdayEmployeesviewtheirjobtaxonomy`).
  - One Facilities file has a trailing dot (`msdyn_DiningGetMenusQuery..xml`).
  - Some XML files use lowercase prefixes (`msdyn_copilotforemployeeselfservice...`).

For **new** files, follow the PascalCase + `msdyn_<Area><Action>.xml` convention. For **existing** files, preserve names exactly.

## Before you create or change anything

1. **Read a sibling topic first.** Pick the nearest topic in the same area and sub-grouping. Mirror its top-level YAML keys, its XML root element, and its file layout.
2. Confirm the target area, sub-grouping (Employee/Manager/Extended), and topic folder from the issue. If any of these is ambiguous, **stop and ask**.
3. Run issue triage before editing files. Do not create or modify topic files until the issue is classified as actionable.
4. Keep all changes inside `samples/`. For topic-related issues, do not edit `solutions/`, repo-root files, or `.github/`. Changes to `.github/agents/skills/` are allowed only when the task is explicitly about agent workflow guidance (not when fulfilling a topic request).

## Safety boundaries (hard rules)

- No renames of existing folders or files.
- No deletions of existing topics.
- No new top-level area unless the issue explicitly names the ISV and provides at least one topic.
- No external network calls. No secrets in files.
- One issue → one PR. No auto-merge. Human review required.
- Diff must be confined to a single topic folder (or a single new topic folder) unless the issue explicitly requires more.

## When to stop and ask for clarification

Stop and ask if:

- The target area or ISV is unclear.
- The target sub-grouping, such as `Employee`, `Manager`, or `Extended`, is unclear.
- The target topic folder is unclear.
- The issue does not say whether this is a new topic or a fix.
- Required behavior, inputs, outputs, or API/config details are missing.
- The requested change would require edits outside `samples/`.

## Validation before PR

Before preparing a PR, run every check in [`.github/agents/skills/validate-sample-topic/SKILL.md`](../.github/agents/skills/validate-sample-topic/SKILL.md) and paste its summary block into the PR body. The checks are:

- YAML well-formedness (changed `topic.yaml`).
- `topic.yaml` has top-level `kind: AdaptiveDialog`.
- Neighbor-key parity for new `topic.yaml` against its sibling reference.
- XML well-formedness (changed `*.xml`).
- Filename convention for **new** XML files (`msdyn_` prefix).
- Folder convention for **new** topic folders (PascalCase, contains `topic.yaml`, at least one `*.xml`, and `README.md`).
- Diff scope limited to a single `samples/<Area>/.../<TopicFolder>/`.
- No secrets or internal URLs in the diff.

## Topic YAML authoring guidance

High-level rules for `topic.yaml` files in this repo. The **existing samples folder is the source of truth** — when this guidance and a nearby sibling topic disagree, mirror the sibling.

Two framings used throughout:

- **For new topics** — prefer the patterns below unless the nearest sibling in the same area uses a different established structure.
- **For existing topics** — preserve the current structure and make the smallest targeted change. Do not retrofit existing topics to match this guidance.

Step-by-step execution (creation checklist, edit checklist, bug-fix tracing) lives in [`create-or-update-sample-topic/SKILL.md`](../.github/agents/skills/create-or-update-sample-topic/SKILL.md). This file stays at the briefing level.

### Topic archetypes

Classify before authoring or editing:

- **User-facing UI topic** — usually `OnRecognizedIntent`. Talks to the user, collects inputs, calls a system topic, renders results.
- **System topic** — usually `OnRedirect`. No user prompts. Receives parameters, calls flows/APIs or other system topics, returns structured output.
- **Lifecycle / shared topic** — `OnConversationStart`, `OnError`, or `OnEvent`.

### Standard `topic.yaml` shape

Use what applies; mirror the nearest sibling:

- `kind: AdaptiveDialog` (always)
- `modelDisplayName` (optional)
- `modelDescription` (recommended for LLM-routed UI topics)
- `inputs` (when accepting caller/LLM input)
- `beginDialog` with the trigger and ordered `actions`
- `inputType` / `outputType` (when callable as a child dialog or returning structured data)

Do not invent unsupported top-level keys or action kinds.

### Common action kinds

`SetVariable`, `ParseValue`, `BeginDialog`, `InvokeFlowAction`, `AdaptiveCardPrompt`, `Question`, `SendActivity`, `ConditionGroup`, `GotoAction`, `LogCustomTelemetryEvent`, `EndDialog`, `EndConversation`, `CancelAllDialogs`.

If a different action kind seems necessary, verify it appears in a sibling topic. Otherwise **stop and ask**.

### Creating a new topic

For new topics, confirm: archetype, persona, read-only vs mutation, trigger style, inputs and their source (LLM / caller / `Topic.*` / `Global.*` / `Env.*` / `System.*`), outputs, downstream calls (child topics, flows, sibling XML), and the five UX states (success-with-data, success-with-no-data, validation failure, downstream error, user cancel). Author by mirroring the nearest sibling. Detailed checklist in the create-or-update skill.

### Modifying an existing topic

- Read the file before editing.
- Make the smallest safe change.
- Preserve action `id:` values, action ordering, and `ConditionGroup` branches not targeted by the change.
- Do not rename or remove existing `inputs`, and do not rename or retype existing `inputType` / `outputType` properties — add new properties instead of changing existing contracts.
- New variables go under `Topic.*` unless cross-topic persistence requires `Global.*` or environment config requires `Env.*`.

### Bug fixes

Required from the issue: current behavior, expected behavior, repro/transcript if available, target topic path. When fixing, trace the `actions` list before editing (record the trace in the PR), make the minimal change, and prefer adding `IsBlank` / `IsBlankOrError` guards or an explicit `ConditionGroup` branch over broad rewrites. If the bug is in `ParseValue` schema, confirm the upstream response shape first.

### Triggers and routing

- Deterministic UI topics: trigger phrases include the object/action, not generic verbs alone (`update my phone number`, not `update`).
- LLM-routed topics: `modelDescription` should cover **scope**, **trigger only if**, **do not trigger if**, and **valid / invalid examples**.
- Avoid overlapping trigger phrases with sibling topics; the more specific topic explicitly excludes the broader scenario.

### Variables and inputs

- `Topic.*` for topic-local state.
- `Global.*` only for values that must survive across topic boundaries.
- `Env.*` for environment-specific values (base URLs, tenant values, feature flags).
- `System.*` is read-only runtime info.
- Every `AutomaticTaskInput` should have a plain-English `description`. If required and not safely inferable, set `shouldPromptUser: true`. Optional inputs default to blank and are guarded before use.

### API / action invocation

- *Preferred for new topics where the area supports this pattern:* keep UI topics decoupled from direct API/flow calls — UI topics call system topics; system topics call flows/APIs.
- System topics validate required inputs before invoking downstream calls.
- Branch explicitly on success/failure after every downstream call.
- Never hardcode customer-specific IDs, tenant IDs, sys_ids, URLs, or secrets — use `Env.*`, `Global.*`, or documented configuration.

### Adaptive cards

- Inputs have stable `id`, clear `label`, and required-field validation when needed.
- Mutating actions include both Submit and Cancel; Cancel must not be blocked by required-field validation (`associatedInputs: "none"`).
- Bind inputs to `Topic.*` and bind the card action submit id to `Topic.actionSubmitId`; branch on it.
- Do not assume the host can edit, delete, or re-render a previously posted card. To change shown information, post a new card.
- *Preferred for new cards:* keep one Adaptive Card version per topic, matching the nearest sibling.

### Errors, empty states, mutation, cancel

- Topics that call downstream APIs/flows handle three outcomes: success-with-data, success-with-no-data, failure.
- Count or check result rows before rendering; show a friendly empty-state message instead of a generic success.
- Do not swallow errors silently; failures should reach the user or telemetry — preferably both.
- Mutation topics ask for confirmation before mutating; the confirmation card has Submit and Cancel; final cancel sends a clear acknowledgement and exits cleanly. Never auto-confirm a mutation on intent recognition alone.
- Use clear second-person language. Do not expose raw error codes, GUIDs, sys_ids, or stack traces in user-facing messages.
- Every terminal path ends explicitly with `EndDialog`, `EndConversation`, or `CancelAllDialogs`.

### YAML authoring rules

- Two-space indentation, no tabs.
- Quote strings that contain `:` or start with `=`. Power Fx expressions start with `=`. Use block scalars (`|-`, `|`, `>-`) for long expressions.
- Action `id:` values are unique within a topic and stable across edits.
- `displayName` is for readability; do not treat it as behavior.
- `intent: {}` is required on `OnRecognizedIntent` when applicable.

### Good patterns and anti-patterns

**Good (prefer for new topics):** read the sibling topic first; use `Topic.actionSubmitId` for card-action branching; `ParseValue` with explicit schema after downstream calls; guard external values with `IsBlank` / `IsBlankOrError`; positive **and** negative trigger examples for LLM-routed topics; UI/system separation where the area already supports it.

**Anti-patterns:** calling APIs directly from UI topics when the area has a system-topic pattern; empty responses falling through to success; hardcoded identifiers/URLs/secrets/large base64 images; renaming or retyping existing `inputType` / `outputType`; skipping cancel paths in mutation topics; reordering or rewriting unrelated actions; broad cleanup inside a bug-fix PR.

### PR summary expectations

PR descriptions should include:

- One sentence describing user-visible behavior after the change.
- A list of every file changed and why.
- **New topics:** trigger utterances; `Global.*` and `Env.*` read; child topics invoked; flows/APIs/sibling XML involved.
- **Modified topics:** before/after of the changed behavior; whether `inputType` or `outputType` changed.
- **Bug fixes:** a short trace of how the original actions reached the wrong outcome, and the minimal change made.

## Skills to use

Located under [`.github/agents/skills/`](../.github/agents/skills/):

1. `triage-sample-issue` — classify the issue.
2. `create-or-update-sample-topic` — make the change.
3. `validate-sample-topic` — validate before PR.
4. `prepare-sample-pr` — branch, commit, PR body.

Run them in that order.

## Labels used in this area

- `area:samples` — applies to all samples issues/PRs.
- `agent:eligible` — issue has enough info; agent may proceed.
- `agent:needs-info` — agent posted a clarification comment.
- `agent:blocked` — external dependency.
- `agent:out-of-scope` — request outside `samples/` rules.

## Known gaps / future work

- No published JSON Schema for `topic.yaml` or the ESS Template XML. Validation is structural + well-formedness + neighbor-similarity only.
- `ServiceNow/` is currently an empty placeholder. Only add ServiceNow topics when an issue explicitly requests one and provides enough details.
- Optional automation (CI validation workflow, duplicate-issue detector) is deferred.
