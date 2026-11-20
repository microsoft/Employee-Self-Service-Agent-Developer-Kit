---
name: workday-oss-import
description: Deterministically install selected Workday OSS employee or manager scenario topics into an existing configured DA agent through an authenticated Copilot Studio browser session.
---

# Import Workday OSS topics

Install the reviewed Workday OSS sample topics into the active editable DA
agent. This is a bounded native-agent operation:

- source is only `samples/Workday`;
- employee topics follow `samples/Workday/Employee/README.md`;
- manager topics follow `samples/Workday/Manager/README.md`;
- existing topics are preserved when either `displayName` or `schemaName`
  matches;
- only missing `DialogComponent` topics are created;
- no topic is updated, deleted, published, activated, or runtime-tested;
- no Computer Use automation is allowed.

The target must already have its Workday template configurations initialized.
This command installs only the 16 Employee and Manager scenario topics.
`--display-prefix` can add a reviewed prefix to created topic display names
without changing schema names.

The installer uses the Microsoft Object Model converter and the live MinimalBot
components request contract observed from an authenticated Copilot Studio page.
It does not send raw YAML to the API.

## Runtime prerequisite

Use a local Edge or Chromium browser that was launched with a CDP port and is
already signed into the selected agent in Copilot Studio. Supported exact-agent
routes are **Details**, **Overview**, **Tools**, and the adaptive topic editor.
Both `copilotstudio.microsoft.com` and
`copilotstudio.preview.microsoft.com` are supported. Use an InPrivate window
and a fresh, dedicated browser data directory. Close the browser and remove
that temporary directory after the operation.

Example Edge launch:

```powershell
msedge --inprivate --remote-debugging-port=9222 `
  --user-data-dir="$env:TEMP\ess-adk-oss-cdp" `
  --no-first-run --no-default-browser-check `
  "https://copilotstudio.microsoft.com/"
```

The installer reloads the selected safe agent page once to observe that page's
own authenticated MinimalBot components request. Do not leave unsaved edits in
the tab. The installer keeps the captured authorization header and browser
cookies in memory only. It never writes a token cache, browser storage state,
cookies, request headers, HAR, or request body to disk.

Install `scripts/requirements.txt` before running. Playwright attaches to the
existing browser; it does not need to download or launch a browser.

If CDP or the authenticated page is unavailable, use the safe local fallback:

```powershell
python scripts/install_oss_topics.py --all --offline-plan
```

The offline plan validates source order and hashes only. It does not validate a
target, inspect duplicates or dependencies, run Object Model conversion, or
claim that anything can be installed.

## Step 1: Resolve scope

Read `.local/config.json` and resolve `activeAgent`. Require:

- an environment GUID;
- an agent/bot GUID;
- an agent schema name;
- an environment-specific `powerPlatformApiEndpoint`;
- the endpoint-encoded environment GUID to match the configured environment.

Ask whether to install all scenarios or an explicit subset. Never infer all
from "OSS".

For all 16 scenarios:

```powershell
python scripts/install_oss_topics.py --all --dry-run
```

For a subset:

```powershell
python scripts/install_oss_topics.py `
  --topics WorkdayGetEducation EmployeeGetVacationBalance `
  --dry-run
```

To prefix scenario display names:

```powershell
python scripts/install_oss_topics.py --all `
  --display-prefix "Workday OSS " --dry-run
```

If more than one safe Copilot Studio agent tab is open, add
`--page-url-contains <agent-or-environment-id>` to disambiguate. Do not use a
different account, environment, agent, ring, host, or API path to work around a
401, 403, missing page, or identity mismatch.

## Step 2: Review the dry-run

The dry-run must complete before any write. It:

1. captures the exact components URL and API version used by the authenticated
   safe exact-agent page;
2. reads the live MinimalBot component inventory and validates bot ID/schema;
3. resolves every `BeginDialog` dependency to exactly one existing target
   schema;
4. substitutes the configured Workday tenant where a sample contains
   `<TENANT_NAME>`;
5. converts YAML to Object Model JSON and round-trips it through the same
   Microsoft serializer used by Copilot Studio authoring;
6. reports each topic as `preserved` or `would-create`.

Show the deterministic JSON summary. Stop on any missing dependency, ambiguous
display/schema identity, conversion failure, target mismatch, 401/403, or
blocking diagnostic. Do not offer to overwrite an existing topic.

## Step 3: Confirm the exact write

Before applying, show:

- environment ID, agent ID, agent schema, and ring;
- every `would-create` topic in manifest order;
- every preserved topic and its duplicate reason;
- that creation is sequential and stops on the first failed verification;
- that this does not publish or test the agent.

Ask:

> Create exactly these missing Workday OSS topics in the selected agent?

Proceed only after an explicit yes for that exact dry-run.

## Step 4: Apply and verify

Run the same selection with `--apply`:

```powershell
python scripts/install_oss_topics.py --all --apply
```

The installer creates one topic per PUT using a fresh `changeToken`,
`$kind: BotComponentInsert`, `$kind: DialogComponent`, and a deterministic
component UUID derived from agent ID plus schema name. After each PUT it
requires:

- write-response identity for the new component;
- one exact component ID/schema/display name on read-back;
- `Active` state and status;
- canonical Object Model content matching the converted source;
- no blocking diagnostics.

If the write response is lost, the installer reads back the deterministic ID
once. It never automatically replays an indeterminate creation. A stale token,
identity drift, ambiguous result, auth failure, or failed diagnostic stops the
remaining imports and returns nonzero.

## Step 5: Report

Report the JSON status accurately:

- `completed`: every selected topic was created and verified or preserved;
- `dry-run`: no writes were attempted;
- `offline-plan`: no target assertions were made;
- `failed`: stop at the reported boundary; do not claim rollback or retry.

List created and preserved topics separately. Remind the maker that Workday
template configurations must already be initialized before these scenarios
execute. Publishing and fresh-conversation runtime testing remain separate
approved actions.

## Telemetry

Capability telemetry is deliberately deferred for this first bounded
installer. The deterministic JSON result is local command output only and must
not include credentials, cookies, authorization headers, employee data, or
topic XML values.
