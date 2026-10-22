<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Add a SharePoint library

This branch contains a targeted workaround for a native ESS DA GA knowledge
picker that returns **No results** for a library-root URL. This adds a source,
not a platform/UI code fix. Do not use general `/push`, package replacement,
Dataverse updates, browser developer tools, or ad hoc HTTP requests.

## 1. Check setup and collect the URL

Read `.local/config.json` and `.local/setup/config.json`. Require canonical
schema version 4 and exactly one entry whose `agent.workspace_slug` equals the
local `activeAgent`. The entry must have `workspace.folder`,
`workspace.agent_path` and `steps.SETUP-07.state: done`; the selected local bot
ID must match the canonical agent ID. The agent must be native DA GA, not a
Dataverse/DA Preview/CEA agent. If these requirements are not met, ask the maker
to run `/setup` for their **existing agent**, then stop. Do not create a new
agent to work around missing setup. Unrelated connector readiness is not required.

Ask for the full library-root URL unless it was already supplied. Examples:
`https://contoso.sharepoint.com/sites/HR/SitePages/` or
`https://contoso.sharepoint.com/sites/HR/Shared%20Documents/`.
Use the library's direct URL, not a sharing link, view (`Forms/AllItems.aspx`),
individual page, site root, subweb, or subfolder. Do not broaden to the site
root if the library is rejected.

## 2. Preview without writing

From the Maker Kit workspace, using its installed Python environment, run:

```text
python scripts/add_sharepoint_library.py --library-url "<library URL>"
```

Pass arguments as literal values using the terminal's quoting rules; never
interpolate a maker's URL as executable shell text. In PowerShell, use
single-quoted arguments and double any embedded single quote. Reuse the authenticated
maker account; pass `--account "<maker sign-in>"` when it is known from setup.
Let the script use the shared sign-in cache and interactive authentication if
needed. Never ask the maker to copy a bearer token.

The default mode only reads. Show the returned agent name/ID, environment,
ring, library URL and the proposed one-source addition. If the source already
exists, report that no change was needed and continue to validation, without
inserting a duplicate. Do not claim that an existing source was added by this run.
If the script fails, show its diagnostic and stop; do not fall back to general
push, replay a backup, remove existing sources, or alter permissions.

## 3. Confirm, then apply the scoped change

Use the available user-question tool to ask:

> Add this SharePoint library to the agent shown above? Existing sources and
> other components will be preserved. This will not publish the agent.

Offer **Add library** and **Cancel**, initially unselected. Wait for an explicit
Add library response. Cancellation or an unclear answer does not authorize a write.
After confirmation, run the same script with the exact target IDs from preview:

```text
python scripts/add_sharepoint_library.py --library-url "<library URL>" --apply --yes --expected-agent-id "<preview agent ID>" --expected-environment-id "<preview environment ID>"
```

Preserve the account argument when used in preview. The script reads a fresh
change token, writes a local backup, inserts exactly one knowledge component,
and verifies the URL and preservation of every existing component. It does not
replace the agent or publish. A conflict, timeout or verification failure is
not success: report it, retain the backup, and run a new read-only preview
before any separately confirmed retry. Do not automatically restore the backup.

## 4. Validate and keep publishing separate

After successful readback, report the library URL, source ID and local backup
path. State **Added and verified; agent not published**.

Ask the maker to refresh Copilot Studio and test a question about a known page
or document in this library. Check the answer and its citation with the maker.
An in-library citation alone does not prove that all out-of-library content is
excluded. Do not claim customer retrieval success without the maker's test.

Only if the maker separately requests publication, follow the existing
`/publish` skill and its confirmation. Publishing can release other pending
changes, so it is deliberately not part of this command.
