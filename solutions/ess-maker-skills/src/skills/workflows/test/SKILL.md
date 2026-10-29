# Inspect an existing workflow run

Power Automate authoring, deployment, registration, and repair take place outside ADK. This skill provides separately requested read-only run-history inspection, not workflow execution or a backend conversation test.

## Establish the target

Confirm the intended environment and flow identity from current approved context. Preserve a supplied run identity. Read-only inspection has its own target and authentication prerequisites; selected-Dev AgentBuilder readiness does not establish Dataverse or Flow API access.

If those prerequisites are unavailable, explain what could not be inspected and leave the runtime outcome unknown.

## Read and interpret

Read `src/reference/ess-docs/operations/flow-run-inspection.md` before interpreting run actions. Use the existing inspector against the confirmed target:

```powershell
python scripts/flow_run_inspect.py --flow "<flow-guid>" --environment "<environment-guid>"
```

Add `--run "<run-guid>"` when inspecting a selected run. Preserve returned run identity, action status, service errors, and correlation information. If no relevant run exists, report that rather than treating absence as success or starting a conversation automatically.

## Report

Explain the observed failure and its evidence without claiming runtime execution or a successful repair. Direct any required flow, connection, or template-configuration change to its supported external owner. Keep topic authoring and separately requested evaluation work with their own owners.
