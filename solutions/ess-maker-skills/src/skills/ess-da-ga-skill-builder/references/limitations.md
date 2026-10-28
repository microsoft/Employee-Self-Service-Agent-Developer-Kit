# Agent skill limitations

A live record of what declarative agents (DA GA) in Microsoft 365 Copilot support for agent skills, and what testing has shown about how Copilot uses them. Kit maintainers add, change and remove entries as the platform changes.

Last reviewed: 2026-10-27.

## Contents

- How to use this record
- Status values
- Packaging and size
- Files and scripts
- Runtime behavior
- Tenant and publishing
- Agent Skills specification
- Unverified
- Changelog
- How to update this record

## How to use this record

- Start with Microsoft documentation for the target host's capabilities, limits, packaging and documented behavior. Apply Agent Skills format and portable conventions within those constraints; use Anthropic and OpenAI guides only for applicable authoring techniques. `sources.md` records the source order and host scope.
- **Plan** within these limits in Round 3 (skill count, what a skill can do without network access), and **draft** within them in Round 7.
- **Answer** the maker's questions from this file. Give the limit, where it applies and its status. **All** means declarative agents, whether built in Agent Builder or with the Agents Toolkit; **Copilot Studio** means Copilot Studio agents built with the GitHub Copilot harness. The validator applies the Copilot Studio load checks to every skill, since they cost nothing elsewhere. For a **Documented** entry, link its source. For an **Observed** entry, say it comes from testing and can change without notice.
- When the question isn't covered here, say so, don't guess, and point the maker to the closest source. Record the question in `plan.md` under **Decisions** so maintainers can add it.
- Don't edit this file while building a skill; it's maintained in the kit.

## Status values

| Status     | Meaning                                                                                         |
| ---------- | ----------------------------------------------------------------------------------------------- |
| Documented | Microsoft documentation states it.                                                              |
| Spec       | Agent Skills format and portable conventions, applied within the target host's documented constraints. |
| Observed   | Seen in ESS testing with Microsoft 365 Copilot; not a documented platform guarantee, and can change. |
| Unverified | An open question; tell the maker it's unknown.                                                  |

## Packaging and size

| ID    | Limit                                                                                                                                               | Applies to     | Status     | Source         | Enforced by                     |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- | ---------- | -------------- | ------------------------------- |
| PK-01 | Up to 8 skills per agent.                                                                                                                           | All            | Documented | [DA skills][1] | Validator with `--package`      |
| PK-02 | `SKILL.md` instructions must be under 20,000 characters.                                                                                            | All            | Documented | [DA skills][1] | Validator                       |
| PK-03 | Maximum directory depth 3: `skills/<name>/<folder>/file`. A skill's own folders can't contain subfolders.                                           | All            | Documented | [DA skills][1] | Validator                       |
| PK-04 | Up to 350 files across all of an agent's skills.                                                                                                    | All            | Documented | [DA skills][1] | Validator with `--package`      |
| PK-05 | Upload the complete skill as a `.zip` of up to 50 MB, with `SKILL.md` at its root. `SKILL.md` alone isn't accepted.                                 | Agent Builder  | Documented | [Builder][2]   | Packager                        |
| PK-06 | Each file in the package can be up to 25 MB.                                                                                                        | Agent Builder  | Documented | [DA skills][1] | Packager                        |
| PK-07 | Add a skill as a folder (a `.zip` isn't supported); the whole app package is limited to 10 MB.                                                      | Agents Toolkit | Documented | [Toolkit][3]   | Not enforced                    |
| PK-08 | Skills need declarative agent manifest version 1.9.                                                                                                 | Agents Toolkit | Documented | [Toolkit][3]   | Not enforced                    |
| PK-09 | `atk add skill` works only when the `TEAMSFX_AGENT_SKILLS` environment variable is `true`; otherwise the CLI reports `skill` as an unknown command. | Agents Toolkit | Documented | [Toolkit][3]   | Not enforced                    |
| PK-10 | A skill can't be shared between agents; add a copy to each agent.                                                                                   | All            | Documented | [DA skills][1] | Not enforced                    |
| PK-11 | Upload either a `SKILL.md` file or a `.zip` that contains one. A skill that fails a load check is skipped while the rest of the agent loads.        | Copilot Studio | Documented | [Studio][4]    | Validator                       |
| PK-12 | Skill names must be unique within an agent.                                                                                                         | Copilot Studio | Documented | [Studio][4]    | Validator (name matches folder) |

## Files and scripts

| ID    | Limit                                                                                                                                                                                                                                                                                | Applies to     | Status     | Source         | Enforced by                                     |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------- | ---------- | -------------- | ----------------------------------------------- |
| FS-01 | Resource files can be `.json`, `.xml`, `.yaml`, `.yml`, `.ini`, `.config`, `.utf8`, `.docx`, `.doc`, `.docm`, `.pdf`, `.txt`, `.rtf`, `.md`, `.ppt`, `.pptx`, `.ppsm`, `.xlsx`, `.xls`, `.xlsm`, `.csv`, `.tsv`, `.html`, `.htm`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp` or `.log`. | All            | Documented | [DA skills][1] | Validator                                       |
| FS-02 | Scripts can be `.py`, `.js`, `.mjs`, `.cjs`, `.ts`, `.mts`, `.sh` or `.bash`.                                                                                                                                                                                                        | All            | Documented | [DA skills][1] | Validator                                       |
| FS-03 | Scripts run in a sandbox with no internet or network access.                                                                                                                                                                                                                         | All            | Documented | [DA skills][1] | Validator (network imports and commands)        |
| FS-04 | Scripts can't install packages. They may use packages already in the sandbox, but shouldn't depend on one whose availability isn't confirmed; in practice, use the standard library only.                                                                                            | All            | Documented | [DA skills][1] | Validator (installs; non-standard imports warn) |
| FS-05 | Scripts can't make authenticated network calls.                                                                                                                                                                                                                                      | All            | Documented | [DA skills][1] | Validator                                       |
| FS-06 | Scripts can't call connectors, API plugins or MCP servers. Only the agent can use them, through the orchestrator.                                                                                                                                                                    | All            | Documented | [DA skills][1] | Builder guidance                                |
| FS-07 | `SKILL.md` must be UTF-8 without a byte-order mark, and its front matter must be valid YAML: quote a value that contains a colon followed by a space.                                                                                                                                | Copilot Studio | Documented | [Studio][4]    | Validator                                       |
| FS-08 | Sensitivity labels on skill files are kept and honored; user-defined permissions and Double Key Encryption aren't supported.                                                                                                                                                         | All            | Documented | [DA skills][1] | Not enforced                                    |
| FS-09 | Uploaded skill files are stored in tenant-scoped SharePoint Embedded containers.                                                                                                                                                                                                     | All            | Documented | [DA skills][1] | Not enforced                                    |

## Runtime behavior

| ID    | Limit                                                                                                                                                                                       | Applies to     | Status     | Source          | Enforced by                  |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- | ---------- | --------------- | ---------------------------- |
| RT-01 | Only each skill's name and description are in the model's context; the rest loads when the task needs it.                                                                                   | All            | Documented | [DA skills][1]  | Builder guidance             |
| RT-02 | The model reads a skill only when it decides to, and in testing often answered without reading it. Anything that must always hold belongs in a tool description or the tool's code as well. | All            | Observed   | Kit testing     | Builder guidance             |
| RT-03 | Reference files are read even less often than `SKILL.md`, so nothing essential lives only in a reference file.                                                                              | All            | Observed   | Kit testing     | Builder guidance             |
| RT-04 | Starting a description with "Read this skill before …" didn't make the model read skills more often.                                                                                        | All            | Observed   | Kit testing     | Validator warning            |
| RT-05 | Instructions to the model inside a tool's result made Copilot's content filter refuse the whole answer.                                                                                     | All            | Observed   | Kit testing     | Builder guidance             |
| RT-06 | The skill-loading step isn't always shown in chat; its absence doesn't mean the skill wasn't read. Check the debug export.                                                                  | All            | Observed   | Kit testing     | Builder guidance             |
| RT-07 | A skill can't load another skill. It can name one, and the model decides whether to read it.                                                                                                | All            | Observed   | Kit testing     | Builder guidance             |
| RT-08 | Copilot reads MCP tool descriptions from the tool file packaged with the agent, so a changed description takes effect only after the package is updated.                                    | All            | Observed   | Kit testing     | Not enforced                 |
| RT-09 | Agent instructions are limited to 8,000 characters; skills don't count toward it.                                                                                                           | All            | Documented | [DA skills][1]  | Not enforced                 |
| RT-10 | A skill whose description is too long for the model-facing catalog is skipped at load time.                                                                                                 | Copilot Studio | Documented | [Studio][4]     | Validator (1,024 characters) |
| RT-11 | Copilot runs a plugin function marked `isNonConsequential` without asking the user, so the skill's confirmation or form is the only safeguard.                                              | All            | Documented | [Plugin 2.4][5] | Validator note               |

## Tenant and publishing

| ID    | Limit                                                                                                                                           | Applies to    | Status     | Source         | Enforced by  |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------- | ---------- | -------------- | ------------ |
| TP-01 | In tenants with Microsoft Purview Information Barriers, admins can deploy agents with skills, but users can't add skills to agents they create. | All           | Documented | [DA skills][1] | Not enforced |
| TP-02 | ISVs can't publish declarative agents with skills through Partner Center yet.                                                                   | All           | Documented | [DA skills][1] | Not enforced |
| TP-03 | Adding skills in Agent Builder needs a qualifying Microsoft 365 Copilot license or pay-as-you-go access.                                        | Agent Builder | Documented | [Builder][2]   | Not enforced |

## Agent Skills specification

| ID    | Limit                                                                                       | Applies to | Status | Source    | Enforced by       |
| ----- | ------------------------------------------------------------------------------------------- | ---------- | ------ | --------- | ----------------- |
| SP-01 | `name`: 1 to 64 lowercase letters, digits and single hyphens, identical to the folder name. | All        | Spec   | [Spec][6] | Validator         |
| SP-02 | `description`: required, up to 1,024 characters, no XML tags.                               | All        | Spec   | [Spec][6] | Validator         |
| SP-03 | `SKILL.md` under 500 lines; about 5,000 tokens or fewer recommended.                        | All        | Spec   | [Spec][6] | Validator         |
| SP-04 | Reference files one level deep from `SKILL.md`.                                             | All        | Spec   | [Spec][6] | Validator warning |

## Unverified

| ID    | Question                                                                                         | Status     |
| ----- | ------------------------------------------------------------------------------------------------ | ---------- |
| UV-01 | Which packages are preinstalled in the script sandbox.                                           | Unverified |
| UV-02 | Whether skill scripts run in an agent that doesn't have the Code Interpreter capability enabled. | Unverified |
| UV-03 | The description length Copilot's catalog accepts, beyond the specification's 1,024 characters.   | Unverified |

## Changelog

| Date       | Change          |
| ---------- | --------------- |
| 2026-10-28 | Clarified source precedence and evidence labels; platform limits not re-reviewed. |
| 2026-10-27 | Initial record. |

## How to update this record

1. Add or edit the row in the right section. Keep IDs stable and never reuse one; when a limit is lifted, delete its row and note the removal in the changelog.
2. Set the status and the source. An Observed entry says what was seen, not what the platform guarantees. Promote it to Documented only with an applicable Microsoft documentation source. If documentation and testing disagree, record the discrepancy rather than silently changing the contract.
3. Update **Last reviewed** and add a changelog row.
4. When a script enforces the limit, change its constant in `scripts/ess-da-ga-skill-builder/skill_builder_validate.py` or `scripts/ess-da-ga-skill-builder/skill_builder_package.py` in the same change. `tests/scripts/test_skill_builder.py` fails when this record and the scripts disagree.

[1]: https://learn.microsoft.com/microsoft-365/copilot/extensibility/declarative-agent-skills
[2]: https://learn.microsoft.com/microsoft-365/copilot/extensibility/agent-builder-add-skills
[3]: https://learn.microsoft.com/microsoft-365/copilot/extensibility/build-declarative-agents-add-custom-skills
[4]: https://learn.microsoft.com/microsoft-copilot-studio/agents-experience/skills-add-existing
[5]: https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-manifest-2.4
[6]: https://agentskills.io/specification
