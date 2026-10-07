# Repo-root Copilot instructions

## Discover Maker Kit operations

At the beginning of each conversation:

1. List the `*.prompt.md` files under `.github/prompts/`.
2. When that path contains no prompt files, list the `*.prompt.md` files under
   `solutions/ess-maker-skills/.github/prompts/`.

Classify the catalog location from those results:

- Prompt files under `.github/prompts/` represent an active Maker Kit workspace.
- Prompt files found only under
  `solutions/ess-maker-skills/.github/prompts/` represent a nested Maker Kit
  workspace.
- No prompt files at either path means the Maker Kit operation catalog is
  unavailable from the current folder.

Use the discovered prompt filenames to match direct commands and natural-language
operation intent. When a filename provides a clear match, route from the catalog
location. When the match remains unclear, read the `description` frontmatter
field from likely candidate prompts and then route.

Requests whose target is repository source, tests, documentation, or tooling
follow the repository-development workflow.

For a request that matches a discovered Maker Kit operation:

- In an active Maker Kit workspace, continue with the applicable prompt and skill
  instructions.
- In a nested Maker Kit workspace, provide the folder-selection guidance.

When the operation catalog is unavailable and the user explicitly names the ESS
Maker Kit, provide the folder-selection guidance.

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
