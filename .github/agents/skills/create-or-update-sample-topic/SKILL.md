# Skill: Create or update a sample topic

**Preconditions:** triage produced `actionable-new-topic` or `actionable-fix`. You have read [`samples/AGENTS.md`](../../../../samples/AGENTS.md).

This skill is the execution layer. `samples/AGENTS.md` defines *what good looks like*; this file defines *the steps to get there*.

## Procedure

1. **Read a neighbor first.**
   - Pick the sibling topic that is most similar in content and within the same sub-grouping.
   - Read its `topic.yaml` end-to-end and at least one of its `*.xml` files.
   - Note its top-level YAML keys, XML root element, and file layout. This is your shape reference. Record the path — you will cite it in the PR.

2. **Pick exactly one path from the table below and follow only that section. Do not read the other sections.**

   | Triage label          | Issue is a bug fix? | Go to                  |
   | --------------------- | ------------------- | ---------------------- |
   | `actionable-new-topic`| n/a                 | **New topic checklist**|
   | `actionable-fix`      | yes                 | **Bug-fix tracing**    |
   | `actionable-fix`      | no                  | **Modify-topic rules** |

3. **Hard rules (always).** Apply every rule in every group:

   *File-scope rules:*
   - Do not rename or delete existing files or folders.
   - Confine the diff to one topic folder (or the new topic folder).

   *Security rules:*
   - No secrets, no internal URLs.

   *Schema rules:*
   - Do not invent unsupported top-level YAML keys or action kinds. Verify any unfamiliar key/kind appears in a sibling topic; if not, stop and ask.

## New topic checklist

Walk through every step before writing YAML:

1. **Archetype** — UI, system, or lifecycle/shared (see AGENTS.md).
2. **Persona / scope** — employee, manager, admin, support.
3. **Read-only vs mutation** — mutations require confirmation card + cancel path.
4. **Trigger style** — `triggerQueries` (deterministic) and/or `modelDescription` (LLM-routed). Trigger phrases must include the object/action.
5. **Inputs and source** — for each input, decide source: LLM (`AutomaticTaskInput` with `entity` + `description`), caller (`ManualTaskInput`), `Global.*`, `Env.*`, or `System.*`. Mark required-but-not-inferable inputs `shouldPromptUser: true`.
6. **Outputs** — populate `outputType.properties` if the topic returns data.
7. **Downstream calls** — list child topics (`BeginDialog`), flows (`InvokeFlowAction`), and any sibling XML/template-config dependencies in the topic folder.
8. **Five UX states** — success-with-data, success-with-no-data, validation failure, downstream error, user cancel. Each must have an explicit branch.
9. **Author** by mirroring the nearest sibling — same top-level keys, same XML root element, same file layout.
10. **Validate** via `validate-sample-topic` before preparing the PR.

If any step lacks information, **stop and ask**.

## Modify-topic rules

- Read the topic file before editing.
- Make the smallest safe change. No opportunistic refactors.
- Preserve action `id:` values, action ordering, and `ConditionGroup` branches not targeted by the change.
- Do not rename or remove existing `inputs`. Do not rename or retype existing `inputType` / `outputType` properties — add new properties instead.
- New variables go under `Topic.*` unless cross-topic persistence requires `Global.*` or environment config requires `Env.*`.
- Do not reformat unrelated YAML/XML.

## Bug-fix tracing

Required from the issue: current behavior, expected behavior, repro/transcript if available, target topic path. If any is missing, stop and ask.

When fixing:

1. **Trace the `actions` list** before editing — walk the path the bug takes and record it. The trace goes into the PR description.
2. **Make the minimal safe change.** No surrounding cleanup.
3. **Schema/parsing bugs** — confirm the upstream response shape before changing a `ParseValue` schema.
4. **Power Fx bugs** — prefer adding an `IsBlank` or `IsBlankOrError` guard over rewriting the expression.
5. **Missing-branch bugs** — add or update an explicit `ConditionGroup` branch rather than restructuring.

## Outputs

- A working tree ready for `validate-sample-topic`.
- The neighbor reference path, for the PR body.
- For bug fixes, the `actions` trace, for the PR body.

## Stop conditions

- Stop if no suitable neighbor exists (e.g., first topic in a new area). Post a comment on the triggering GitHub issue or PR that names the missing neighbor and tags the repository maintainers listed in `CODEOWNERS`, then wait for their reply before continuing.
- Stop if the change would require touching more than one topic folder.
- Stop if any required information from the new-topic checklist or bug-fix list is missing.

