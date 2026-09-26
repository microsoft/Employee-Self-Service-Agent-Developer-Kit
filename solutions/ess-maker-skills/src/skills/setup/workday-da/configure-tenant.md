<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Phase 3 - Workday administrator

This phase never modifies Workday. The skill generates one handoff, validates
the administrator's non-secret response, derives deterministic endpoints, and
records evidence. All Workday tenant changes are performed by the Workday
administrator.

Generate one administrator handoff:

```powershell
python scripts/workday_connect.py workday-admin-packet
```

Show the packet once as a single ordered task list. Do not split it into
repeated confirmations or rerun manual-only FlightChecks that merely repeat
the same instructions.

The Workday administrator must:

1. Identify the currently enabled SAML identity-provider row and confirm its
   Service Provider ID. Stop if it belongs to another federation.
2. Upload the active Entra SAML signing certificate and compare its validity
   dates with Workday.
3. Set the exact Service Provider ID to
   `http://www.workday.com/{workdayTenant}`. This is not the
   `api://{entraAppId}` Application ID URI.
4. Enable OAuth 2.0 Clients and SAML in Tenant Setup - Security.
5. Register the signed-in employee API client with Core Payroll,
   Organizations and Roles, Staffing, Time Off and Leave, and Include Workday
   Owned Scope.
6. Verify an active authentication policy allows SAML for the intended
   employees without replacing existing administrator or network safeguards.

Collect one response form containing only:

- enabled Service Provider ID;
- certificate Valid From and Valid To dates;
- Workday OAuth client ID;
- OAuth token URL;
- REST base URL ending at `/ccx/api`;
- SOAP base URL;
- authentication-policy outcome.

Never collect a secret, password, token, cookie, certificate body, or private
key. Pass the response once:

```powershell
python scripts/workday_connect.py record-workday-admin --response-json '{...}'
```

The controller validates the Service Provider ID, HTTPS endpoints, and exact
REST base suffix, then records the non-secret identifiers, endpoints, and
evidence atomically. If the administrator is not available, stop here; rerun
`workday-admin-packet` later to regenerate the same handoff without losing
prior progress.
