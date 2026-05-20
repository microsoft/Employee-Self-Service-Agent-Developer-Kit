# Workday SSO Test Flow Template

A Power Automate flow template that helps customers validate Entra SSO
permissions on the Workday `OAuthUser` connection before deploying the
Employee Self-Service (ESS) agent. The flow performs a lightweight
`Get_Workers_Request` SOAP call as the test user and confirms that the
user has the correct Workday security domain access for ESS.

This template is **reference content** — it is not deployed automatically
by any kit script. Customers import it manually in Power Automate.

## When to use this

Run this flow once after configuring the Workday connectors and SSO, and
once again for every new test user before granting them access to ESS.

If the flow fails, the response payload identifies which security
domain is missing or misconfigured. Common failures:

- The user is not in the Workday security group that ESS requires.
- The `OAuthUser` connection is not using Entra ID Integrated auth (the
  flow will fail with a `403` or empty `Worker` element).
- The `Get_Workers` operation is not exposed to the user's domain
  security policy.

## Files

| File | Purpose |
|---|---|
| [`sso-test-flow-template.json`](./sso-test-flow-template.json) | Power Automate flow definition + setup instructions + permissions-tested matrix. |

The JSON's `flow_setup_instructions`, `manual_creation_guide`,
`soap_request_readable`, and `permissions_tested` blocks are
self-contained — open the file in any editor for the full reference.

## Quick setup

1. Open [Power Automate](https://make.powerautomate.com) and select
   your ESS environment.
2. Create a new **Instant cloud flow** with an HTTP Request trigger.
   The trigger schema is in the JSON under
   `manual_creation_guide.trigger.schema`.
3. Add a **Workday SOAP — Execute SOAP operation (Preview)** action and
   point it at your `OAuthUser` connection (Entra ID Integrated auth).
4. Paste the SOAP body from the JSON's `soap_request_readable.xml`
   block, replacing the `@{triggerBody()?[...]}` expressions with the
   trigger inputs.
5. Add a **Response** action that returns the SOAP result.
6. Save the flow and copy the HTTP trigger URL.
7. Run the flow with a real test user's UPN. A `200` with a populated
   `Worker` element confirms SSO + permissions are wired correctly.

## Security domains tested

The `Get_Workers_Request` shape in the template exercises the following
Workday security domains. The full list lives in the JSON under
`permissions_tested.domains`:

- **Worker Data: Worker ID** — minimum auth gate.
- **Worker Data: Personal Information (Self)** — name, contact info.
- **Worker Data: National Identifiers / Government IDs** —
  identity-related fields.
- **Worker Data: Employment Information** — hire date, position.
- **Worker Data: Current Staffing Information** — cost center, company.
- **Person Data: Emergency Contacts**.
- **Worker Data: Qualifications / Skills and Experience**.

## Related

- [ESS Workday integration setup](../../reference/ess-docs/integrations/workday.md)
- [ESS Workday extensibility patterns](../../reference/ess-docs/integrations/workday-extensibility.md)
- Workday REST endpoints diagnostic:
  `solutions/ess-maker-skills/scripts/diagnostics/test_workday_rest_endpoints.py`
  (covers the REST-side connector validation; this template covers the
  SOAP-side SSO validation).
