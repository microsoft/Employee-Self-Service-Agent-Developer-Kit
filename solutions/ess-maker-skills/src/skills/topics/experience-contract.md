# Shared topic experience

Read this shared foundation before topic authoring, deletion, Push or testing. It owns common presentation, supported authoring coverage, deletion protection and authorization. Use the owning operation for execution and authoritative readback.

## Read by operation

Read only the reference needed for the current operation or next step. Load its opening instructions and applicable sections, including parent-level bindings and subordinate instructions, before acting. Read permission, safety and cleanup requirements before the action they govern. Reuse guidance already available in context; do not load every linked reference upfront.

| When                                                                                      | Reference                                                                                                                    |
| ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Drafting or reviewing a topic or related instruction correction; reporting their outcomes | [Authoring experience](authoring-experience.md)                                                                              |
| Reviewing or applying topic deletion, local-only deletion or draft discard                | [Deletion experience](deletion-experience.md)                                                                                |
| Reviewing a Push inventory or composed result; executing any approved save batch          | [Push experience](push-experience.md); standalone owners use its [Push telemetry](push-experience.md#push-telemetry) section |
| Offering or conducting topic testing; readiness, outcomes, pause or stop                  | [Testing experience](testing-experience.md)                                                                                  |

These references own the literal UX copy. Operation owners link directly to the needed references and retain their execution guards; routing prompts carry context to those owners rather than repeat the shared procedures.

## Presentation and scope

Read and apply [Authoring pattern](../../reference/ui-formatting-guidelines.md#authoring-pattern) before rendering a template. The focused references own its literal copy, placeholder bindings and applicable omission, repetition and conditional-choice rules.

Every UX instruction list is an **at-least baseline**, not an exhaustive closed list. This includes component types, summary fields, formatting guidance, choices, outcome heads, statuses, readiness cases and examples.

Include the defined baseline items where applicable and add relevant supported items through the documented bindings and repeatable entries. These baselines govern coverage; the template's fixed copy remains verbatim. Keep the agreed omission of empty or unaffected sections.

Extensibility does not reintroduce explicitly excluded rules or options, invent capabilities, or expand consent. A displayed inventory, selected batch or approved debugging scope remains concrete and bounded; unlisted work is not silently authorized.

Use ordinary chat for open-ended requirements and revisions. Do not put a free-text-only exchange in a structured question. Retain structured controls for genuine choices; render summaries and previews in normal chat before a separate short control, not inside a long question description.

Use terse, external, semi-technical language about behavior and interfaces, without internal node labels. Use bold labels with whitespace between sections, short bullets for multiple inputs/outputs and required/optional markings where useful, inline code only for technical names the developer needs, and a link to the full draft for detail.

Omit genuinely empty sections. Unresolved information is not absence: identify it as unresolved rather than omitting it or calling it absent. Apply [Response wording and local drafts](authoring-experience.md#response-wording-and-local-drafts) when presenting literal response text. Describe dynamic content without inventing its rendered response. For lengthy wording, provide a clearly labeled excerpt and access to the full text.

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
