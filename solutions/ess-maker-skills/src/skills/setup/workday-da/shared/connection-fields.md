# Connection Fields — Capture & Validate (DA)

Centralizes capture and validation of the Workday connection identifiers the
DA Workday setup skills exchange. **DA-3 captures** these (from the Workday
API client view and tenant URL); a later DA extension-pack configuration step
consumes them when it binds the connection. Keeping the rules here means both
steps agree on format — especially the documented **REST-base `/api` trim**
gotcha that silently breaks the connection if it's wrong.

Forked from the CEA `setup/shared/connection-fields.md` with DA-scoped state
paths. The tenant math (URL derivation, trim rules) is agent-architecture
agnostic and identical to the CEA version — only the persisted file changes.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase or narrate tool calls.

**Inputs from the calling file (any that are already known):**
- `WD_TENANT`, `WD_BASE_URL`, `WD_TOKEN_HOST` — captured by DA-3 from the
  Workday tenant / API-client screens (or read from
  `.local/connect/workday-da/config.json` when an earlier step already stored
  them).
- `OAUTH_CLIENT_ID`, `TOKEN_ENDPOINT` — from the Workday "View API Client"
  screen (DA-3).
- `ENTRA_APP_ID_URI` — the Entra Application ID URI
  (`api://{entraAppId}`) from DA-2.
- `WORKDAY_SAML_ENTITY_ID` — the Workday SAML Service Provider ID and
  connection resource URL (`http://www.workday.com/{tenant}`) from DA-2.

**Outputs (written back to `.local/connect/workday-da/config.json`, see
`config-schema.md`):**
- `entraAppIdUri`, `workdaySamlEntityId`, `oauthTokenUrl` / `tokenEndpoint`,
  `oauthClientId`,
  `soapBaseUrl`, `restBaseUrl` (trimmed).

---

## C.1 — Keep the two audience identifiers distinct

The Application ID URI identifies the Entra app registration itself
(`api://{entraAppId}`). DA-3 exposes it for the SAML token audience and the
connector's API pre-authorization. It is **not** the connection's "Microsoft
Entra resource URL" — see the note below.

- Expected form: `api://{entraAppId}` (the GUID, not the object ID).
- If `ENTRA_APP_ID_URI` is missing, derive it from `entraAppId`:
  `api://{entraAppId}`.
- **Validate:** must start with `api://` and contain a GUID. If it instead looks
  like a full URL (`https://...`) or is empty, re-prompt:

```json
[
  {
    "header": "Application ID URI",
    "question": "What's the Application ID URI of the Entra app? It looks like api://<app-client-id>."
  }
]
```

Save as `entraAppIdUri`.

> **Not the connection resource URL.** The Workday connection asks for a
> **Microsoft Entra resource URL** — the Workday SAML identifier
> `http://www.workday.com/{tenant}` (matching the Entra app's Identifier /
> Entity ID and Workday's SAML Service Provider ID), **not** this `api://…` App
> ID URI.

Derive `WORKDAY_SAML_ENTITY_ID` independently from the validated Workday
tenant as `http://www.workday.com/{tenant}` and save it as
`workdaySamlEntityId`. Reject the data if these two identifiers are equal or if
the SAML entity ID does not exactly match the selected tenant.

---

## C.2 — OAuth token URL

- Expected form: `https://{WD_TOKEN_HOST}/ccx/oauth2/{WD_TENANT}/token`.
- If `TOKEN_ENDPOINT` was captured from the API client screen, prefer it but
  confirm it matches the derived form's host + tenant; if it diverges, keep the
  captured value and note it.
- **Validate:** must be `https://`, contain `/ccx/oauth2/`, and end with `/token`.

Save as `oauthTokenUrl` (and `tokenEndpoint` when captured from the API client).

---

## C.3 — Client ID

- `OAUTH_CLIENT_ID` is the **Workday API client ID** shown on the "View API
  Client" screen. It is **not** the Entra `entraAppId` — do not conflate them.
- **Validate:** non-empty. If the user pastes something that is obviously the
  Entra app GUID already stored as `entraAppId`, warn and re-ask — they are
  distinct identities.

Save as `oauthClientId`.

---

## C.4 — SOAP base URL

The SOAP base is derived from the Workday **services** host (the same host as
`WD_TOKEN_HOST`, so `https://{WD_TOKEN_HOST}/ccx/service` is equivalent):

- `impl.workday.com` → `https://wd2-impl-services1.workday.com/ccx/service`
- `wd5.myworkday.com` → `https://wd5-services1.myworkday.com/ccx/service`
- `{dcN}.myworkday.com` → `https://{dcN}-services1.myworkday.com/ccx/service`

- Expected form: `https://{services-host}/ccx/service` (no tenant suffix, no
  trailing slash).
- **Validate:** must be `https://`, contain `/ccx/service`, and **not** end in a
  trailing `/`. If `WD_BASE_URL` didn't match a known pattern, fall back to
  asking the user for the SOAP base URL.

Save as `soapBaseUrl`.

---

## C.5 — REST base URL — trimmed to `/api` *(silent-failure gotcha)*

This is the field that most often breaks the simplified-path connection. The
Workday screens and copy/paste sources frequently include extra trailing
segments. **Copy as displayed, then trim** so the value ends at `/api`.

- Canonical form: `https://{WD_TOKEN_HOST}/ccx/api`.
- **Trim procedure** — starting from whatever was captured:
  1. Strip any trailing slash.
  2. If it ends with a version segment (`/v1`, `/v2`, …), remove it.
  3. If it ends with the tenant name or any path **after** `/ccx/api`, remove
     everything after `/ccx/api`.
  4. The result must end exactly with `/ccx/api` (or `/api` for hosts that omit
     `/ccx`).
- **Validate:** must be `https://`, contain `/api`, and have **nothing** after
  the `/api` segment. If anything follows `/api`, trim it and show the user the
  corrected value:

**Message:**

I trimmed the Workday REST base URL to **{restBaseUrl}** — the connection
fails silently if anything is appended after `/api`, so it has to end there.

**End message.**

Save the trimmed value as `restBaseUrl`.

---

## C.6 — Persist

Read `.local/connect/workday-da/config.json`, merge the validated fields above
(never dropping fields owned by other steps), and write it back — per the
round-trip contract in `config-schema.md`. Return the saved values to the
calling file.
