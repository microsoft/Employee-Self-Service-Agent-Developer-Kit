---
nav_exclude: true
search_exclude: false
---
# Give peer feedback — Custom Engine Agent

This topic asks for a colleague's Workday Employee ID and your feedback text, then submits the feedback through the CEA common-execution system topic. Try "Give feedback" or "Share feedback for a colleague."

The request binds the signed-in employee as sender, the entered employee ID as recipient, and the entered text as the comment. The agent displays success or the returned error after submission.

{: .warning }
> The sample submits immediately after collecting feedback; it has no separate confirmation card. Use an approved test recipient and non-sensitive text. The supplied YAML checks whether the recipient ID is blank, but does not compare it with the sender's ID despite its self-feedback error message. Validate the required recipient restrictions with your integration owner before enabling this scenario.

## Files

| File | Description |
|---|---|
| [topic.yaml](./topic.yaml) | Recipient and feedback questions, submission, and result messages |
| [msdyn_HRWorkdayHCMEmployeeGiveFeedback.xml](./msdyn_HRWorkdayHCMEmployeeGiveFeedback.xml) | Workday `Give_Feedback`, Talent v42.0 request and response mapping |

## Setup

Follow the [CEA prerequisites](../#before-you-start) and [register the template configuration](../#register-the-template-configurations) with **Unique name** `msdyn_HRWorkdayHCMEmployeeGiveFeedback` and the complete XML in **Value**. Its inner scenario is named `GiveFeedbackRequest`; preserve that name rather than replacing it with the lookup key.

Then [add this scenario](../#add-a-scenario) by pasting the complete `topic.yaml` into a blank topic's code editor, resolving the CEA system-topic reference, saving, and enabling it.

## Dependencies and customization

Keep `msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemGetCommonExecution`, authenticated employee context, and the Workday permissions required for feedback configured.

Preserve these parameter bindings when changing question wording:

- `{Employee_ID}`: `Global.ESS_UserContext_Employee_Id`, the sender.
- `{Employee_ID_Of_Receiver}`: `Topic.varEmployeeId`, the recipient.
- `{Comment}`: `Topic.FeedbackText`, the feedback.

The sample's `modelDescription` describes coworker feedback, while `triggerQueries` includes broad phrases such as "report issue with workday." Review and narrow those triggers in your customized topic so product-support complaints do not enter an employee-feedback workflow.

## Test and troubleshoot

Start a new test conversation, enter an approved recipient and feedback, and verify both the returned message and the resulting Workday record. Check an invalid recipient, denied Workday permissions, and comment text containing quotes or line breaks: parameters are assembled as a JSON string, so confirm those inputs reach Workday intact.

If submission fails, inspect `isSuccess`, `errorResponse`, the configuration lookup, and sender/recipient permissions. Do not infer success solely from the conversational text. Follow the [shared CEA troubleshooting checks](../#troubleshooting) before publishing.
