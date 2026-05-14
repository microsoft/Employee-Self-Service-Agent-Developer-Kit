# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Shared helpers for VCR.py recording wrappers.

Every record_*.py script in this directory uses build_cassette() to get a
pre-configured VCR instance that:

* Strips Authorization, Cookie, Set-Cookie, and ocp-apim-subscription-key
  headers from every recorded request and response.
* Replaces tenant-identifying values (GUIDs, org URL fragment, real names,
  real emails, employee/worker IDs, ISU usernames) in URLs and response
  bodies BEFORE the cassette is written to disk.
* Writes to tests/fixtures/cassettes/{name}.yaml.

The redaction substitutions are read from REDACT_TABLE below. The values on
the left should be **the real values your tenant emits** — edit this file
once per machine to add anything tenant-specific that's not on the default
list.

If a captured cassette still has unredacted PII after this pass, the
fallback is tests/captures/_redact.py which can be run on an existing
cassette file to apply additional substitutions.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Make the production source importable without a package install.
# Scope: FlightCheck only, plus the parts of the kit's shared auth.py
# that FlightCheck depends on. The MCP servers under src/mcp/ are out
# of scope for this test suite.
REPO_ROOT = Path(__file__).resolve().parents[2]
KIT_ROOT = REPO_ROOT / "solutions" / "ess-maker-skills"
SCRIPTS_ROOT = KIT_ROOT / "scripts"

if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))


CASSETTE_DIR = REPO_ROOT / "tests" / "fixtures" / "cassettes"
RAW_CASSETTE_DIR = CASSETTE_DIR / ".raw"


def chdir_kit_root() -> None:
    """Change cwd to solutions/ess-maker-skills/.

    The kit's production scripts use relative paths (LOCAL_STATE_DIR =
    ".local") and assume cwd is the kit root, not the repo root. Recording
    wrappers must call this before invoking production code or auth.py
    will look for .local/config.json + .local/.token_cache.bin in the
    wrong directory.
    """
    os.chdir(str(KIT_ROOT))


def get_dataverse_url() -> str:
    """Resolve the Dataverse env URL for a recording session.

    Resolution order:
      1. ``ESS_DATAVERSE_URL`` environment variable.
      2. ``dataverseEndpoint`` field in
         ``solutions/ess-maker-skills/.local/config.json`` (populated by
         the kit's ``/setup`` flow).

    If neither is set, prints a clear error pointing the operator at the
    env var (so the recording wrappers don't require ``/setup`` to have
    been run) and exits with code 1.
    """
    url = os.environ.get("ESS_DATAVERSE_URL", "").strip()
    if url:
        return url

    config_path = KIT_ROOT / ".local" / "config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cfg = {}
        url = (cfg.get("dataverseEndpoint") or "").strip()
        if url:
            return url

    print("ERROR: no Dataverse URL available.")
    print()
    print("Set the URL via environment variable:")
    print('  $env:ESS_DATAVERSE_URL = "https://orgb78b4a3b.crm.dynamics.com"')
    print()
    print("Or run the kit's /setup flow in your Copilot CLI chat to populate")
    print(f"  {config_path}")
    sys.exit(1)


def get_workday_test_employee_id() -> str | None:
    """Read WORKDAY_TEST_EMP_ID from env or .local/config.json. Optional."""
    val = os.environ.get("WORKDAY_TEST_EMP_ID", "").strip()
    if val:
        return val
    config_path = KIT_ROOT / ".local" / "config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            return cfg.get("workdayTestEmployeeId") or None
        except (OSError, json.JSONDecodeError):
            return None
    return None


# ────────────────────────────────────────────────────────────────────────
# Redaction table
#
# These strings get find-and-replaced in URLs, request bodies, response
# bodies, and any other text VCR captures. The mapping is intentionally
# conservative: it only redacts values that are clearly identifying.
#
# To add a tenant-specific value (e.g. your own org URL fragment, your test
# tenant GUID), edit this table on your local machine before running a
# recording wrapper. Don't commit tenant-specific entries here.
# ────────────────────────────────────────────────────────────────────────

REDACT_TABLE: dict[str, str] = {
    # Tokens that may end up in bodies (response error_descriptions sometimes
    # echo bearer tokens back).
    "Bearer ": "Bearer ",  # placeholder; bearer tokens are stripped via header filtering
    # Real org URL fragment (read from .local/config.json at runtime, see
    # _read_real_dataverse_url below). The placeholder here is a sentinel
    # — runtime substitution overwrites it with the real value.
    "__REAL_ORG_FRAGMENT__": "orgmocktenant",
}


# Regex-based substitutions for things that have a stable shape but vary
# per record (employee IDs, worker IDs, tenant GUIDs we don't know in
# advance). Applied AFTER the literal REDACT_TABLE.
REDACT_REGEX: list[tuple[re.Pattern[str], str]] = [
    # WS-Security password element. Scrub the contents regardless of
    # whatever the caller passed. Any XML namespace prefix matches
    # (wsse:, ns0:, etc.) since we recorded multiple variants in the wild.
    # CRITICAL: this rule must come FIRST so password contents are gone
    # before any other regex (e.g. the GUID rule) can capture parts of
    # them. multiline + DOTALL because real cassettes wrap long lines.
    (
        re.compile(
            r"<([\w-]+:)?Password(\s[^>]*)?>.*?</([\w-]+:)?Password>",
            re.DOTALL,
        ),
        "<wsse:Password>REDACTED_WSSE_PASSWORD</wsse:Password>",
    ),
    # WS-Security username element. The wrapper appends @<tenant> so
    # most usernames will have an @ and the email regex would catch
    # them — but bare ISU usernames (no @ in the original input) would
    # not, so we belt-and-braces scrub the element here too.
    (
        re.compile(
            r"<([\w-]+:)?Username(\s[^>]*)?>.*?</([\w-]+:)?Username>",
            re.DOTALL,
        ),
        "<wsse:Username>REDACTED_WSSE_USERNAME</wsse:Username>",
    ),
    # Microsoft tenant / object GUIDs in URL paths and bodies.
    # Replaces every GUID with a stable fake. This is aggressive — if you
    # need to keep specific GUIDs for a test, exempt them by editing the
    # cassette by hand after recording.
    #
    # Boundary uses negative lookaround for "not preceded/followed by hex
    # or dash" rather than \b. Plain \b fails when the GUID is followed
    # by `_` (PowerShell-pasted SKU IDs like `{tenantGuid}_{skuGuid}`)
    # because `_` is a word character — so \b doesn't fire between the
    # final hex char and `_`. The lookaround treats `_` as a boundary,
    # closing a real PII leak we hit in flightcheck_graph.yaml.
    (
        re.compile(
            r"(?<![0-9a-fA-F-])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9a-fA-F-])"
        ),
        "00000000-0000-0000-0000-000000001111",
    ),
    # Workday WIDs: 32-char hex, sometimes prefixed by "WID="
    (re.compile(r"\b[0-9a-fA-F]{32}\b"), "0" * 32),
    # Email addresses → mock.user@contoso.com
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "mock.user@contoso.com",
    ),
    # Dataverse org subdomains: orgb78b4a3b, org4e28026f, etc. The leading
    # "org" + 6-12 hex chars is the Microsoft-assigned tenant fragment.
    # Bound by word boundaries so we don't match "Microsoft.Org.Something".
    (re.compile(r"\borg[0-9a-f]{6,12}\b"), "orgmocktenant"),
    # ServiceNow dev instance hostnames: dev184242.service-now.com etc.
    (
        re.compile(r"\bdev\d{4,8}\.service-now\.com\b", re.IGNORECASE),
        "devmocktenant.service-now.com",
    ),
    # ServiceNow instance short names appearing in connectionParameters
    # (e.g. "instance":"Dev184242"). Bound to start with "Dev" + digits +
    # word boundary so we don't accidentally match "Devops" or "Develop".
    (re.compile(r"\bDev\d{4,8}\b"), "DevMockInstance"),
    # SuccessFactors demo tenant hostnames: apisalesdemo8.successfactors.com
    (
        re.compile(r"\bapisalesdemo\d+\.successfactors\.com\b", re.IGNORECASE),
        "apisalesdemomock.successfactors.com",
    ),
    # SuccessFactors company IDs: "SFCPART001804" etc.
    (re.compile(r"\bSFCPART\d{4,8}\b"), "SFCPARTMOCK000"),
    # Dataverse uniqueName fragments: "unq2012fca7bd1bf111afbf6045bd056",
    # "unqc458128aac1cf111afc0000d3a5cb" — start with "unq" followed by hex.
    (re.compile(r"\bunq[0-9a-f]{20,40}\b"), "unqmocktenant"),
    # Power Platform scale group identifiers: "NAMCRMLIVESG731", "NAMCRMLIVESG691".
    (re.compile(r"\b(NAM|EUR|APAC|OCE)CRMLIVESG\d{3}\b"), "MOCKCRMLIVESG000"),
    # PVA gateway suffixes: "us-il107.gateway.prod.island", "ca-il101.gateway.prod.island"
    # — the IL number identifies a specific cluster within a region.
    (
        re.compile(r"\b([a-z]{2})-il\d+\.gateway\.prod\.island\b"),
        r"\1-il000.gateway.prod.island",
    ),
    # OAuth tokens in form-urlencoded bodies. The JSON-key scrub above
    # handles tokens in JSON response bodies, but the kit POSTs token
    # exchange requests with form-urlencoded bodies — refresh_token=xxx
    # — which JSON scrubbing misses. The refresh token in particular is
    # a long-lived bearer; it MUST be scrubbed.
    (
        re.compile(r"\brefresh_token=[A-Za-z0-9._\-]+"),
        "refresh_token=REDACTED_OAUTH_REFRESH_TOKEN",
    ),
    (
        re.compile(r"\baccess_token=[A-Za-z0-9._\-]+"),
        "access_token=REDACTED_OAUTH_ACCESS_TOKEN",
    ),
    (
        re.compile(r"\bid_token=[A-Za-z0-9._\-]+"),
        "id_token=REDACTED_OAUTH_ID_TOKEN",
    ),
    (
        re.compile(r"\bclient_secret=[A-Za-z0-9._\-]+"),
        "client_secret=REDACTED_CLIENT_SECRET",
    ),
    # Long JWTs (3 base64url-encoded segments separated by dots, each
    # at least 16 chars). Catches tokens that snuck into URLs, logs, or
    # JSON values whose key didn't match the scrub list.
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b"),
        "REDACTED_JWT",
    ),
]


# Workday SOAP responses include large amounts of PII inside named XML
# elements. The text-level GUID / email regex catches some of it but
# not most. These patterns scrub the contents of named PII elements
# regardless of namespace prefix. Each entry maps element name → fixed
# replacement value.
#
# IMPORTANT: applied AFTER REDACT_REGEX so the explicit element rules
# always win. If you find a Workday element leaking real data, add it
# here.
WORKDAY_PII_ELEMENTS: dict[str, str] = {
    "First_Name": "Mock",
    "Last_Name": "User",
    "Middle_Name": "",
    "Preferred_Name": "Mock User",
    "Formatted_Name": "Mock User",
    "Reporting_Name": "Mock User",
    "Full_Name": "Mock User",
    "Worker_Descriptor": "Mock User",
    "Phone_Number": "555-555-0100",
    "International_Phone_Code": "1",
    "Phone_Extension": "",
    "Email_Address": "mock.user@contoso.com",
    "Address_Line_Data": "1 Mock Street",
    "Municipality": "Mocktown",
    "City": "Mocktown",
    "Postal_Code": "00000",
    "Region": "MC",
    "Hire_Date": "2020-01-01",
    "Original_Hire_Date": "2020-01-01",
    "Continuous_Service_Date": "2020-01-01",
    "Birth_Date": "1990-01-01",
    "End_Employment_Date": "",
    "Termination_Date": "",
    "Worker_ID": "MOCK_EMP_001",
    "User_ID": "mockuser",
    "ID_Value": "MOCK_ID",
    "National_ID_Value": "XXX-XX-XXXX",
    "Identification_ID": "MOCK_ID",
    "Position_ID": "POS-MOCK-001",
}


# Workday also embeds PII as attributes on element opening tags
# (e.g. <wd:Worker wd:Formatted_Name="Sarah Connor" wd:Reporting_Name="Connor, Sarah">).
# These attribute names need their VALUES scrubbed regardless of which
# element they appear on. Each entry maps attribute local-name → fixed
# replacement value.
WORKDAY_PII_ATTRIBUTES: dict[str, str] = {
    "Formatted_Name": "Mock User",
    "Reporting_Name": "Mock User",
    "Descriptor": "Mock User",
}


# Pattern that catches `<wd:ID wd:type="Employee_ID">21005</wd:ID>` —
# Workday uses attribute-based discriminators for various ID types
# (Employee_ID, Position_ID, Manager_ID, etc.) rather than separate
# element names. Scrub all of them.
_WORKDAY_TYPED_ID_PATTERN = re.compile(
    r'(<[\w-]+:?ID\s+[\w-]+:?type="(Employee_ID|Position_ID|Manager_ID|'
    r'Organization_Reference_ID|Cost_Center_Reference_ID|Company_Reference_ID|'
    r'Supervisory_Organization_ID|National_ID|Passport_ID|Visa_ID|'
    r'Government_ID|Personnel_Number)"\s*>)([^<]*)(</[\w-]+:?ID>)',
    re.DOTALL,
)


# JSON keys whose values get replaced wholesale with a fixed mock value
# regardless of where they appear in the response structure. Use this for
# fields that are reliably identifying (real names, real addresses, real
# tenant friendly-names) and where we don't need to preserve exact value
# shape for the kit's behavior.
#
# Each entry maps a JSON key (case-sensitive) to a replacement value. None
# means "set to null".
SCRUB_JSON_KEYS: dict[str, Any] = {
    # Tenant identity
    "displayName": "Mock Display Name",
    "friendlyName": "Mock Friendly Name",
    "uniqueName": "unqmocktenant",
    "domainName": "orgmocktenant",
    # Tenant physical address (Graph /organization)
    "street": "1 Mock Street",
    "city": "Mocktown",
    "postalCode": "00000",
    "state": "mc",
    "countryLetterCode": "MC",
    # User identifiers — names and UPNs on createdBy / lastModifiedBy
    "userPrincipalName": "mock.user@contoso.com",
    "accountName": "mock.user@contoso.com",
    "email": "mock.user@contoso.com",
    "mail": "mock.user@contoso.com",
    "mailNickname": "mock.user",
    # Tenant verified domains (Graph /organization). Real responses list
    # the customer's vanity + .onmicrosoft.com + any federated domains —
    # all identifying. Replace with a single mock entry preserving shape.
    "verifiedDomains": [
        {
            "capabilities": "Email,OfficeCommunicationsOnline",
            "isDefault": True,
            "isInitial": True,
            "name": "mocktenant.onmicrosoft.com",
            "type": "Managed",
        }
    ],
    # Tenant marketing / notification mailing lists (Graph /organization).
    "marketingNotificationEmails": [],
    "technicalNotificationMails": ["mock.user@contoso.com"],
    "securityComplianceNotificationMails": [],
    "securityComplianceNotificationPhones": [],
    "businessPhones": [],
    # Workday REST API responses use camelCase JSON. The "descriptor" field
    # is Workday's human-readable display string for almost any object
    # (worker, supervisory org, job profile, location, etc.) and routinely
    # contains real worker names like "Sarah Connor" or org names like
    # "Global Support - USA Group". Aggressive scrub.
    "descriptor": "Mock Descriptor",
    "firstName": "Mock",
    "lastName": "User",
    "middleName": "",
    "preferredName": "Mock User",
    "primaryWorkEmail": "mock.user@contoso.com",
    "primaryHomeEmail": "mock.user@contoso.com",
    "primaryWorkPhone": "+1 555-555-0100",
    "primaryHomePhone": "+1 555-555-0100",
    "phoneNumber": "+1 555-555-0100",
    "emailAddress": "mock.user@contoso.com",
    "businessTitle": "Mock Title",
    "jobTitle": "Mock Title",
    # Workday Worker ID camelCase REST equivalent of the SOAP
    # `Worker_ID` element. Direct PII (real employee number).
    "workerId": "MOCK_EMP_001",
    "employeeId": "MOCK_EMP_001",
    "employeeID": "MOCK_EMP_001",
    # Bare "phone" field appears in some Workday REST shapes alongside
    # the more-specific primaryWorkPhone / primaryHomePhone fields.
    "phone": "+1 555-555-0100",
    # Date-of-birth is HIGHLY sensitive — should never land in a cassette.
    "dateOfBirth": "1990-01-01",
    "birthDate": "1990-01-01",
    # Free-form address text fields. Workday returns multi-line
    # addresses in primaryWorkAddressText / primaryHomeAddressText.
    "primaryWorkAddressText": "1 Mock Street, Mocktown, MC 00000",
    "primaryHomeAddressText": "1 Mock Street, Mocktown, MC 00000",
    "addressLine": "1 Mock Street",
    # Numeric-but-identifying fields. yearsOfService combined with
    # other context (department, role) can re-identify a specific
    # person even if names and IDs are scrubbed.
    "yearsOfService": 5,
    # OAuth tokens — these MUST be scrubbed. The Workday OAuth token
    # exchange response body contains both access_token (full JWT, decodes
    # to reveal client_id and other tenant info) and refresh_token (long-
    # lived bearer that re-exchanges for fresh access tokens). Same for
    # id_token if present.
    "access_token": "REDACTED_OAUTH_ACCESS_TOKEN",
    "refresh_token": "REDACTED_OAUTH_REFRESH_TOKEN",
    "id_token": "REDACTED_OAUTH_ID_TOKEN",
    # Workday refers to the worker URL via "href" — these contain the
    # internal hex IDs we already scrub via the WID regex, but the
    # path also encodes the tenant. The org/tenant gets scrubbed by
    # the regex already; href values are fine to leave alone otherwise.
}


# Headers that get stripped completely (replaced with REDACTED).
SCRUB_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-ms-aadtoken",
    "ocp-apim-subscription-key",
    "x-ms-correlation-id",   # tenant-correlated trace id
    "x-ms-client-request-id",
    "x-ms-request-id",
    "x-ms-routing-request-id",
    "x-ms-service-request-id",
    "authactivityid",        # Dataverse-emitted activity id
    "req_id",                # Dataverse-emitted request id
    "x-source",              # Dataverse-emitted opaque routing tokens
    "ms-cv",                 # Microsoft Correlation Vector
}


def _read_real_dataverse_url() -> str | None:
    """Pull the real org URL fragment so the redactor knows what string
    to substitute. Returns the fragment (e.g. "orgb78b4a3b") or None.

    Resolution order matches get_dataverse_url():
      1. ``ESS_DATAVERSE_URL`` environment variable.
      2. ``dataverseEndpoint`` in solutions/ess-maker-skills/.local/config.json.
    """
    candidates: list[str] = []

    env_url = os.environ.get("ESS_DATAVERSE_URL", "").strip()
    if env_url:
        candidates.append(env_url)

    config_path = REPO_ROOT / "solutions" / "ess-maker-skills" / ".local" / "config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            ep = (cfg.get("dataverseEndpoint") or "").strip()
            if ep:
                candidates.append(ep)
        except (OSError, json.JSONDecodeError):
            pass

    for url in candidates:
        m = re.match(r"https?://([^.]+)\.", url)
        if m:
            return m.group(1)
    return None


def _read_real_workday_tenant() -> str | None:
    """Pull the real Workday tenant name (the path segment in the SOAP
    URL after /ccx/service/) so the redactor can scrub it. Reads from
    the ``WORKDAY_TENANT_NAME`` env var only — the kit doesn't persist
    Workday tenant info to disk."""
    val = os.environ.get("WORKDAY_TENANT_NAME", "").strip()
    return val or None


def _scrub_json_keys(obj: Any) -> Any:
    """Walk a JSON-decoded structure and replace values for any key in
    SCRUB_JSON_KEYS with the corresponding fixed mock value.

    Recurses into dicts and lists. Leaves everything else alone.
    """
    if isinstance(obj, dict):
        return {
            k: (SCRUB_JSON_KEYS[k] if k in SCRUB_JSON_KEYS else _scrub_json_keys(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_scrub_json_keys(item) for item in obj]
    return obj


def _redact_text(text: str) -> str:
    """Apply REDACT_TABLE + REDACT_REGEX to a string. Used for URLs,
    headers, and any non-JSON body content."""
    if not text:
        return text
    real_org = _read_real_dataverse_url()
    if real_org and real_org != "orgmocktenant":
        text = text.replace(real_org, "orgmocktenant")
    real_workday_tenant = _read_real_workday_tenant()
    if real_workday_tenant and real_workday_tenant != "mocktenant_xx":
        # Workday tenant names appear in SOAP URLs and various reference
        # paths. Scrub them just like the Dataverse org fragment.
        text = text.replace(real_workday_tenant, "mocktenant_xx")
    for src, dst in REDACT_TABLE.items():
        if src.startswith("__"):  # skip sentinels
            continue
        if src and src != dst:
            text = text.replace(src, dst)
    for pat, dst in REDACT_REGEX:
        text = pat.sub(dst, text)
    # Workday-specific XML element scrubbing. Done after the generic
    # regex pass so that element contents take precedence over any
    # patterns the generic pass might have partially matched inside
    # element bodies.
    for element_name, replacement in WORKDAY_PII_ELEMENTS.items():
        # Match <prefix:ElementName ...>contents</prefix:ElementName>
        # with any namespace prefix and any attributes.
        pattern = re.compile(
            rf"(<[\w-]+:?{element_name}(?:\s[^>]*)?>)[^<]*(</[\w-]+:?{element_name}>)",
            re.DOTALL,
        )
        # Use a lambda so the replacement value isn't interpreted as a
        # regex template (e.g. "1" becoming \11 = invalid backreference).
        text = pattern.sub(lambda m, r=replacement: m.group(1) + r + m.group(2), text)
    # Workday typed-ID elements (<wd:ID wd:type="Employee_ID">...</wd:ID>).
    text = _WORKDAY_TYPED_ID_PATTERN.sub(
        lambda m: m.group(1) + "MOCK_ID" + m.group(4), text
    )
    # Workday PII attributes (e.g. wd:Formatted_Name="Sarah Connor" inside
    # an opening tag). Match attribute name + value regardless of which
    # element it's on.
    for attr_name, replacement in WORKDAY_PII_ATTRIBUTES.items():
        # Match: prefix:attr_name="..."   (with any namespace prefix,
        # any double-quoted value)
        pattern = re.compile(rf'([\w-]+:?{attr_name})="[^"]*"')
        text = pattern.sub(
            lambda m, r=replacement: f'{m.group(1)}="{r}"', text
        )
    return text


def _redact_body_text(body: str) -> str:
    """Apply both JSON-key scrubbing (if body parses as JSON) and text
    regex/literal redaction. Falls back to text-only for non-JSON bodies
    (e.g. SOAP envelopes, HTML error pages).
    """
    if not body:
        return body
    text = body
    if body.strip().startswith(("{", "[")):
        try:
            parsed = json.loads(body)
            scrubbed = _scrub_json_keys(parsed)
            text = json.dumps(scrubbed, separators=(",", ":"))
        except json.JSONDecodeError:
            pass
    return _redact_text(text)


def _scrub_headers(headers: dict[str, list[str] | str]) -> dict[str, list[str] | str]:
    """Replace sensitive header values with REDACTED, and apply text
    redaction to every other header value so leaked GUIDs / emails /
    org names get scrubbed even when the header itself isn't on the
    SCRUB list.
    """
    cleaned: dict[str, list[str] | str] = {}
    for k, v in headers.items():
        if k.lower() in SCRUB_HEADERS:
            cleaned[k] = ["REDACTED"] if isinstance(v, list) else "REDACTED"
            continue
        if isinstance(v, list):
            cleaned[k] = [_redact_text(item) if isinstance(item, str) else item for item in v]
        elif isinstance(v, str):
            cleaned[k] = _redact_text(v)
        else:
            cleaned[k] = v
    return cleaned


def _before_record_request(request: Any) -> Any:
    """vcrpy hook: scrub headers + redact URL + redact request body."""
    request.headers = _scrub_headers(dict(request.headers))
    request.uri = _redact_text(request.uri)
    if getattr(request, "body", None):
        body = request.body
        if isinstance(body, bytes):
            try:
                body = body.decode("utf-8")
                request.body = _redact_body_text(body).encode("utf-8")
            except UnicodeDecodeError:
                pass  # leave binary bodies alone
        elif isinstance(body, str):
            request.body = _redact_body_text(body)
    return request


def _before_record_response(response: dict[str, Any]) -> dict[str, Any]:
    """vcrpy hook: scrub headers + redact response body."""
    if "headers" in response:
        response["headers"] = _scrub_headers(response["headers"])
    body = response.get("body", {})
    if isinstance(body, dict) and "string" in body:
        raw = body["string"]
        if isinstance(raw, bytes):
            try:
                decoded = raw.decode("utf-8")
                body["string"] = _redact_body_text(decoded).encode("utf-8")
            except UnicodeDecodeError:
                pass
        elif isinstance(raw, str):
            body["string"] = _redact_body_text(raw)
    return response


def build_cassette(name: str) -> Any:
    """
    Return a vcrpy.VCR instance configured with our standard redaction +
    cassette path conventions. Use as:

        vcr = build_cassette("dataverse_whoami")
        with vcr.use_cassette():
            # call production code that issues HTTP requests
            ...

    Cassettes write to tests/fixtures/cassettes/{name}.yaml.
    """
    try:
        import vcr
    except ImportError:
        print("ERROR: vcrpy not installed. Run: pip install -r requirements-dev.txt")
        sys.exit(1)

    CASSETTE_DIR.mkdir(parents=True, exist_ok=True)
    cassette_path = CASSETTE_DIR / f"{name}.yaml"

    return vcr.VCR(
        cassette_library_dir=str(CASSETTE_DIR),
        path_transformer=vcr.VCR.ensure_suffix(".yaml"),
        record_mode="new_episodes",
        match_on=("method", "scheme", "host", "port", "path", "query"),
        filter_headers=list(SCRUB_HEADERS),
        before_record_request=_before_record_request,
        before_record_response=_before_record_response,
        decode_compressed_response=True,
    ).use_cassette(str(cassette_path))


def announce(scenario: str) -> None:
    """Standard preamble printed by every record_*.py wrapper."""
    print(f"=== Recording cassette: {scenario} ===")
    print(f"Output: tests/fixtures/cassettes/{scenario}.yaml")
    print()
    print("This script will make REAL network calls to your tenant.")
    print("Authentication uses your existing .local/.token_cache.bin.")
    print("Headers + tokens + tenant GUIDs are scrubbed BEFORE write.")
    print()
    print("After recording, review the cassette by hand for any leftover")
    print("tenant-specific data (real names, real ticket numbers, etc.) and")
    print("commit it to tests/fixtures/cassettes/.")
    print()


def confirm_or_exit() -> None:
    """Prompt the operator to confirm before hitting the network."""
    if os.environ.get("ESS_RECORD_NO_CONFIRM") == "1":
        return
    answer = input("Proceed with recording? [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        print("Aborted.")
        sys.exit(0)
