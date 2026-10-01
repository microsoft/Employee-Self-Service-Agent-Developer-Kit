# Record current Test pane evidence

Ask the maker to run a low-side-effect HRSD request in the Copilot Studio Test
pane, such as listing HR cases. Record the exact prompt, pass/fail result, and
optional details:

[Open Employee Self-Service (HR) in Copilot Studio]({COPILOT_STUDIO_AGENT_URL})

Use `links.copilotStudioAgent.url` from the provider inspection result.

Open the `Test` pane from this exact agent landing; do not invent a
tab-specific URL.

```text
python scripts/connect_servicenow_da.py record-test --prompt "<prompt>" --result <pass-or-fail> --details "<details>"
```

Do not infer success from topic, credential, binding, or publish health.
Return `ACTION_RESULT = "recorded"` after current evidence is recorded. If the
maker is unavailable, return `ACTION_RESULT = "cancelled"`.
