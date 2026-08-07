<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Setup Step 5 — Select, Install, and Bind an ESS Starter

Read the locked environment and current product state:

```text
python scripts/setup_state.py show --view products
```

If `selected_products` is empty, discover the supported ESS agents already
installed in the selected environment and the remaining catalog installations:

```text
python scripts/discover.py \
  --url "{ENVIRONMENT_URL}" \
  --inventory-only
```

Parse `ESS_AGENT_DISCOVERY_JSON:`. Treat `agents` as installed and
`availableInstallations` as the only products available to install. Do not
offer an installed product as an installation option.

If `agents` is nonempty, show each installed agent distinctly:

```text
Installed: **{agent 1 name}**; **{agent 2 name}**
```

Build the same `vscode_askQuestions` picker used by onboarding:

- Add one option for each `availableInstallations` entry, preserving catalog
  order and using its `label` and `description`.
- If `agents` is nonempty, append **Customize an installed agent**.
- Do not mark any option as recommended in the tool metadata and do not
  preselect an option. The `(Recommended)` text in a catalog label is
  informational only.
- Allow exactly one selection.

If the maker selects an available installation, use its `configKey` as
`PRODUCT_ID`.

If the maker selects **Customize an installed agent**, ask them to select one
entry from `agents`. Use its `configKey` as `PRODUCT_ID` and retain its
`schemaname` as `INSTALLED_SCHEMA_NAME`. This adopts the existing installed
product into foundation state; it does not reinstall it.

If both `agents` and `availableInstallations` are empty, show the exact
discovery result and stop.

Persist the selected product:

```text
python scripts/setup_state.py select-product \
  --product "{PRODUCT_ID}"
```

If an installed agent was selected for customization, immediately record its
existing installation:

```text
python scripts/setup_state.py set-product-status \
  --product "{PRODUCT_ID}" \
  --status installed \
  --schema-name "{INSTALLED_SCHEMA_NAME}"
```

Do not collapse the choices into HR, IT, or both. DA and CEA are separate
installable products with independent lifecycle state. Install one product per
foundation cycle. After setup completes, onboarding uses `add-product` to offer
one remaining product at a time while preserving the installed product.

Mark the step in progress and reload the selected product:

```text
python scripts/setup_state.py update-step --step SETUP-05 --status in-progress
python scripts/setup_state.py show --view products
```

Process selected products in catalog order: `da.esshr`, `da.essit`,
`da.esshub`, `cea.esshr`, `cea.essit`, `cea.esshub`. Resume from each
product's persisted status; never overwrite another product's successful
result.

For each product, resolve its `experienceKey`, `verticalKey`, application,
solution, and `requiredConnection` from
`src/reference/ess-agent-installation/config.json`. Do not hard-code package
schema names in this playbook.

For products with `requiredConnection`, run preflight before installation:

```text
python scripts/ess_connection_binding.py inspect \
  --url "{ENVIRONMENT_URL}" \
  --experience "{da|cea}" \
  --vertical "{hr|it|hub}"
```

Parse `ESS_CONNECTION_PREFLIGHT_JSON:`:

- `not-required`: mark the product `ready`.
- `ready`: retain `selectedConnection.name` and mark the product `ready`.
- `selection-required`: ask the maker to select one returned connected
  connection, retain its stable `name`, then mark the product `ready`.
- `missing`: mark the product `connection-required` and show:

  1. Open [Power Apps](https://make.powerapps.com).
  2. Select the `{ENVIRONMENT_NAME}` environment.
  3. Open `Connections`.
  4. Choose `New connection`.
  5. Search for **{displayName}**.
  6. Create the connection, then select **Check again** here.

  Rerun preflight when they choose **Check again**. Do not start installation
  until validation succeeds. Do not show `creationGuidance` as one dense
  sentence.

Persist preflight state independently:

```text
python scripts/setup_state.py set-product-status \
  --product "{PRODUCT_ID}" \
  --status "{connection-required|ready}" \
  [--connection-name "{CONNECTION_NAME}"]
```

Start or resume automatic installation through the solution-catalog schema:

```text
python scripts/install_ess_agent.py \
  --url "{ENVIRONMENT_URL}" \
  --experience "{da|cea}" \
  --vertical "{hr|it|hub}" \
  [--connection-name "{CONNECTION_NAME}"]
```

The installer persists `installing`, `installed`, `manual-required`, or
`failed` only for that product. A failure must preserve every other product's
state. On timeout, follow the emitted manual-install guidance and verify with
`ESS-SOLN-001` before setting the product to `installed`:

```text
python scripts/setup_state.py set-product-status \
  --product "{PRODUCT_ID}" \
  --status installed \
  --schema-name "{MARKETPLACE_APPLICATION_UNIQUE_NAME}"
```

After installation, automatically bind and verify the selected connection:

```text
python scripts/ess_connection_binding.py bind \
  --url "{ENVIRONMENT_URL}" \
  --experience "{da|cea}" \
  --vertical "{hr|it|hub}" \
  [--connection-name "{CONNECTION_NAME}"]
```

Continue only when `ESS_CONNECTION_BINDING_JSON:` reports `bound` or
`not-required`. The command rereads Dataverse after binding.

- For `not-required`, it persists the product as `bound` and continues without
  asking for connection attestation.
- For a bound connection whose catalog `runtimeSource` is not `invoker`, it
  persists the product as `bound` and continues without attestation.
- For a bound `invoker` connection, it persists the product as
  `connection-attestation-required` and returns `agentName`,
  `connectionDisplayName`, and `connectionSettingsUrl`. Show:

  Connection binding is complete. Please verify that the connection is
  available to the installed agent:

  1. Open [connection settings for `{AGENT_NAME}`]({CONNECTION_SETTINGS_URL}).
  2. Confirm the `{ENVIRONMENT_NAME}` environment is selected.
  3. Confirm the `{AGENT_NAME}` agent is open.
  4. In `Settings`, open `Connection settings`.
  5. Locate **{CONNECTION_DISPLAY_NAME}**.
  6. Confirm the connection is connected.
  7. In the `Manage` column, choose `See details`.
  8. Open `Connection parameters`.
  9. If parameters are available, enable sharing for the parameters and choose
     `Save`.

  Ask exactly one question:

  - Header: `Verify connection`
  - Question: `Is **{CONNECTION_DISPLAY_NAME}** connected, with all required connection parameters shared with the \`{AGENT_NAME}\` agent?`
  - Options:
    - `Yes, it is connected and required parameters are shared`
    - `No, it still needs attention`

  When the maker selects
  `Yes, it is connected and required parameters are shared`, persist the
  mandatory manual attestation:

  ```text
  python scripts/setup_state.py attest-product-connection \
    --product "{PRODUCT_ID}"
  ```

  Continue only after the command advances the product to `bound`. If the maker
  selects `No, it still needs attention`, keep the product at
  `connection-attestation-required`, repeat the navigation guidance, and stop
  that product. There is no skip option.

On failure, keep the product-specific error and stop that product without
changing successful products. When resuming a product already at
`connection-attestation-required`, use its persisted agent name and settings
URL to show the same mandatory attestation; do not rerun installation or
binding.

After every selected product is installed, opens successfully, is bound, and
has any required invoker connection attested, persist one consolidated result:

```text
python scripts/setup_state.py record-step-result \
  --step SETUP-05 \
  --mode {automated|manual-attested}
```

Use `manual-attested` when any selected product required invoker connection
attestation; otherwise use `automated`.

Automated verification may be supplemented by manual attestation because
`ESS-SOLN-001` covers the solution family rather than uniquely identifying both
starter experiences. Product-specific state remains in the `products` object.

Complete only after all selected starters pass:

```text
python scripts/setup_state.py update-step --step SETUP-05 --status done
```
