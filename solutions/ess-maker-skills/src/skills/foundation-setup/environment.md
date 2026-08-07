<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Setup Step 3 — Environment Binding

Mark the step in progress and read only the locked environment:

```text
python scripts/setup_state.py update-step --step SETUP-03 --status in-progress
python scripts/setup_state.py show --view environment
```

Treat the locked scope as the maker's selected target. Do not ask whether it is
still intended and do not show a confirmation popup. Verify its identity
automatically below. If observed environment identity differs from the locked
scope, block with cause `ENVIRONMENT_DRIFT`; do not silently rewrite the scope.

If `environment.verified_at` is no more than 15 minutes old, reuse that
successful environment resolution as the `ENV-001` result. Do not authenticate
or call FlightCheck again. State:

`Environment identity was verified recently; continuing with the locked target.`

If it is older than 15 minutes, run:

```text
python scripts/flightcheck/cli.py \
  --checkpoint ENV-001 \
  --quiet-auth \
  --environment-url "{ENVIRONMENT_URL}" \
  --environment-id "{ENVIRONMENT_ID}"
```

After the fresh result is reused or the check passes, persist the result:

```text
python scripts/setup_state.py record-step-result \
  --step SETUP-03 \
  --checkpoint ENV-001 \
  --mode automated
```

Do not read `.local/config.json` or invoke environment selection during this
step; local workspace configuration is created later. No manual pass is allowed
for context drift.

Complete after the locked identity is confirmed:

```text
python scripts/setup_state.py update-step --step SETUP-03 --status done
```
