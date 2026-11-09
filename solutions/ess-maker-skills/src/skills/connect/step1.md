# Choose an integration

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not narrate tools, files, or internal routing.

## 1.1 - Discover registrations

Read `src/skills/connect/*/integration.json` from immediate child directories.
Each registration supplies:

- `id`: a unique lowercase identifier containing only letters, digits, and
  hyphens, starting with a letter, matching its directory name.
- `displayName`, `description`, and `aliases`: menu text and selection names.
- `availability`: exactly `available` or `unavailable`.
- `entryDoc`: required when available, a relative Markdown path within the
  same provider directory.
- `statusDoc`: optional when available, a relative Markdown path within the
  same provider directory for read-only, active-agent connection status.
- `unavailableMessage`: required when unavailable, the exact message to show.

Reject malformed registrations, duplicate identifiers or selection names across
providers, invalid availability, missing required fields, and missing or unsafe
document paths. Never follow absolute paths or `..` segments, or silently guess
a default. A directory without a registration is not a guided integration.

If registrations cannot be loaded safely:

**Message:**

I can't load the integration options because the local integration
configuration is incomplete or conflicting. No connection changes were made.
Restore the integration configuration before trying again.

**End message.**

Stop. Do not run provider actions.

## 1.2 - Resolve a selection or show the menu

Use the current explicit request or `PRE_SELECTED_INTEGRATION` before any
earlier conversation selection. Match the named provider to a registration's
ID, display name, or aliases, case-insensitively. Use an established conversation
selection only when the current request does not select a different provider.
An ambiguous or unknown selection must not select a provider.
If there is one exact provider match, go directly to 1.3 without asking.

Otherwise, build the menu from `available` registrations only, sorted by
`displayName`. Number each row as `{number}. **{displayName}** - {description}`.
Keep this number-to-provider mapping for the user's response.

If none are available:

**Message:**

No guided integrations are available in this installation.
Please contact your administrator.

**End message.**

Stop without running provider actions.

For available providers that define `statusDoc`, follow only that document's
local, read-only status instructions. Status lookup must not authenticate,
contact services, or mutate state. Do not inspect unavailable providers' state.
Show a connected name only when its status document returns `CONNECTED = true`;
an unknown or failed status lookup is not a successful connection. If a status
lookup errors, show:

**Message:**

I couldn't determine the current connection status for {provider display name}.
No connection state was changed.

**End message.**

Do not claim the provider is disconnected. Continue with integration selection.

If any providers are connected, show:

**Message:**

Currently connected: {connected provider display names}

**End message.**

Then show:

**Message:**

Which system do you want to connect to your agent?

{numbered available-integration menu}

**End message.**

Wait for the user. Resolve their number against the displayed mapping, or match
their text against all registrations, including unavailable ones. On an unknown
or ambiguous response, show:

**Message:**

I couldn't identify that integration. Choose a number from the list or enter
the integration's name.

**End message.**

Wait for the user and try again. Never fall back to a provider automatically.

## 1.3 - Apply availability, then dispatch

Recheck the selected registration's availability on every selection and resume.
For `unavailable`, show `unavailableMessage` verbatim and STOP before provider
state, credentials, telemetry, MCP, or retained steps. Do not load `entryDoc`,
`statusDoc`, or any old setup procedure for that provider.

**Message:**

{unavailableMessage}

**End message.**

Stop after that message for an unavailable provider.

For `available`, set `INTEGRATION_ID` to the validated registration ID. Record
anonymous usage telemetry attributed to that selected provider:

```text
python scripts/emit_capability.py connect --connector "{INTEGRATION_ID}"
```

Telemetry is best-effort and non-blocking; do not narrate it or fail the
connection because of a telemetry error.

Read the selected provider directory's `entryDoc` and follow it with the
original request and target intent intact. Only that entry point decides
supported agents, authentication, readiness, state, and lifecycle progress.
