# Shared topic experience

<!-- markdownlint-disable MD001 -->

Read this shared foundation before topic authoring, deletion, Push or testing. It owns common presentation, supported authoring coverage, deletion protection and authorization. Use the owning operation for execution and completion evidence.

## Read by operation

Read only the reference needed for the current operation or next step. Load its opening instructions and applicable sections, including parent-level bindings and subordinate instructions, before acting. Read permission, safety and cleanup requirements before the action they govern. Reuse guidance already available in context; do not load every linked reference upfront.

| When                                                                                      | Reference                                                                                                                    |
| ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Drafting or reviewing a topic or related instruction correction; reporting their outcomes | [Authoring experience](authoring-experience.md)                                                                              |
| Reviewing a Push inventory or composed result; executing any approved save batch          | [Push experience](push-experience.md); standalone owners use its [Push telemetry](push-experience.md#push-telemetry) section |
| Offering or conducting topic testing; readiness, outcomes, pause or stop                  | [Testing experience](testing-experience.md)                                                                                  |

These references own the literal UX copy. Operation owners link directly to the needed references and retain their execution guards; routing prompts carry context to those owners rather than repeat the shared procedures.

## Status update markers

An `{EMIT_STATUS_UPDATE: point}` marker identifies where to report the outcome of the preceding work, not a successful result or literal text to display. Before the marked work, load the point's completion condition and message from the experience section linked by the operation. Reuse those definitions while they remain available in context.

At the marker, assess the available evidence. Emit the defined completion message only when its completion condition is satisfied. Otherwise, select or compose a concise status update appropriate to the observed result using the owning experience's outcome guidance. Explain what failed, remains incomplete, required no change, or cannot be confirmed. Preserve known successful effects and distinguish an observed cause from an unknown one.

Send the update as a standalone normal-chat message before proceeding to the next step. Keep required reviews, outcome reports and questions in separate subsequent messages, even when they repeat the same fact. Emit once for the observed result at that point; assess and report a revised result anew. Then follow the operation's applicable continuation, pause or recovery instructions without expanding its authorization.

Apply markers at their defined reporting points, including failed or incomplete attempts, rather than after every tool call. If the marked work stops before its normal reporting point, emit its observed outcome before pausing or returning. Do not enter reporting points for work that was never requested or selected. Reuse an existing still-current assessment rather than repeating work only to emit an update.

The operation performing the work owns its status update. A delegating caller carries the reporting context and reuses the owner's update without emitting it again. Required composed reports remain separate. When the caller performs work without an emitting owner, it uses the definition and marker specified at that dispatch point. Pause and stop acknowledgements take precedence over a generic status message for the same result.

## Presentation and scope

For topic authoring, deletion, Push, testing and cleanup, use the operation-linked status definitions and markers, not native todo lists or Markdown progress checklists. Keep previews, decisions and results separate. Setup and other operations retain their own progress rules.

Read and apply [Authoring pattern](../../reference/ui-formatting-guidelines.md#authoring-pattern) before rendering a template. The focused references own its literal copy, placeholder bindings and applicable omission, repetition and conditional-choice rules.

Every UX instruction list is an **at-least baseline**, not an exhaustive closed list. This includes component types, summary fields, formatting guidance, choices, outcome heads, statuses, readiness cases and examples.

Include the defined baseline items where applicable and add relevant supported items through the documented bindings and repeatable entries. These baselines govern coverage; the template's fixed copy remains verbatim. Keep the agreed omission of empty or unaffected sections.

Extensibility does not reintroduce explicitly excluded rules or options, invent capabilities, or expand consent. A displayed inventory, selected batch or approved debugging scope remains concrete and bounded; unlisted work is not silently authorized.

Use ordinary chat for open-ended requirements and revisions. Do not put a free-text-only exchange in a structured question. Retain structured controls for genuine choices; render summaries and previews in normal chat before a separate short control, not inside a long question description.

For mixed-operation results, use a consolidated report only where the owning experience explicitly defines one, such as [composed Push](push-experience.md#composed-push-report-composed_push_report). Otherwise retain each operation's required outcome heading and facts in the combined response, showing shared [Target context](#target-context) once.

Use terse, external, semi-technical language about behavior and interfaces, without internal node labels. For topic-workflow reviews, previews and reports, render field labels as own-line level-five Markdown headings in ALL CAPS, followed by a blank line and content, without horizontal rules or trailing colons. Under Outputs, nest child labels and literal quotations within their output bullet using indented level-six headings. Each Routing Conflicts parent bullet gives the conflict and applicable consequence. Put its recommendation in a nested sub-bullet in the form "I recommend we {Concrete next action} to resolve this." Do not add a Suggested actions subheading. Notes' SUGGESTED ACTION headings remain level five outside list indentation, immediately after their issue. Not included uses conversational bullets with the component subgroup bolded within each sentence, not subgroup headings or label-colon prefixes. Keep status/outcome sentences, literal responses, field values and picker options in their original casing and wording. Use short bullets for multiple inputs/outputs and required/optional markings where useful, inline code only for technical names the developer needs, and a link to the full draft where its template defines one.

Omit genuinely empty sections. Unresolved information is not absence: identify it as unresolved rather than omitting it or calling it absent. Apply [Response wording and local drafts](authoring-experience.md#response-wording-and-local-drafts) when presenting literal response text. Describe dynamic content without inventing its rendered response. For lengthy wording, provide a clearly labeled excerpt and access to the full text.

Present the applicable review, then the short choice control without a YOUR CHOICES table or per-option explanatory text. Keep material effects, destructive consequences and the scope of consent in the review, not in expanded picker labels. Use the owning JSON with an empty top message, contextual title and fixed inner question, allowing custom text. Substitute discovered values and documented conditional choices only; never display JSON or unresolved placeholders to the maker. Submit, keyboard hints and close/collapse controls belong to the host.

### Target context

Resolve `{Target context}` from the selected operation's target and render these two lines, with a Markdown line break between them:

> {Agent name}\
> {Environment name} - {ALM realm}

Use the existing Agent or Target section when present. Otherwise place this context immediately after the review or outcome heading, without adding Environment or ALM Realm headings. When an inventory's opening sentence already names the agent, append only the environment-and-realm line there. Include context once per complete review or report, not once per component row. A nested owner summary reuses the enclosing report's context.

Include context in authoring and instruction reviews, Push inventories and selected/component reviews, deletion and draft-discard reviews, testing readiness, and cleanup reviews. Retain it in standalone completion summaries, including local drafts, no-change, cancellation, deferred testing, failed, uncertain and partial outcomes, debugging results and zero-error cleanup results. For an empty or failed Push inspection, identify the target that was inspected or could not be established.

Do not repeat this block in short status updates, choice controls, free-text revision questions, or the immediate pause/stop acknowledgement. Any separate outcome report still includes it.

Use `target.agent.realm` from the owning operation when available; `dev`, `test` and `prod` display as Dev, Test and Prod. Resolve the environment name from matching target metadata or canonical setup evidence tied to the same environment ID. If the name is unavailable, use the known environment ID; if identity or realm is not established, say Not established rather than guessing or hiding the missing value. Do not infer ALM realm from service ring, environment name or SKU. Retrieved results use their recorded target, not a different currently selected agent. Local-only outcomes identify the intended destination without implying a remote save. Presentation does not relax an owner's target-verification prerequisites.

## Topic selection

Carry a known topic forward without another question. When identity is genuinely ambiguous, use the operation's current discovery and readback to show candidate titles and short purposes. Bind each option to its exact discovered identity; distinguish duplicate titles with useful target context. Accept a free-text name or description without requiring name recall, then resolve identity before proceeding. Selection alone authorizes no edit, save, deletion, activation or test.

Show candidate titles and short purposes as discovery information, not an explanation of each picker option. Repeat the `enum` entry for each actual candidate. Call `ask_user`:

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "topic": {
        "type": "string",
        "title": "Topic selection",
        "description": "How would you like to continue?",
        "enum": ["{Discovered topic title}"]
      }
    }
  }
}
```

## Supported authoring scope

This release's supported authoring scope is one employee intent, optional input collection and local conditional logic, ending in approved text.

Makers may author outside this scope with an explicit disclaimer that these uses are permitted but unsupported in this release. Examples include cross-topic calls, live lookups, business actions and modifications to shipped topics. The support boundary is not an authoring restriction.

For a request outside the supported scope above, begin the first authoring review, clarification or outcome response in normal chat with the following callout, once per request. Keep it in that response, not in an interim progress message. Do not repeat it in revisions or continuations, or show it for supported requests.

> > **Important**
> >
> > This release only supports text-response topic authoring. Customizations to shipped topics and more complex topic behavior may be attempted, but are outside this release's supported scope.

Do not silently remove requested or existing behavior to fit supported coverage.

Use the ordinary YAML authoring owners. Do not treat optional exact-response compatibility as a universal admission requirement. Separately scoped agent-instruction corrections retain their own preview and consent requirements.

## Authoring policy for this release

Resolve the selected agent and the topic's exact identity through current inventory and the owning operation's readback. For a new topic, use the proposed schema identity from the selected agent and filename stem; it has no existing component to read back.

Missing customer-origin evidence does not block authoring or deletion, including for topics created by another author or in another workspace. Do not require creation receipts, shared provenance metadata or maker attestation as an eligibility prerequisite. Retain unknown origin as unknown rather than claiming verified customer ownership.

A genuinely new topic can proceed through Create with a new schema identity that does not collide with current agent inventory. Creation also requires a unique display name in the selected agent, compared case-insensitively after trimming surrounding whitespace. If the requested name already exists, stop and request a different name; preserve any existing draft. Meaningful intent overlap under a different name remains advisory.

Unclear target identity, denied access, unavailable required reads and conflicting edits require their owning operation's safety handling. Name the actual blocker; missing topic-origin evidence alone is not one.

### Template protection for deletion

Topic deletion is not available in this release. Preserve local files, baselines and mappings. The protection rules below also apply when assessing pending deletions; they do not enable a deletion operation.

Do not delete template-provided topics through topic deletion, Push or cleanup, including local-only deletion. Apply this section before deletion; inventory classifications do not override it.

The inventory target is DA-GA: the Core, HR and IT families from `sources/dev/AgentTemplates` declared in `catalog.authoring-additions.json`. The companion catalog also includes solution-backed DA families outside this target. Do not include those rows in DA-GA coverage, substitute DA-Preview inventories or translate their schema prefixes into DA-GA identities.

Before deleting a local topic or dispatching its remote deletion, apply the following checks. Reuse an assessment only while the selected target, topic identity and inventory evidence remain current.

1. Read all data files matching `src/reference/topic-actions/catalog.*.json`, excluding `catalog.schema.json`. Consult their `packages[].topics` together, not just the first file or an action set's member list. The supplement's `baseCatalog` identifies the required companion and its pinned source. A missing, unreadable or incompatible companion leaves combined coverage unverified; having two files alone does not establish completeness.
2. Resolve the selected agent and topic identity using current inventory and the owning operation's readback. Match full `schemaName` values within the evidenced source family. Keep template-family, package-version and source-revision distinctions; do not match only display names or infer origin from a schema prefix such as `msdyn_`.
3. Use each supplement package's `combinedTopicInventory` as coverage of the union for its recorded source revision, not of every installation with the same version string. Its count and SHA-256 describe the complete sorted full-schema list, joined by LF with a final LF. Preserve source evidence from both catalogs. Identical identities can be combined; conflicting identity or source evidence must be resolved rather than choosing a file by ordering. Action-set classifications, `required` flags and action-set approval metadata do not decide this authoring policy.
4. An applicable inventory match or other established template origin means the topic is protected from deletion, including examples, helpers and integration topics. A nonmatch is not proof of customer ownership. When no template origin is established, continue with ordinary scope, preview, authorization and concurrency checks.

For a template-protected deletion, name the topic, explain its deletion protection, and identify the next safe action. Say that the deletion was not started. Preserve an existing draft unchanged. In a Push inventory, keep the deletion pending with its specific reason under Not included; do not offer a runnable deletion for it. If the restriction is discovered after approval, report the actual no-write outcome using the existing outcome contract. Preserve earlier successful operations and pause any dependent routing correction.

Approval, a debugging objective or a request to fix compile errors does not authorize template-topic deletion. Read-only inspection and reporting remain available.

## Authorization and recovery

Ordinary authoring requires separate topic and instruction approvals. A topic save does not implicitly approve an instruction save.

A displayed Push batch has the scoped consent in [Push experience](push-experience.md); do not repeat independent approvals for its unchanged approved operations. Carry the exact target, selected changes and material consequences into each owner.

Ordinary update approval covers safe recovery that still achieves the same approved change and preserves unrelated content, subject to owner safety/concurrency guards. Re-show the change-focused summary and obtain fresh approval for a materially changed target, behavior, scope or treatment of conflicting edits. For a rejected conflicting save, retain the truthful outcome head, then render the Update summary with Title, Agent, the freshly read current wording versus the proposal, verified Unchanged facts, applicable advisories and Full draft. Follow it with the specific replacement or draft-only decision; the conflicting excerpts alone do not replace the summary.

The scoped debugging exception is not blanket permission attached to a command named `/test`. A test-only request must not silently authorize edits. Establish the debugging objective and editable scope from an explicit request or the state-aware [Testing offers](testing-experience.md#testing-offers). Carry that authorization into delegated topic or instruction work; an owner does not ask again for necessary in-scope fixes and pushes.

Within that authorization, repeated necessary fixes, pushes and retests do not each need fresh approval. Ask again for expanded scope, changed intended behavior or additional consequential actions. Preserve concurrency safeguards, known outcomes and uncertainty; do not blindly repeat an uncertain operation. The exception does not itself authorize publication or unrelated changes.
