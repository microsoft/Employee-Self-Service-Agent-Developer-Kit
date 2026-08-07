<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Setup Step 6 — Baseline Readiness

Mark the step in progress and read the selected starter matrix:

```text
python scripts/setup_state.py update-step --step SETUP-06 --status in-progress
python scripts/setup_state.py show --view products
```

For each selected installed starter:

1. Open [Copilot Studio](https://copilotstudio.microsoft.com).
2. Select the `{AGENT_NAME}` agent in the `{ENVIRONMENT_NAME}` environment.
3. Confirm the agent can be edited.
4. Confirm `Configure` and `Topics` are reachable.
5. Confirm the agent shell and starter content footprint are present.

Use automation when available. Otherwise show these exact checks and require explicit
manual attestation for each starter. A listed starter that cannot be opened is a
failure, not a partial pass.

Persist readiness independently:

```text
python scripts/setup_state.py set-product-readiness \
  --product "{da.esshr|da.essit|da.esshub|cea.esshr|cea.essit|cea.esshub}" \
  --ready
```

After every selected starter passes, persist one consolidated result:

```text
python scripts/setup_state.py record-step-result \
  --step SETUP-06 \
  --mode {automated|manual-attested}
```

Use `manual-attested` when any selected starter required manual readiness
attestation; otherwise use `automated`.

Complete only after every selected starter passes:

```text
python scripts/setup_state.py update-step --step SETUP-06 --status done
```
