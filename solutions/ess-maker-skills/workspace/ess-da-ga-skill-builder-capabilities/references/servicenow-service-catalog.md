# ServiceNow service catalog

What a skill or tool needs to know to browse and order from the ServiceNow service catalog through the Service Catalog API (`/api/sn_sc/servicecatalog/`). The Power Platform [ServiceNow connector][connector]'s catalog actions use this API, and so do the ESS generic ServiceNow tools.

Facts come from ServiceNow's [Service Catalog API reference][api] unless marked **Observed**, which means ESS testing against a ServiceNow developer instance showed it.

## Item kinds

Catalog item results carry `type` and `sys_class_name`. What submitting an item does depends on them:

| `type` | `sys_class_name` | Kind | Submit with | Creates |
| --- | --- | --- | --- | --- |
| `catalog_item` | `sc_cat_item`, `pc_hardware_cat_item`, `pc_software_cat_item` | Orderable item | `POST items/{sys_id}/order_now` | A request (REQ, `sc_request`) holding requested items (RITM, `sc_req_item`) |
| `record_producer` | `sc_cat_item_producer` | Record producer: a form that creates a record such as an HR case or incident | `POST items/{sys_id}/submit_producer` | The target record directly; no REQ or RITM |
| `order_guide` | `sc_cat_item_guide` | Order guide: a bundle of items | `POST items/{sys_id}/submit_guide`, then `checkout_guide` | Several items ordered together |
| `content_item` | `sc_cat_item_content` | A link to a page | Nothing; share its `url` | Nothing |
| `catalog_item` | `sc_cat_item_composite_producer` | Composite producer | Unverified | Treat as portal-only |

- A tool that only calls `order_now`, such as the connector's **Order item** action, can't submit record producers or order guides. Give the user the item's portal link instead: `<instance>/sp?id=sc_cat_item&sys_id=<sys_id>`.
- Record producers are common: about a third of the items one test user could see were record producers (**Observed**). A skill that orders items must check the kind before collecting answers.

## Questions (variables)

`GET items/{sys_id}` returns the item's `variables`. Each has `name`, `label`, `friendly_type`, `mandatory`, `value` (the default), and, by type, `choices`, `reference` (a table) or `children` (inside a container).

- Key each answer by the question's `name`, and send a choice's `value`, not its label.
- Map types on `friendly_type`, not the numeric `type`. The number is sometimes a string, and published code tables disagree with it; for example, 6 is `single_line_text` and 2 is `multi_line_text` (**Observed**).
- Walk the `children` of container questions; they hold real questions.
- A default such as `javascript:gs.getUserID();` is a script, not a value. Use the user's sys_id (the variable's `displayvalue` names them); never send the script text (**Observed**).
- A `lookup_select_box` has no usable `choices`; query its `lookup_table`.
- The API doesn't run UI policies or client scripts, so the portal's rules that show, hide or require questions conditionally don't apply. Mandatory questions are enforced only at submit, with a `400` ("Mandatory Variables are required"); there's no endpoint to validate answers first.
- Multi-row variable sets, attachments (`mandatory_attachment` on the item) and custom UI types (`macro`, `ui_page`) can't be filled through the API from chat. When one of them is mandatory, give the portal link.

## Ordering

- `order_now` body: `{"sysparm_quantity": "1", "variables": {"<name>": "<value>"}, "sysparm_requested_for": "<sys_user sys_id>"}`. `sysparm_requested_for` applies only when the item has a Requested For question, and ServiceNow decides whether the user may order for that person.
- The response is the request (REQ): `request_number`, `request_id` (the `sc_request` sys_id), `number`, `sys_id` and `table: sc_request` (**Observed**). Read its requested items from `sc_req_item` with `request=<request_id>`.
- `submit_producer` returns the created record: `sys_id`, `number`, `record`, `redirect_url` and `table`.

## Browsing

- Browse and search with the Service Catalog API (`GET items`, with `sysparm_text` to search), not the `sc_cat_item` table. The API applies each item's user criteria, so it returns only what the user may order; the Table API doesn't.
- `GET items/{sys_id}` returns `400` for an item the user isn't entitled to.

## Tracking and cancelling

- Find the user's orders in `sc_req_item` (`requested_for=javascript:gs.getUserID()`); requested items show progress in `state`, `stage` and `approval`.
- Cancel through the request: set `sc_request.request_state` to `closed_cancelled`, which closes its requested items (**Observed**). Updating `sc_req_item.state` returned `200` but changed nothing (**Observed**); always re-read after a write.

[api]: https://developer.servicenow.com/dev.do#!/reference/api/latest/rest/c_ServiceCatalogAPI
[connector]: https://learn.microsoft.com/connectors/service-now/
