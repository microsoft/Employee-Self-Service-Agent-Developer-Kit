---
name: org-announcements
description: >-
  Create, edit, republish, and manage announcements for a deployed ESS agent
  through the Org Announcements MCP server. Use for announcements, org
  announcements, bulletins, alerts, announcement audiences, archiving or
  republishing an announcement, and any call to the ess-org-announcements
  MCP server.
---

# Org Announcements

Orchestrate organization announcements through the Org Announcements MCP
server. Open the right view once, let the widget own the editing session, and
never claim a save the tools did not return.

## Tenant-and-agent scope

Org Announcements belong to **one deployed ESS agent in the authenticated
tenant**, selected by its required `titleId`. They are not shared across every
agent. `titleId` is an agent identifier, not an author permission, a Dataverse
`botId`, or a Graph audience group. Tenant identity comes only from the
authoring sign-in; never supply `tenantId` to a tool.

The 100-current-item limit and latest-50 archived window apply separately to
each tenant-and-agent pair. There is no migration or tenant-wide fallback.
Tell the maker which selected agent they are managing:

> These announcements belong to **{agent name}**. Their selected audiences apply
> within that agent, not across your other ESS agents.

## Setup-state check

For every request that reads or authors an announcement, read
`.local/config.json` before calling any MCP tool.

If the file does not exist, or its `setup` value is not `"complete"`, show:

> Welcome to the ESS Maker Kit. Before using `/org-announcements`, type `/setup` to set up your environment.

and STOP.

Requests that only ask what announcements are, or what this skill can do, do not
require local setup. Answer them directly.

## MCP availability check

Before any request that requires an announcement tool, inspect the tools
available in the current conversation for the `ess-org-announcements` server.

When its tools are available, continue to **Resolve the target**.

When its tools are unavailable:

1. Run:

   ```text
   python scripts/mcp_config.py validate --server ess-org-announcements
   ```

2. Parse `MCP_CONFIG_STATUS_JSON:`:
   - `configured`: follow **Start the announcements MCP server**.
   - `missing-file` or `missing-server`: run:

     ```text
     python scripts/mcp_config.py materialize-defaults
     ```

     Parse `MCP_CONFIG_RESULT_JSON:` and confirm `ess-org-announcements`
     appears in `addedServers`, or run `validate` again and confirm its status
     is `configured`. Then follow **Start the announcements MCP server**.
   - command failure or any other result: show the exact error and stop. Do not
     replace malformed JSON or overwrite an existing configuration.

### Start the announcements MCP server

Show:

> The announcements server is configured, but its tools are not available in
> this chat yet.
>
> 1. Press `Ctrl+Shift+P`.
> 2. Run `MCP: List Servers`.
> 3. Select `ess-org-announcements`.
> 4. Choose `Start`.
>
> Type `done` when the server shows `Running`.

Wait for the maker. When they confirm, inspect the available tools again. If the
tools are available, continue the original request. If they remain unavailable,
tell the maker to reload the VS Code window, rerun `/org-announcements`, and
stop.

## Resolve the target

Reuse the setup configuration already loaded. Do not guess an identifier or
use announcement content to decide which agent owns it.

1. Select the active agent from the backward-compatible `agent` object. For
   another configured agent, match an `agents` entry by `slug`, `botId`, or
   unambiguous `name`.
2. Use the maker's explicit `titleId`, otherwise the selected entry's stored
   `titleId`. A verified target can be reused for this conversation; do not
   force `get_agent_config` before each opener.
3. If the title is missing, use this provider's read-only discovery tools:
   `list_agent_configs`, then `search_agents` with a distinctive agent-name
   substring when the list has no unambiguous match. These discover deployed,
   tenant-visible agents; a `botId` is never a substitute for `titleId`.
   Both tools belong to `ess-org-announcements`. No landing-page MCP process
   is needed; follow this skill's availability check if they are unavailable.
4. Ask the maker to choose among ambiguous candidates. If no candidate matches,
   stop and ask them to confirm the agent name and have the published agent
   approved and deployed to the organization. Never fall back to tenant-wide
   announcements.
5. Persist a discovered, verified `titleId` using the existing local-agent
   convention: reread the complete config, find the selected `agents` entry by
   `botId` then `slug` (name only if unambiguous), and change only its `titleId`.
   If the active agent exists only as `agent`, copy that complete object into
   `agents` first. Also update `agent.titleId` when the target matches
   `activeAgent` or the active object's botId/slug. Preserve all other fields
   and agents. Reread to verify both copies before calling another tool.
   With no matching local entry, use the discovered title for this request
   without fabricating a partial local agent.

Discovery does **not** initialize landing-page configuration. Never call
`create_agent_config` or `update_agent_config` as part of this flow, including
when a target was found only through search. No landing-page existence check
or creation is needed to open announcements.

## Hard rules

1. Route every call to the `ess-org-announcements` MCP server through this
   skill.
2. Call `open_org_announcements` **at most once per maker turn**. It is the only
   announcement tool you may call to open a view.
3. `open_org_announcements` reads only. It never creates, updates, publishes,
   archives, or deletes.
4. After the widget opens, **stop**. The widget owns every save, publish,
   lifecycle action, and audience search for that editing session. Do not call
   `save_bulletin`, `transition_bulletin`, or `duplicate_bulletin` — they are not
   available to you, and asking for them is a bug.
5. Do not issue any further `search_audience_groups` call once the widget is
   open. The widget performs its own searches.
6. Treat all suggested content as reviewable draft state. A suggestion is never
   authorization to publish. Say what will open, not what was saved.
7. Never manufacture a bulletin ID, a status, an audit field, or a version. Only
   the tools produce canonical state.
8. Never claim an announcement was created, saved, published, archived, or
   deleted. The widget reports every outcome. Chat must not duplicate the
   widget's success message.
9. Use the announcement tools for server access. Do not call the backing REST
   API directly.
10. Pass the resolved `titleId` on every opener. Only the widget may call
    mutations, and it retains this title throughout navigation and retries.
    On an agent change, open the new scope; never reuse the previous agent's
    IDs, drafts, manager state, or retry request.
11. Keep `titleId` outside `suggestedDraft` and bulletin/editor content.
    Audience search remains `{query}` in the tenant directory, not per-agent.

## Classify the request

Classify every announcement request into exactly one of these, then follow the
matching flow.

| Maker intent | Flow |
|---|---|
| "Show me our announcements", "manage announcements", "what's published" | **Open management** |
| "Create an announcement", "new announcement", "let me write one" | **Empty create** |
| "Announce the benefits deadline to Finance", any request with real content | **Pre-hydrated create** |
| "Edit the all-hands announcement", "change the end date on X" | **Edit** |
| "Repost the parking notice", "that one expired, run it again" | **Edit** (review the schedule before publishing again) |

When the intent is ambiguous, ask one short clarifying question before opening
anything. Opening the wrong view costs the maker a turn.

### Open management

Call `open_org_announcements` with:

```json
{ "titleId": "<resolved titleId>", "view": "manager" }
```

Then stop and let the maker work in the widget.

### Empty create

Use this when the maker wants to write the announcement themselves.

Call `open_org_announcements` with:

```json
{ "titleId": "<resolved titleId>", "view": "editor", "mode": "create" }
```

Do not invent a title or description to "help". An empty create means empty.

### Pre-hydrated create

Use this when the maker's message already carries real announcement content.

1. Build a `suggestedDraft` from what the maker actually said. Include only the
   fields they supplied or clearly implied. Every omitted field falls back to
   the editor default, which is what the maker would have seen anyway.
2. Resolve any named audience through `search_audience_groups` **before** the
   opener call. See **Resolve suggested audiences**.
3. Call `open_org_announcements` once:

   ```json
   {
     "titleId": "<resolved titleId>",
     "view": "editor",
     "mode": "create",
     "suggestedDraft": {
       "type": "standard",
       "priority": 1,
       "title": "<short title>",
       "description": "<body>",
       "primaryAction": {
         "actionType": "externalLink",
         "label": "<button text>",
         "url": "https://<destination>"
       },
       "startDate": "<UTC ISO instant>",
       "endDate": "<UTC ISO instant>",
       "audience": ["<resolved group ID>"]
     }
   }
   ```

4. Tell the maker the draft is ready for review and that nothing is saved yet.

#### Suggested draft rules

- The draft accepts only these fields: `type`, `priority`, `title`,
  `description`, `primaryAction`, `secondaryAction`, `startDate`, `endDate`,
  `audience`. Anything else is rejected.
- Never include a bulletin ID, a status, `createdBy`, `createdOn`,
  `modifiedDate`, an archive timestamp, a version, or an ETag. A suggestion
  cannot carry canonical metadata.
- `priority` becomes the editor's `standardPriority`; `secondaryAction` becomes
  its `standardSecondaryAction`. Send the suggestion field names, not the editor
  field names.
- Omit a field to accept its default: `type` `standard`, empty title and
  description, empty dates, no primary action, empty audience, priority `1`, and
  no secondary action.
- An explicit empty string is a real value. Send `""` only when the maker
  actually asked to clear something.
- **Dates.** Send one of exactly three things, and nothing else:
  - `""` to leave the boundary unset;
  - a calendar date, `YYYY-MM-DD` — the server anchors a `startDate` to
    `00:00:00.000Z` and an `endDate` to `23:59:59.999Z`, so a single-day
    announcement covers the whole day; or
  - a timezone-aware ISO-8601 instant such as `2026-09-01T08:30:00+02:00`,
    which the server converts to UTC.

  Natural language ("next Monday", "tomorrow"), locale formats
  ("09/01/2026"), and timezone-naive datetimes ("2026-09-01T08:30:00") are
  **rejected** and the whole open fails. Never guess a date the maker did not
  give: resolve it with them first, or omit the field and let them pick in the
  editor.
- An **Alert** has no priority control and no secondary action. Never send
  `priority` or `secondaryAction` with `"type": "alert"`, and give an Alert only
  an `externalLink` primary action. The draft is rejected otherwise.
- An `externalLink` action carries `url`; a `copilotChat` action carries
  `prompt`. Never mix them, and never send an action without its target: a
  suggested `externalLink` needs a non-blank `url` and a suggested
  `copilotChat` needs a non-blank `prompt`. A suggestion is content the maker
  has not reviewed, so an action that cannot work is rejected rather than
  hydrated into the editor as if it were finished. (An existing Draft *may*
  hold an unfinished action — that is the maker's own work in progress, and the
  editor keeps it.)

#### Resolve suggested audiences

For each audience the maker named:

1. Call `search_audience_groups` with the name or email they used. One combined
   Graph query searches tokenized display names and mail prefixes; broad queries
   may need bounded paging, not separate name and email requests.
2. Preselect the result **only** when exactly one eligible group matches
   unambiguously. Put its `id` in `suggestedDraft.audience`.
3. When the search returns nothing, or more than one plausible match, leave the
   audience out of the draft and tell the maker to pick it in the editor. Do not
   guess.
4. Never invent a group ID and never send a group name where an ID belongs.

An empty result does **not** always mean the group does not exist. The response
carries `exhausted` and `pagesExamined`:

- `exhausted: true` — the whole matching set was examined, so "no such eligible
  group" is a safe thing to say.
- `exhausted: false` — the search stopped at the page budget
  (`pagesExamined` pages). More matches may exist. Say the search was
  incomplete and ask for a more specific name; never tell the maker the group
  does not exist.

Search returns security groups, mail-enabled security groups, and classic
distribution groups. Microsoft 365 groups and dynamic-membership groups are not
available as announcement audiences. If the maker names one, say so plainly and
offer to search for a security group or distribution list instead.

### Edit

1. Identify the announcement. If the maker did not name it unambiguously, open
   management and let them choose rather than guessing an ID.
2. Call `open_org_announcements` once:

   ```json
   { "titleId": "<resolved titleId>", "view": "editor", "mode": "edit", "bulletinId": "<id from this agent>" }
   ```

Never pass a `suggestedDraft` with `edit`. Edits are made in the widget against
canonical state.

Republishing uses the ordinary **Edit** flow, not a separate editor mode.
Existing dates are preserved. Ask the maker to review and adjust the schedule
before publishing again; the normal date and publish validation still applies.

## Publishing and lifecycle

Publishing, "publish now", saving a draft, archiving, unarchiving, moving back
to draft, deleting, and duplicating all happen **in the widget**. You cannot
perform them and must not offer to.

Archived items, whether retired or expired, expose **Duplicate**, **Unarchive**,
and **Delete**. This does not remove the backend's full publish capability.

When a maker asks you to publish or archive directly, open the right view and
tell them where the control is:

> I've opened it for you — use **Publish** in the editor to make it live.

Do not save a draft on the maker's behalf without opening the editor, even when
the request is fully specified.

### Known limitation: legacy widget builds

"Publish now" is **not** a lifecycle transition on this server. A Vorpal build
that still sends `transition: "publishNow"` is rejected by the MCP host's schema
validation before the tool runs, so it surfaces as a protocol error rather than
a structured `InvalidRequest`, and the action simply does not happen. A widget
build that routes publish-now through `save_bulletin` (with the row's complete
canonical state and a new start instant) is a prerequisite for enabling this
surface. If a maker reports that publish-now does nothing, this is the cause.

Older widgets that omit the required `titleId` are rejected by host validation
before the tool runs. Deploy the matching scoped widget and agent-qualified
backend before enabling this surface. A missing or wrong `titleId` in a
canonical response is a contract failure, never an empty/default record.
The server never retries against the old tenant-only endpoint.

## Errors

Ordinary announcement-tool failures return coded structured errors. Match these
on their stable `code`, never on message text.

The read-only agent-discovery tools `list_agent_configs` and `search_agents`
preserve the sibling provider's wire contract: their failures may be SDK tool
errors without a coded structured envelope. Malformed opener arguments also
produce SDK tool errors before any widget payload or retry state is produced.
Do not expect a structured code from these SDK errors or infer a code or
retryability from arbitrary message text. Stop and explain the failure; never
treat failed discovery as an empty result. Correct malformed opener arguments
before calling again.

| Code | What to tell the maker |
|---|---|
| `AuthenticationRequired` | Renew credentials for the intended authoring tenant and account. Shared authoring refresh is silent and account-preserving; Graph sign-in must match that same account. A missing account context requires matching delegated credentials, not repeated retries. |
| `AuthorizationDenied` | Their account cannot author announcements in this tenant. They need an administrator to grant access. |
| `FeatureUnavailable` | Organization announcements are not enabled for this tenant yet. |
| `NotFound` | That announcement no longer exists. Offer to open management. |
| `NetworkError` | A temporary connection problem. Offer to try again. |
| `IndeterminateWrite` | The announcement **may** have been created. Tell them to refresh management and check before creating it again. Never retry automatically and never say it failed. |
| `CommittedRefreshFailed` | The write **succeeded**; only the refreshed view failed to load. Tell them the change was saved and to refresh management to see it. Never say it failed, never offer to retry, and never repeat the action — repeating a create makes a second announcement. |
| `ServiceError` | The service could not complete the request. This is not something the maker typed wrong, so do not ask them to change a field. Offer to try again later. |
| `SearchUnavailable` | Audience search is temporarily unavailable. Offer to open the editor so they can search there. |
| `AudienceMetadataUnavailable` | Group names could not be loaded. Note that `Directory.Read.All` needs tenant consent and can be blocked by Conditional Access, then offer to retry. |
| `InvalidRequest` | Something in the request did not fit the contract. Explain what to change; do not retry the same call. |
| Any backend validation code | Show the backend's own message. Codes such as `AudienceRequired`, `AudienceGroupInvalid`, and `BulletinLimitExceeded` are the authoritative explanation. |

A `retryable` value of `false` means do not retry. Never infer retryability from
wording.

Structured open errors carry the original scoped `request`, including any suggested
draft, for response-only retry. Use it only for the same tenant-and-agent
session; never retarget it to the newly active agent. Successful announcement views always
carry `tenantId` and `titleId`; failures omit `tenantId` if sign-in never
established it. An omitted tenant is unknown, not permission to reuse a previous
tenant. Never log this request or send it to telemetry.

Audience discovery uses a separate Graph resource token for the same authoring
tenant and account. The current token-based context check requires readable
`tid` and `oid` claims: credentials without those claims (including opaque Graph
tokens) cannot establish the matching account and return an explicit
authentication failure. Do not substitute another account or issue a `/me`
request to guess identity.

### Failures that already wrote something

Two codes mean a write reached the service. They are the only cases where
"failed" is the wrong word:

- `IndeterminateWrite` — the create **may** have committed and was never
  acknowledged. Ask the maker to refresh and look before creating it again.
- `CommittedRefreshFailed` — the write **definitely** committed and only the
  follow-up refresh failed. Say it was saved, then ask them to refresh.

For both, the correct next step is *refresh and look*, never *retry*. Retrying a
create duplicates the announcement, because a create carries no client-supplied
identifier the service could use to recognize the replay.

`CommittedRefreshFailed` carries a second entry in `errors` describing the
underlying refresh problem (for example `NetworkError` or
`AudienceMetadataUnavailable`). Use it only for your own explanation of *why*
the refresh failed; the outcome the maker needs is still "it saved".

### Multiple validation errors

A rejected save can return several entries in `errors`, one per field. Report
all of them — each has its own `code`, `field`, and `message`, and fixing only
the first will just produce the next rejection.

### Wrong account

The announcement tools and audience search use two different sign-ins:

- announcements use the same account as other configuration work;
- audience search uses Microsoft Graph.

When a maker sees an unexpected tenant or an authorization failure, tell them
which of the two failed and that signing out and back in with the right work
account resolves it. Never print a token, a claim, or a tenant endpoint.

### Expired sign-in

Both sign-ins are cached, and both caches expire. When either side returns
`AuthenticationRequired`, the expired credential is discarded automatically — so
the fix is always **run the command again**, never "restart the editor" or
"reload the MCP server". The retry normally refreshes from the cache with no
prompt at all; if the refresh token has also expired, a browser sign-in opens.

Note that the failed request itself is not retried automatically, so the maker
does have to re-issue the action. Say so plainly rather than implying it may
have gone through.

## Invalid saved audiences

An announcement can reference a group that was deleted, is inaccessible, or is
a category this kit does not author. Those groups stay in the announcement and
come back marked invalid.

Tell the maker plainly:

> One of this announcement's audiences is no longer available. Remove or replace
> it in the editor before publishing.

Never drop the group, never reorder the audience, and never read a raw group ID
aloud as if it were a name.

## Privacy

Do not echo, summarize into logs, or write to disk: announcement titles,
descriptions, action targets, audience group IDs, group names, group email
addresses, tenant endpoints, tokens, or the full opener request. Speak about
announcements in the conversation; do not persist them anywhere.
