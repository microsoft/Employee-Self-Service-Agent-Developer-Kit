#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a cassette covering Workday admin queries via the Workday Query
Language (WQL) REST endpoint.

WQL is Workday's general-purpose data-query REST API. Unlike the
unpredictable URL paths of Workday's per-resource REST admin endpoints,
WQL has a single well-defined endpoint and a SQL-like query syntax that
exposes ANY queryable data source in the tenant — including the admin
data sources that validate the configuration steps in the MS Learn
Workday integration docs.

Endpoint:
    POST /ccx/api/wql/v1/{tenant}/data
    Authorization: Bearer {access_token}
    Body: {"query": "<WQL string>"}

The OAuth setup is identical to record_workday_rest_admin.py: API
Client registered via "Register API Client for Integrations" task,
refresh token bootstrapped via "Manage Refresh Tokens for Integrations".

This wrapper captures responses to several WQL queries that future
FlightCheck config-validation checks would consume:

  - List all active API clients (validates Workday Task 5)
  - List authentication policies (validates Workday Task 4 / Task 3
    in the simplified flow)
  - List integration system users matching ISU_*_COPILOT (validates
    Legacy Task 3)
  - List integration system security groups matching ISSG_*_COPILOT
    (validates Legacy Task 3)
  - List custom reports matching WD_User_Context (validates Legacy Task 8)

⚠️ NOTE on WQL scope: the API Client must have the "Workday Query
Language" functional area in its scope. If queries return 403, edit
the API Client and add that scope (the same way you added Staffing).

⚠️ KNOWN BLOCKER — chicken-and-egg auth (do NOT build a runtime
FlightCheck check on this cassette without resolving this first):

  Workday's REST/WQL endpoints accept ONLY OAuth 2.0 Bearer tokens.
  No Basic auth, no session cookie, no "log in as the admin user."
  OAuth = an API Client registered in Workday.

  To validate "the customer's ESS API Client is registered correctly
  via WQL," FlightCheck itself needs its own OAuth API Client
  registered in the same tenant. Registering that client (Workday
  tasks: "Register API Client for Integrations" + functional area
  scope + "Manage Refresh Tokens for Integrations") is nearly the
  same workflow as the ESS Workday integration setup the check is
  supposed to verify.

  Net effect: shipping a WQL-based FlightCheck check pushes the
  setup-pain problem one level deeper, not solves it. A customer who
  can't complete the ESS Workday setup probably also can't complete
  the FlightCheck OAuth setup.

  This recorder still exists because the cassette is valuable as
  DISCOVERY EVIDENCE — it documents the WQL admin surface, captures
  response shapes for 6 useful data sources, and surfaces the
  dataSourceFilters / requiredParameters mechanism. But it is NOT
  the foundation for a runtime check until one of these is solved:

    1. authorization_code + PKCE (still needs API Client registration,
       only removes the "Manage Refresh Tokens" step)
    2. Microsoft adds FlightCheck's redirect URI to the API Client the
       ESS Workday extension pack already registers (zero customer
       setup, but only works AFTER the ESS extension is installed)
    3. SOAP with WS-Security UsernameToken on admin services like
       Identity_Management (no API Client needed, but Get_API_Clients
       was NOT in the publicly-exposed SOAP service list per a 2026-05
       capture attempt against this tenant — would need a re-test)
    4. Drop Workday config validation entirely; check only what's
       visible from outside Workday (Power Platform connection refs,
       env vars — what WD-CONN-001 / WD-ENV-001 already do).

  See the corresponding section in tests/fixtures/cassettes/INDEX.md.

⚠️ NOTE on table/field names: WQL uses Workday-defined "data sources"
which are tenant-specific. If a query returns "Data source not found"
or similar, the table name may be different on your tenant — Workday's
"View WQL Data Sources" report enumerates what's available.

⚠️ KNOWN LIMITATION — filterIsRequired data sources:
  Some WQL data sources have `filterIsRequired: true` (the recorder
  prints this for every source so you can tell). Examples include
  `allSystemAccountSignons`. These sources reject unfiltered queries
  with HTTP 400 "Specify a data source filter".

  The detail endpoint exposes `requiredParameters[]` (typed inputs)
  and `dataSourceFilters[]` (each with an `alias` and `id`/WID), but
  the exact WQL syntax to invoke a filter from the /data endpoint
  could not be determined from REST experimentation alone (function-
  call FROM, qualified names, URL params, dataSourceFilter wrapper
  body — all returned 400 with various errors).

  This recorder INTENTIONALLY skips the actual query for filter-
  required sources but still prints their declared filters/params so
  a future agent with access to Workday's WQL REST API reference can
  fill in the right syntax. As a workaround for tenant config
  validation today, use `allIntegrationSystemsAudited` (already
  captured) — it shows audit metadata for every integration the ISU
  has executed, which is a sufficient proxy for "is the ISU active".

Pre-reqs (same as record_workday_rest_admin.py):
    $env:WORKDAY_TENANT_HOST          = "https://wd2-impl-services1.workday.com"
    $env:WORKDAY_TENANT_NAME          = "<tenant>"
    $env:WORKDAY_OAUTH_CLIENT_ID      = "<API client id>"
    $env:WORKDAY_OAUTH_CLIENT_SECRET  = "<API client secret>"
    $env:WORKDAY_OAUTH_REFRESH_TOKEN  = "<from Manage Refresh Tokens task>"
    python tests\\captures\\record_workday_wql.py

Output: tests/fixtures/cassettes/workday_wql_admin.yaml
"""

from __future__ import annotations

import os
import re
import sys

from _common import announce, build_cassette, chdir_kit_root, confirm_or_exit

# Re-use the OAuth token-acquisition logic from the REST admin wrapper.
# Both wrappers exchange a refresh token for a bearer token via the
# same Workday OAuth endpoint; no need to duplicate.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from record_workday_rest_admin import (  # noqa: E402
    REQUIRED_ENV as REST_REQUIRED_ENV,
    _acquire_token,
    _check_env as _check_rest_env,
    _rewrite_web_to_soap_host,
)

# WQL needs the same OAuth env as REST admin, plus the refresh token.
REQUIRED_ENV = REST_REQUIRED_ENV + ("WORKDAY_OAUTH_REFRESH_TOKEN",)


def _check_env() -> dict[str, str]:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        print("ERROR: missing required environment variables:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)
    return {name: os.environ[name] for name in REQUIRED_ENV}



# Each entry: (label, WQL query string, doc-step it validates)
#
# Data source names below were confirmed via the catalog endpoint
# fetched in Step 2 — they're real on this tenant. The Simplified-setup
# config items (API Clients, Authentication Policies) are NOT queryable
# via WQL — they're not in the catalog. Those would need a different
# validation approach (Workday REST admin endpoints, or RaaS reports).
#
# WQL syntax notes:
#   - WHERE uses standard `=` and `IN`. SQL `LIKE 'foo%'` is NOT
#     supported in WQL — use exact match or post-filter client-side.
#   - SELECT field names must match exactly. Use `SELECT *` first to
#     discover fields, then narrow.
WQL_QUERIES: list[tuple[str, str, str]] = [
    (
        "SANITY: allWorkers (1 row, all fields)",
        "SELECT * FROM allWorkers LIMIT 1",
        "Diagnostic: confirms WQL works at all. allWorkers is universal "
        "across Workday tenants.",
    ),
    (
        "Security Groups (first 10, all fields)",
        "SELECT * FROM allSecurityGroups LIMIT 10",
        "Backs Legacy Task 3 partial validation: ISSG_*_COPILOT groups "
        "should appear in this list. Future check would post-filter for "
        "the specific names.",
    ),
    (
        "Custom Reports (first 10, all fields)",
        "SELECT * FROM allCustomReports LIMIT 10",
        "Backs Legacy Task 8 validation: WD_User_Context RaaS report "
        "should appear in this list. Future check would post-filter for "
        "the specific report name.",
    ),
    (
        "Integration Systems Audited (first 10, all fields)",
        "SELECT * FROM allIntegrationSystemsAudited LIMIT 10",
        "Indirect Legacy Task 3 validation: each ISU (ISU_WQL_COPILOT, "
        "ISU_Generic_COPILOT) is associated with an Integration System. "
        "This data source lists those parent objects.",
    ),
]


def main() -> None:
    announce("workday_wql_admin")
    env = _check_env()

    raw_host = env["WORKDAY_TENANT_HOST"].rstrip("/")
    soap_host = _rewrite_web_to_soap_host(raw_host)
    if soap_host != raw_host:
        print(f"  Note: rewrote web host {raw_host} -> services host {soap_host}")
    tenant = env["WORKDAY_TENANT_NAME"]
    token_url = f"{soap_host}/ccx/oauth2/{tenant}/token"
    wql_url = f"{soap_host}/ccx/api/wql/v1/{tenant}/data"
    refresh_token = env["WORKDAY_OAUTH_REFRESH_TOKEN"]

    print(f"  Token endpoint: {token_url}")
    print(f"  WQL endpoint:   {wql_url}")
    print()

    confirm_or_exit()
    chdir_kit_root()

    import requests

    print("  Step 1: acquiring OAuth access token...")
    with build_cassette("workday_wql_admin"):
        token = _acquire_token(
            token_url,
            env["WORKDAY_OAUTH_CLIENT_ID"],
            env["WORKDAY_OAUTH_CLIENT_SECRET"],
            None,  # no JWT
            refresh_token,
        )
        if not token:
            print("  ABORT: no access token; not making WQL calls.")
            return
        print(f"  Step 1: OK (received {len(token)}-char access token)")
        print()

        # Step 2: fetch the WQL data source catalog. This is a separate
        # REST endpoint from the /data query endpoint — it lists every
        # valid data source name on this tenant. The catalog endpoint
        # caps at 100 results per page so we paginate via offset to
        # collect all 1500+ data sources, then grep client-side.
        catalog_url = f"{soap_host}/ccx/api/wql/v1/{tenant}/dataSources"
        print(f"  Step 2: fetching WQL data source catalog from {catalog_url}")
        all_sources: list[dict] = []
        try:
            offset = 0
            page_size = 100
            page_no = 0
            while True:
                page_no += 1
                r = requests.get(
                    catalog_url,
                    params={"limit": page_size, "offset": offset},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    timeout=60,
                )
                if r.status_code != 200:
                    print(f"    Catalog page {page_no} -> {r.status_code}")
                    print(f"    body[:300]: {r.text[:300]}")
                    break
                body = r.json()
                rows = body.get("data", [])
                total = body.get("total", 0)
                all_sources.extend(rows)
                if not rows or len(all_sources) >= total:
                    break
                offset += page_size
                if page_no > 50:  # safety bound
                    print("    Stopping pagination after 50 pages — something odd.")
                    break

            print(f"    Catalog fetched: {len(all_sources)} data sources (across {page_no} pages)")

            # Show one raw row so we can see all keys (id/WID, alias,
            # descriptor, etc.). The detail endpoint wants the WID, not
            # the alias.
            if all_sources:
                sample = all_sources[0]
                print(f"    Sample row keys: {sorted(sample.keys())}")
                print(f"    Sample row:      {sample}")

            # Dump the entire catalog (alias + descriptor + WID only) to a
            # local-only file so the human can grep offline when the
            # automated keyword search misses. This file is gitignored —
            # it's a discovery aid, not a committed fixture.
            #
            # Path is .local/ under tests/fixtures so it sits next to the
            # cassettes but is excluded by tests/fixtures/.local/.gitignore.
            from pathlib import Path
            local_dir = Path("tests/fixtures/.local")
            local_dir.mkdir(parents=True, exist_ok=True)
            (local_dir / ".gitignore").write_text("*\n", encoding="utf-8")
            catalog_dump = local_dir / "workday_wql_catalog.txt"
            with catalog_dump.open("w", encoding="utf-8") as fh:
                fh.write(f"# Workday WQL data source catalog ({len(all_sources)} sources)\n")
                fh.write(f"# Format: alias\\tdescriptor\\tWID\n")
                for row in sorted(all_sources, key=lambda r: r.get("alias") or ""):
                    fh.write(f"{row.get('alias')}\t{row.get('descriptor')}\t{row.get('id')}\n")
            print(f"    Full catalog dumped to {catalog_dump} (gitignored).")
            print(f"    Grep it with:  Select-String -Path {catalog_dump} -Pattern '<term>'")
            print()

            # Index by alias so step 3 can resolve alias -> WID.
            sources_by_alias = {row.get("alias"): row for row in all_sources if row.get("alias")}

            # Filter for keywords likely to match the admin data sources
            # we want. Searches both `alias` (the name used in WQL FROM
            # clauses) and `descriptor` (human-readable label).
            #
            # Lists are exhaustive on purpose: Workday's data source
            # naming is inconsistent (some use camelCase, some prefix
            # with `all`, some use abbreviations like `oauth`). Match
            # is case-insensitive substring against alias OR descriptor.
            keywords = {
                "API Client validation":  [
                    "apiClient", "api_client", "APIClient", "WebServiceAPI",
                    "oauth", "OAuth", "applicationCredential",
                    "registeredAPI", "tenantedURL", "client credentials",
                    "API Client", "web service",
                ],
                "Auth policy validation": [
                    "authentication", "authPolicy", "authenticationPolicy",
                    "signOn", "signOnPolicy", "SSO", "ssoPolicy",
                    "tenantSecurity", "loginPolicy", "passwordPolicy",
                    "Authentication Policy", "Sign-On",
                ],
                "ISU validation":         [
                    "integrationSystem", "isu", "ISU",
                    "Integration System User", "integration user",
                    "applicationUser", "systemUser",
                ],
                "Security group":         ["securityGroup", "SecurityGroup", "security group"],
                "Custom report":          ["customReport", "CustomReport", "custom report"],
                "Workers (basic)":        ["worker"],
            }
            print("    Matches by category (alias  [descriptor]):")
            for category, kws in keywords.items():
                matches = []
                for row in all_sources:
                    alias = row.get("alias") or ""
                    descriptor = row.get("descriptor") or ""
                    for kw in kws:
                        if kw.lower() in alias.lower() or kw.lower() in descriptor.lower():
                            matches.append((alias, descriptor))
                            break
                print(f"      {category}: {len(matches)} matches")
                for alias, descriptor in matches[:15]:
                    print(f"        - {alias}  [{descriptor}]")
                if len(matches) > 15:
                    print(f"        ... and {len(matches) - 15} more")
        except requests.RequestException as exc:
            print(f"    Catalog endpoint ERROR: {exc!s}")
        print()

        print("  Step 3: discovering fields per data source, then querying with real fields...")

        # Data sources we want to capture (must be in the catalog above).
        #
        # Why these specific sources back FlightCheck config-validation:
        #
        # - allWorkers: sanity check + worker shape. If this fails, the
        #   API client doesn't have basic Worker access — broken setup.
        #
        # - oAuth20RefreshTokenDataSource: lists active OAuth 2.0 refresh
        #   tokens. Workday does NOT expose an "API Clients" table as a
        #   first-class WQL entity. This is the canonical proxy: if the
        #   API client we registered has a usable refresh token, this
        #   data source will show it. Backs Workday Task 5 validation
        #   ("API Client registered + refresh token bootstrapped").
        #
        # - allSystemAccountSignons: lists sign-on events for system
        #   accounts (ISUs). Workday does NOT expose "Authentication
        #   Policy" as a WQL entity — auth policy is tenant-wide config.
        #   The observable effect of a working auth policy is: the ISU
        #   can sign on. Backs Workday Task 4 validation ("Auth Policy
        #   permits OAuth2 sign-on for the ISU").
        #
        # - publicWebServices: lists web service operations exposed to
        #   the current API client. If 'Workday Query Language' isn't in
        #   here, the API client lacks the WQL scope. Backs the API
        #   client SCOPE half of Task 5 validation.
        #
        # - allSecurityGroups: backs Legacy Task 3 ISSG validation
        #   (filter to ISSG_*_COPILOT to confirm group exists).
        #
        # - allCustomReports: backs Legacy Task 8 RaaS report validation
        #   (filter to WD_User_Context to confirm report exists).
        #
        # - allIntegrationSystemsAudited: indirect Legacy Task 3 ISU
        #   validation (each ISU has an Integration System; this lists
        #   all of them with audit metadata).
        # Targets to capture. Each entry is a dict so we can attach an
        # optional WHERE clause for data sources that have
        # filterIsRequired = true (Workday rejects unfiltered queries
        # against those with HTTP 400 "Specify a data source filter").
        target_aliases = [
            {"alias": "allWorkers",
             "why":   "Sanity check + worker shape"},
            {"alias": "oAuth20RefreshTokenDataSource",
             "why":   "Backs Task 5 API Client validation (active refresh tokens)"},
            {"alias": "allSystemAccountSignons",
             "why":   "DISCOVERY ONLY: filterIsRequired=true; we couldn't "
                      "determine the WQL syntax to invoke its named filters "
                      "via REST. Recorder still captures the metadata "
                      "(requiredParameters, dataSourceFilters) so a future "
                      "agent with Workday docs access can complete it. "
                      "For tenant config validation today use "
                      "allIntegrationSystemsAudited instead."},
            {"alias": "publicWebServices",
             "why":   "Backs Task 5 API Client SCOPE validation (WQL exposed?)"},
            {"alias": "allSecurityGroups",
             "why":   "Backs Legacy Task 3 ISSG validation"},
            {"alias": "allCustomReports",
             "why":   "Backs Legacy Task 8 RaaS report validation"},
            {"alias": "allIntegrationSystemsAudited",
             "why":   "Indirect Legacy Task 3 ISU validation"},
        ]

        for target in target_aliases:
            alias = target["alias"]
            why = target["why"]
            where_clause = target.get("where")
            print()
            print(f"  --- {alias} [{why}] ---")

            # Resolve alias -> WID using the catalog index. Workday's
            # detail endpoint addresses data sources by WID, not by
            # human-readable alias.
            row = sources_by_alias.get(alias)
            if not row:
                print(f"    Skipped: alias not in catalog (sources_by_alias has {len(sources_by_alias)} entries)")
                continue
            wid = row.get("id") or row.get("wid") or row.get("dataSourceId")
            if not wid:
                print(f"    Skipped: catalog row has no id/wid/dataSourceId. Keys: {sorted(row.keys())}")
                continue
            print(f"    Resolved alias -> WID: {wid}")

            # Step 3a: fetch the data source detail (descriptor, primary
            # business object, filterIsRequired flag).
            detail_url = f"{soap_host}/ccx/api/wql/v1/{tenant}/dataSources/{wid}"
            try:
                r = requests.get(
                    detail_url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    timeout=60,
                )
            except requests.RequestException as exc:
                print(f"    Detail endpoint ERROR: {exc!s}")
                continue
            if r.status_code != 200:
                print(f"    Detail endpoint -> {r.status_code}: {r.text[:200]}")
                continue
            try:
                detail = r.json()
            except ValueError:
                print(f"    Detail not JSON: {r.text[:200]}")
                continue
            print(f"    Detail OK. primaryBusinessObject: {detail.get('primaryBusinessObject', {}).get('descriptor')}")
            filter_required = detail.get("filterIsRequired", False)
            print(f"    filterIsRequired: {filter_required}")
            # Surface the prompt-parameter and filter metadata Workday
            # exposes for filterIsRequired data sources. These tell future
            # agents exactly which filter aliases and parameter names to
            # use when building queries against this source.
            req_params = detail.get("requiredParameters") or []
            ds_filters = detail.get("dataSourceFilters") or []
            if req_params:
                print(f"    requiredParameters ({len(req_params)}):")
                for p in req_params:
                    print(f"      - {p.get('alias')}  ({p.get('type')})  [{p.get('label')}]")
            if ds_filters:
                print(f"    dataSourceFilters ({len(ds_filters)}):")
                for fi in ds_filters:
                    print(f"      - {fi.get('alias')}  [{fi.get('descriptor')}]")
            if filter_required and not where_clause and not target.get("filter"):
                print(f"    WARNING: filterIsRequired=true but no 'filter'/'where' set in target_aliases for {alias}.")
                print(f"    Query will likely fail with 400 'Specify a data source filter'.")

            # Step 3a-fields: fetch the field catalog for this data source
            # via the /fields sub-resource. The detail endpoint above does
            # NOT include fields — they live at /dataSources/{wid}/fields.
            #
            # We only fetch ONE page (50 fields). Some data sources like
            # allWorkers have thousands of fields (every custom worker
            # attribute, related object, etc.) and paginating through all
            # of them takes minutes per source and bloats the cassette.
            # We only need 5 fields to build a SELECT — one page is plenty.
            fields_url = f"{soap_host}/ccx/api/wql/v1/{tenant}/dataSources/{wid}/fields"
            field_aliases: list[str] = []
            try:
                fr = requests.get(
                    fields_url,
                    params={"limit": 50, "offset": 0},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    timeout=60,
                )
            except requests.RequestException as exc:
                print(f"    Fields endpoint ERROR: {exc!s}")
                continue
            if fr.status_code != 200:
                print(f"    Fields endpoint -> {fr.status_code}: {fr.text[:200]}")
                continue
            try:
                fbody = fr.json()
            except ValueError:
                print(f"    Fields not JSON: {fr.text[:200]}")
                continue
            rows = fbody.get("data", [])
            ftotal = fbody.get("total", 0)
            if rows:
                print(f"    Sample field row: {rows[0]}")
            for f in rows:
                fa = f.get("alias")
                if fa:
                    field_aliases.append(fa)

            print(f"    Discovered {len(field_aliases)} field aliases (of {ftotal} total). First 10:")
            for fa in field_aliases[:10]:
                print(f"      - {fa}")
            if not field_aliases:
                print(f"    No field aliases discovered. Skipping query for {alias}.")
                continue

            # Step 3b: build a query using the first 5 field aliases.
            picked = field_aliases[:5]
            # Build the basic SELECT (no WHERE / no body params).
            select_clause = f"SELECT {', '.join(picked)} FROM {alias} LIMIT 5"

            def run_query(label: str, query: str, body_extras: dict | None = None,
                          url_params: dict | None = None) -> int:
                """POST a WQL query, print result, return status code."""
                payload: dict = {"query": query}
                if body_extras:
                    payload.update(body_extras)
                print(f"    [{label}]")
                print(f"      query:  {query}")
                if body_extras:
                    print(f"      body+:  {body_extras}")
                if url_params:
                    print(f"      url+:   {url_params}")
                try:
                    rr = requests.post(
                        wql_url,
                        params=url_params or {},
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                        },
                        timeout=60,
                    )
                except requests.RequestException as exc:
                    print(f"      ERROR: {exc!s}")
                    return -1
                print(f"      -> {rr.status_code}")
                if rr.status_code == 200:
                    try:
                        body = rr.json()
                        print(f"      success: total={body.get('total', '?')} rows_returned={len(body.get('data', []))}")
                    except ValueError:
                        print(f"      not JSON: {rr.text[:200]}")
                else:
                    try:
                        err = rr.json()
                        top = err.get("error", "(no top-level error)")
                        print(f"      error: {top}")
                        for nested in err.get("errors", []):
                            msg = nested.get("error", str(nested))
                            loc = nested.get("location", "")
                            loc_part = f" [{loc}]" if loc else ""
                            print(f"        - {msg}{loc_part}")
                    except ValueError:
                        print(f"      body[:300]: {rr.text[:300]}")
                return rr.status_code

            filter_required = detail.get("filterIsRequired", False)

            if not filter_required:
                # Simple case: no prompt parameters needed. Optional WHERE
                # clause from the target spec (none of the current 6 use it).
                where_part = f" WHERE {where_clause}" if where_clause else ""
                run_query("simple", f"SELECT {', '.join(picked)} FROM {alias}{where_part} LIMIT 5")
            else:
                # KNOWN LIMITATION (see module docstring): we couldn't
                # determine the WQL syntax to invoke filterIsRequired
                # data sources from the /data REST endpoint. We've
                # already captured the metadata that tells future
                # agents what's needed:
                #   - requiredParameters[]: typed inputs the data source
                #     declares (printed above as "requiredParameters (N)")
                #   - dataSourceFilters[]: named filters the data source
                #     exposes (printed above as "dataSourceFilters (N)")
                # Plus the WID and primaryBusinessObject. A future agent
                # with Workday's WQL REST API reference docs can fill in
                # the right query syntax (probably function-call FROM,
                # but we couldn't determine the value-literal syntax).
                #
                # We deliberately do NOT issue a query here — running
                # multiple known-failing probes just bloats the cassette
                # with HTTP 400 noise. The discovery output above is the
                # whole point of capturing this source.
                print(f"    SKIP query: filterIsRequired=true, see KNOWN LIMITATION in module docstring.")
                print(f"    Discovery metadata above is sufficient for a future agent to complete.")

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/workday_wql_admin.yaml")
    print("for any leftover identifying data before committing. The redactor")
    print("catches names, IDs, emails, tokens, and Workday-specific PII fields,")
    print("but eyeball is the safety net.")


if __name__ == "__main__":
    main()
