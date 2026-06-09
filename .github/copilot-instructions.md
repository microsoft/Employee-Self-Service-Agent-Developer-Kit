# You opened the wrong folder

If GitHub Copilot is reading this file, the user has opened the **top-level repo folder** (`Employee-Self-Service-Agent-Developer-Kit/`) as their VS Code workspace root.

This repo is a **monorepo of solutions**. The actual tooling — slash-commands like `/setup`, `/flightcheck`, the agent persona, the Python scripts — lives inside individual solution folders under `solutions/`, NOT at this repo root.

## Your only job for this conversation

If the user says ANYTHING — `/setup`, `hello`, `help`, "what can you do", or anything else — respond with ONLY this exact message and nothing else:

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

Do not greet the user with anything else. Do not list capabilities. Do not try to help with their actual request from this folder — you cannot, the kit is not loaded here. Do not load any other instruction files. Do not run any tools. Just show the message above and stop.

If the user explicitly asks "why doesn't this work?" or "what is this repo?", you may briefly explain that this is a monorepo and direct them to open the solution folder, but always end by repeating the steps above.
