# Repo-root Copilot instructions

If GitHub Copilot is reading this file, the user has opened the **top-level repo folder** (`Employee-Self-Service-Agent-Developer-Kit/`) as their VS Code workspace root.

This repo is a **monorepo of solutions**. The actual tooling for each solution — slash-commands, agent personas, Python scripts — lives inside individual solution folders under `solutions/` (today the canonical one is `solutions/ess-maker-skills/`; more may be added over time), NOT at this repo root. Slash-commands typed against the repo root will not resolve to any prompt and Copilot Chat will treat them as plain text.

## Do not load nested solution-level instructions from here

Even when responding to a normal coding request at the repo root, do **not** read or follow `solutions/ess-maker-skills/.github/copilot-instructions.md` (or the equivalent file in any future sibling solution). Those files expect to be the active workspace's instructions and contain setup gates that misfire when loaded out of context (e.g. they will force-trigger a "run `/setup`" welcome message even when the user is just editing a CI workflow at the repo root). Treat solution-level instruction files as opaque from this workspace.

## Default behavior

For everything that isn't an attempt to use the kit (general questions, code exploration, README lookups, "what is this repo?", build/test help on the repo's Python scripts, etc.) **behave normally**. You are a general-purpose coding assistant working in a monorepo. Help the user with whatever they're actually asking about — there is no kit persona to load here and no setup gate to enforce.

## When to fire the "wrong folder" redirect

**Only** show the redirect message below when the user is clearly trying to invoke the ESS Maker Kit and will be blocked by the wrong-folder problem. Concretely, fire the redirect if either of the following is true:

1. **Explicit kit slash-command.** The user's message starts with (or is exactly) one of the kit's slash-commands:
   - `/setup`
   - `/create`
   - `/connect`
   - `/delete`
   - `/evaluate`
   - `/scan`
   - `/update`
   - `/push`
   - `/menu`
   - `/troubleshoot`
   - `/flightcheck`

2. **Intent hint — natural-language equivalent.** The user isn't typing a slash-command but is unambiguously asking to *run* the kit from this workspace. Examples:
   - "How do I set up the kit?" / "How do I run setup?" / "Start the ESS Maker Kit"
   - "Run flightcheck" / "Run the readiness check on my agent"
   - "Create a topic" / "Connect ServiceNow" / "Scan my agent for errors" — when phrased as a request to *do it now* in this workspace, not as a general "how does this work?" question.

   When in doubt, prefer the default behavior (answer normally) over firing the redirect. A user asking "what does /flightcheck do?" is asking a documentation question — answer it from the README and `solutions/ess-maker-skills/` files; do **not** redirect.

## The redirect message

When (and only when) the trigger conditions above are met, respond with **only** this message and nothing else:

> Hey! It looks like you opened the top-level repo folder in VS Code, but the kit's slash-commands live inside a specific solution folder.
>
> **To use the ESS Maker Kit:**
>
> 1. Click `File` → `Open Folder…` (or press `Ctrl+K Ctrl+O`)
> 2. Navigate **inside** this folder, then **into** `solutions`, and select `ess-maker-skills`
> 3. Click `Select Folder`
> 4. VS Code will reopen with the kit loaded
> 5. Type `/setup` again — it will work this time
>
> See the [README](README.md) for the full getting-started walkthrough.
>
> Just looking for example topics to copy rather than the runnable kit? Browse the `samples/` folder at the repo root. That's reference content (topics, prompts, sample data), not a slash-command workspace.

When firing the redirect, do not also try to execute the user's request from this folder — the kit persona, skills, and scripts are not loaded here, so any attempt would run against the wrong workspace.

If the user explicitly asks "why doesn't this work?" or "what is this repo?", you may briefly explain that this is a monorepo and direct them to open the solution folder, then include the steps above.
