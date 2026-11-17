# Shared agent title resolution

Read this procedure when either the landing-page or Org Announcements skill
needs an agent's announcement/configuration scope. The calling skill supplies
its own MCP provider: `ess-landing-page-config` or `ess-org-announcements`.
Use that provider's `resolve_agent_title_id` tool; never require the other
provider's MCP process.

This procedure resolves identity only. It does not check, initialize, read,
update, or delete landing-page configuration or announcements. Resume the
calling skill's normal feature flow after selecting the scope.

## Identity and cache

One configured DA bot can have two Microsoft 365 registrations:

- **Regular:** `bot.teamsAppInformation.microsoft365.titleId` in the components response.
- **LOB:** the M365 publish-status response's `titleId`, mapped to `lobTitleId`.

Different IDs are different scopes. Do not infer registration from announcement
content, an agent name, an announcement's type, an app ID, or a share link.
Both `appId`/`lobAppId` and `shareLink`/`lobShareLink` are not title-ID sources.
The components response alone does not establish the DA LOB registration.

Keep the verified pair on the selected local agent as:

```json
{
  "registrationTitleIds": {
    "titleId": "<regular title ID>",
    "lobTitleId": "<LOB title ID>"
  }
}
```

Use JSON `null` for a registration the resolver reports as unavailable. A
missing cache object/key is unknown, not proof that the registration is absent.
Never copy `lobTitleId` into the pair's `titleId` or vice versa.

The existing top-level `titleId` is the **selected scope**, not necessarily the
regular identity. Preserve explicit/cached-ID precedence: an intentionally
supplied scope ID wins, then a compatible verified conversation choice or
stored selected `titleId`. An explicit Regular/LOB request takes precedence
over a stored selection of the other registration. Never treat a pasted pair
of metadata values as an implicit selection of its regular ID.

## Explain the registration choice

When a registration choice is needed, expand **LOB** as **line-of-business**
and explain that Regular and LOB are two Microsoft 365 app registrations of the
same agent, not different bots or audience groups. Announcements and landing-page
settings belong to the selected registration; changes for one are not
automatically applied to the other.

Ask which registration their intended users use to open the agent. Do not guess
a deployment or distribution channel from the labels or IDs. If the maker does
not know which registration they intend to configure, clarify that target
before continuing.

For example: "Regular and LOB (line-of-business) are separate app registrations
of this agent. An announcement or landing-page change for one does not apply
to the other. Which registration do your intended users use?"

Do not present unexplained Regular/LOB labels or title IDs alone. This
explanation accompanies a needed choice; it does not require another question
when an explicit, verified, or compatible cached selection already exists.

## Resolve and choose

1. Read the complete `.local/config.json` already gated by the calling skill.
   Select the active agent from `agent`, or another configured `agents` entry
   by `slug`, `botId`, or unambiguous name. Resolve ambiguity before any lookup.
   Record the selected bot GUID and environment before discovery. DA setup's
   canonical `.local/setup/config.json` locks the environment, ring and tenant;
   conflicting local mirrors must be corrected through `/setup`, not guessed.
2. If the maker intentionally supplies `titleId` or `lobTitleId` as the exact
   scope, use that value as the calling tool's `titleId`. If a registration
   label conflicts with an explicit scope ID in known metadata, ask which
   scope is intended. An explicit scope without a matching local agent is
   request-only; do not fabricate a partial local agent.
3. Otherwise reuse a non-null cached ID for an explicitly requested Regular or
   LOB registration, or a verified conversation choice for the same bot and ID.
   Without a registration-specific request, a stored selected `titleId` can
   be reused; do not force discovery merely to reopen an established scope.
   If a complete pair contradicts that stored selection, refresh once and
   clarify the target rather than silently relabeling the selection.
4. Call this feature provider's read-only `resolve_agent_title_id` with the
   selected configured `botId` when the needed ID is missing, the registration
   kind cannot be established from a legacy scalar cache, or the maker asks
   to refresh or choose registrations. Do not use `list_agent_configs`,
   `search_agents`, name search, or tenant-wide discovery as a fallback.
   The tool validates the exact bot through
   `GET /copilotstudio/minimalBots/api/{botId}?api-version=2024-10-01`,
   then reads regular metadata through the existing read-only component fetch,
   `POST /copilotstudio/minimalBots/api/{botId}/components?api-version=2022-03-01-preview`
   with `{}`. It validates `bot.cdsBotId`, then reads
   `GET /copilotstudio/agents/{botId}/channels/m365/publish?api-version=2024-10-01`
   with `X-CCI-CdsBotId` set to that exact bot. The plain response `titleId`
   supplies the canonical `lobTitleId`, not the regular title.
   It returns `botId`, `titleId`, and `lobTitleId`. Both registration keys
   are always returned; JSON `null` means unavailable. At least one ID must
   be available. A legacy cache containing only a top-level `titleId` does
   not prove the registration identities.
5. Persist both discovered registration fields according to the gate below.
   If the maker requested **Regular**, use the regular `titleId`; if they
   requested **LOB**, use `lobTitleId`. If the requested registration remains
   unavailable after discovery, explain that and stop. Never silently fall
   back to the other registration.
6. If no explicit, verified, or compatible stored selection exists, use the
   only available ID. If both IDs are available and different, ask the maker
   to choose **Regular registration** or **LOB registration**. Explain the
   distinction above before asking. Do not open a view or issue a feature
   mutation until they choose. If both fields contain the same ID, they
   address one scope and need no duplicate choice.
7. When the chosen ID is verified to belong to the local target, persist that
   choice in the target's scalar `titleId` and its active mirror. This is an
   intentional selection change, not a change to either canonical field in
   `registrationTitleIds`. Never initialize the selected alias before the
   required choice or use an automatically initialized alias as maker intent.
   Pass the chosen non-null value as the calling feature tool's `titleId`.
   An explicitly chosen `lobTitleId` is passed as the opener's `titleId`,
   never as a new opener parameter.
   An unchanged, already-recorded cached selection needs no rewrite or legacy
   migration merely to reuse it; the persistence gate applies to new discovery
   results and actual selection changes.

## Persistence gate

After successful discovery, reread the complete config before writing:

1. Match the selected entry in `agents` by the returned `botId`, normalizing
   both identifiers as GUIDs. Require exactly one match. Never persist by
   display name or by slug alone.
2. If the active target exists only as legacy `agent`, require its normalized
   bot GUID to match and copy that complete object into `agents`. Do not
   invent `botId`, schema, folder, or other agent properties.
3. Confirm the target GUID and environment have not changed during discovery,
   including the canonical DA environment, ring, endpoint and tenant binding.
   If the configured target disappeared or changed, surface the error and
   stop. Do not fabricate a replacement entry or persist a partial result.
4. Determine active status before any write. Treat the target as active only
   when `activeAgent` identifies its slug and any existing `agent.botId`
   identifies that same bot, or when legacy `agent.botId` matches and
   `activeAgent` is absent. If only `activeAgent` exists, require an unambiguous
   match and copy the complete selected entry into `agent`. If active markers
   conflict, surface the configuration error and stop before writing.
5. Update only the selected entry's `registrationTitleIds` with the returned
   pair, including JSON `null` for a known unavailable registration. Also
   update `agent.registrationTitleIds` when the target is active. Preserve the
   existing selected scalar until a scope has been chosen; then update only
   the selected entry's `titleId` and, when active, `agent.titleId`.
6. Preserve all other fields and agents, the entire `agents` array, and every
   top-level field. For a non-active target, leave `agent` and `activeAgent`
   unchanged. Do not change cached values after failed discovery. Do not
   rewrite canonical setup state or workspace projection files to store titles.
7. Write valid JSON and reread to verify both the selected entry and active
   mirror before another feature tool call. A required registration question
   can follow verification of the pair; verify the selected scalar after the
   maker chooses and before proceeding.

Do not overwrite the regular identity when selecting LOB: it remains in
`registrationTitleIds.titleId` even when the selected scalar `titleId` becomes
the LOB ID. Setup preserves the pair and selected scalar when rebuilding the
same agent in the same environment; neither may transfer to a different bot.

## Errors and in-flight work

Use the agent's recorded native environment, validated against canonical DA
setup and the environment GUID encoded in its PPAPI host. DA-only setup does
not require a Dataverse endpoint. Never fall back to Dataverse, a name search,
another environment, or another registration after an API error.

The publish-status GET is a Studio frontend route confirmed by prior read-only
probes, not a public documented API contract. Never POST `/publish`, require
a channel-root GET, or invent a realm parameter. The implemented fail-closed
policy treats HTTP 404 as `NotFound`, not as proof of missing registration;
a null/non-object response or missing `titleId` field is malformed metadata.
An explicit null/blank title in a valid response means that registration is
unavailable. These failure policies are offline-tested, not live-established.

Missing both registration IDs is `RegistrationRequired`. Authentication,
authorization, network, and malformed-response failures are explicit errors,
not empty discovery. Report the tool's error and stop. Never synthesize a
title as `T_{botId}` or substitute a bot, Teams, or application ID.

Power Platform metadata discovery requests ring-global MinimalBot.Read and
MakerOperations.Read scopes, reusing the authoring MSAL cache for the exact
tenant/account. Prior successful reads also had previously granted ReadWrite
permissions, so minimum endpoint permissions have not been established.
Substrate and Power Platform retain separate resource tokens.

Interactive Power Platform sign-in is limited to 300 seconds. A cancelled request
leaves its lookup tracked until its worker finishes; retries do not start
another lookup until it finishes. If resolution is already in progress,
complete the pending sign-in or wait for its timeout before retrying. Do not
repeatedly call the resolver or reuse an in-flight result for a changed target.

When the agent or chosen registration ID changes, discard the previous
scope's widget association, item IDs, drafts, manager/configuration state,
existence assumptions, and retry request. The calling feature owns its
normal permission checks and authoring lifecycle.
