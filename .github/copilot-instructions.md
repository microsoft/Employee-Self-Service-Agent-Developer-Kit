# Repo-root Copilot instructions

## Discover Maker Kit operations

At the beginning of each conversation, check whether both of these nested Maker
Kit paths are available:

- `solutions/ess-maker-skills/.github/prompts/` contains at least one
  `*.prompt.md` file.
- `solutions/ess-maker-skills/src/skills/` exists.

When that pair is unavailable, do not apply the Maker Kit folder-routing
instructions below. Route the request as normal.

When that pair is available:

- When the request begins with `/`, derive its prompt filename from the command
  name. For example, `/flightcheck` maps to `flightcheck.prompt.md`. Check that
  candidate directly in the nested prompt catalog.
- For natural-language requests, or when the direct command candidate does not
  exist, list the prompt filenames in the nested catalog and use them to match
  the operation intent.
- When the filename match remains unclear, read the `description` frontmatter
  field from likely candidate prompts.
- Provide the folder-selection guidance when the request matches a discovered
  Maker Kit operation.
- Also provide the folder-selection guidance when the user explicitly asks to
  use, open, or run the ESS Maker Kit as a maker experience.

## Folder-selection guidance

When folder-selection guidance applies, respond with only:

> ESS Maker Kit agent operations are available from the
> `solutions/ess-maker-skills` workspace.
>
> **Open the Maker Kit workspace:**
>
> 1. In VS Code, select `File` → `Open Folder…` or press `Ctrl+K Ctrl+O`.
> 2. Select `solutions/ess-maker-skills`.
> 3. Click `Select Folder`.
> 4. After VS Code reopens, enter the request again.

Route every request not covered above as normal.
