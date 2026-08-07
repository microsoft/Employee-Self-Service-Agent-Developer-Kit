<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Setup Step Result Adapter

After completing a setup step's automated checks and permitted attestations,
persist one consolidated result directly on that step:

```text
python scripts/setup_state.py record-step-result \
  --step {SETUP_STEP_ID} \
  [--checkpoint "{FLIGHTCHECK_IDS}"] \
  --mode {automated|manual-attested|skipped}
```

The command adds the step's concise note and recorded timestamp automatically.
Do not duplicate environment, prerequisite, ALM, or product data in the step.
