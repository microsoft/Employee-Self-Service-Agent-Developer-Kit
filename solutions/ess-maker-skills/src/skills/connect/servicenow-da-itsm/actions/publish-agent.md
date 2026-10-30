# Legacy publish evidence

This action is retired and is not part of the ServiceNow ITSM Connect
lifecycle. Connect completes after the current Test pane validation passes.

Do not invoke `publish`, ask a publish question, or mutate the remote agent.
The user may publish manually outside Connect. Existing publish receipts remain
historical evidence and may be inspected or reconciled read-only; they are not
a current completion gate.

Return `ACTION_RESULT = "recorded"` only when an older caller opens this file
for compatibility. Do not claim that the agent was published.
