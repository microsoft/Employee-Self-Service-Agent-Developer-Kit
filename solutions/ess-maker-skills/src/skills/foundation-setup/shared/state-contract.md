<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Setup State Contract

`scripts/setup_state.py` is the only writer for `.local/setup/config.json`.

## Responsibilities

- `SetupState` owns the versioned domain data.
- `SetupWorkflow` enforces transitions, deterministic resume, and readiness.
- `JsonSetupStateRepository` owns atomic JSON persistence.
- `SetupStateService` coordinates repository behavior.
- `ProductInstallationRecord` owns one product's installation, connection, and
  readiness outcome.

The state intent is fixed to `prereqs + base ESS install only`. Integration data must
never be added to this file.

## Step state

The eight canonical steps support `pending`, `in-progress`, `blocked`, and `done`.
Only one step may be `in-progress`. `active_step` always resolves to the first step
that is not `done`.

## Step result

Completed steps retain only workflow metadata:

```text
state: done
checkpoint: optional FlightCheck ID
note: concise step outcome
mode: automated | manual-attested | skipped
recorded_at: UTC timestamp
```

Canonical facts belong in `environment`, `prerequisites`, `alm`, or `products`
and must not be duplicated inside steps. A failed or unknown mandatory check
cannot be converted into success-shaped state.

## Product installation state

`selected_products` contains one or more catalog IDs:

```text
da.esshr
da.essit
da.esshub
cea.esshr
cea.essit
cea.esshub
```

`products` always contains an independent record for all six IDs. Selected
products transition through `pending`, `connection-required`, `ready`,
`installing`, `manual-required`, `installed`,
`connection-attestation-required`, `bound`, or `failed`. Unselected products
remain `not-selected`.

Installation and binding commands may update only their own product record.
Successful products must remain durable when another product is blocked or
fails. Readiness can pass only after that product reaches `bound`; `bound`
also covers products whose catalog declares that no connection is required.
An `invoker` connection reaches `connection-attestation-required` after
automatic binding and can reach `bound` only after the maker attests that the
connection is connected and shared in the installed agent's Copilot Studio
connection settings.
