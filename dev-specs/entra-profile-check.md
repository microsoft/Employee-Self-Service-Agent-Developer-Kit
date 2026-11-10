# Entra profile coverage for ESS personalization

## Purpose and scope

`AUTH-PROFILE-001` checks standard Entra attributes for ESS knowledge personalization. It measures tenant coverage when permitted; otherwise it checks the signed-in maker's own profile. Gaps and access limitations are non-blocking.

Guidance connects coverage to personalization and explains how to enrich relevant profile data. This scalar-attribute diagnostic does not establish complete personalization readiness.

| Attributes checked | Interpretation |
| --- | --- |
| `usageLocation` | Licensing-country coverage, not verified HR country or confirmation of the agent's runtime location source. |
| `preferredLanguage` | Profile data relevant to language-specific knowledge answers. |
| `country`, `officeLocation`, `jobTitle`, `department`, `employeeType`, `employeeId`, `employeeHireDate` | Additional profile coverage; no specific runtime experience or mandatory field requirement is asserted. |

Manager relationships, custom attributes, and HR-source comparison/applicability are excluded. An Entra gap need not be a runtime gap when HR supplies the value.

## Access, fallback and limits

FlightCheck uses its own Graph client, not the agent's runtime permissions. Tenant reads require existing app consent for `User.Read.All`; the maker need not hold an administrator role.

If that consent is unavailable or a tenant read is denied, read the same nine attributes from `/me` using `$select` and delegated `User.Read`, for the same verified account and tenant. Self-profile sign-in or consent follows tenant policy; never request new directory-read consent or broader permissions.

Fallback is access-driven, not role-driven, and affects only this checkpoint. It must not downgrade other checks' Graph clients. Other authentication/identity failures, network errors, timeouts and invalid data remain errors.

Tenant mode reads Member accounts, including disabled and service accounts, not an employee roster. Sequential **999-account pages** stop at completion or **10,000 accounts**; unused final-page records are discarded. Reports label **Tenant coverage** or **Sample coverage**, with the checked count, `isSample`, and `populationComplete`. Graph page order is not random sampling.

The **30-second total data-read budget** spans tenant and fallback requests, retries and aggregation; authentication is excluded and fallback does not reset it. Each page shares three retries across retryable HTTP and transport failures, honoring backoff and `Retry-After` within the remaining budget.

## Coverage and outcomes

Count nonblank values as `available`, null/blank as `empty`, and omitted properties as `notReturned`. Tenant coverage is `available / usersChecked * 100`; own-profile states use the same presence rules.

| ADK result | Condition |
| --- | --- |
| `Passed` | Tenant scan: every selected attribute has at least **95%** coverage and no omitted properties, evaluated before two-decimal display rounding. |
| `Warning` - coverage | Tenant scan: measured gap or omitted property; personalization and enrichment guidance. |
| `Warning` - own profile only | Tenant access is unavailable; self-profile read succeeds. Show Available, Empty or Not returned per attribute, without percentages or the tenant threshold. Always Warning, even if all nine attributes are available. |
| `Warning` - not checked | Tenant access and self-profile read permission are unavailable; neither profile availability nor tenant coverage is verified. |
| `Error` | Other authentication/identity failures; request or budget errors; invalid responses; empty tenant populations; duplicate or out-of-population tenant records. |

Access-limited findings retain ADK's existing Warning status, not a new `Not verified` type. `coverageVerified: false` means tenant coverage is unverified; `profileVerified: true` identifies a successful self-profile read. DA coverage accounting treats fallback as limited, not a completed tenant scan.

Discard any partial tenant results before fallback. Failed or expired reads never produce coverage figures. Focused FlightCheck warnings exit `0`; errors are nonzero. Other profile checks retain their existing gates.

## Report contract

One HTML/JSON finding shows either tenant counts, percentages and sample metadata, or **Own profile only** with this explanation:

> Tenant-wide directory-read access was unavailable for this run. Only your signed-in profile was checked; tenant-wide attribute coverage was not calculated.

Own-profile evidence contains `scope: "me"`, `usersChecked: 1`, `profileVerified: true`, `coverageVerified: false`, and attribute availability states, without percentages or tenant-population/sample claims. If self-profile permission is also unavailable, report **Not checked** for both modes.

Guidance links missing fields to potential personalization benefits and existing Entra/HR-to-Entra update processes. It distinguishes own-profile enrichment from tenant validation and recommends neither new HR-system setup in ESS nor placeholder values.

Coverage evidence excludes profile values, user IDs, and tokens; telemetry contains outcomes only. Presence proves neither correctness nor runtime use. `hrCountryComparison` remains `NotApplicable`.

## Entry points and validation

The checkpoint runs in full/authentication FlightChecks and selected-DA diagnostics, with the same automatic fallback in each. The shared standalone command remains unchanged: it defaults to `--scope me` with `User.Read`; explicit `--scope tenant` does not fall back. Only standalone supports `--attributes`. Target selection uses `--tenant-id` and `--preferred-username`.

```powershell
python scripts\flightcheck\cli.py --checkpoint AUTH-PROFILE-001 --tenant-id '<tenant-guid>' --preferred-username '<work-account>' --output .local\entra-flightcheck --no-open
python scripts\check_entra_profile.py --scope me --tenant-id '<tenant-guid>' --preferred-username '<work-account>'
```

Commands run from `solutions\ess-maker-skills`. Standalone exit codes are `0` for passed checks, `1` for either warning, and `2` for errors; `--output` saves its JSON report.

Tests cover tenant thresholds and limits; fallback after consent/read denial; populated, empty and omitted self-profile fields; both reads denied; identity/error guards; shared deadlines; unchanged standalone behavior; and full/checkpoint/profile parity. Live validation covers tenant and own-profile fallback HTML/JSON; mocked tests cover both reads denied.

API contracts: [Graph schema](https://graph.microsoft.com/v1.0/$metadata), [Get user](https://learn.microsoft.com/en-us/graph/api/user-get?view=graph-rest-1.0), [List users](https://learn.microsoft.com/en-us/graph/api/user-list?view=graph-rest-1.0).
