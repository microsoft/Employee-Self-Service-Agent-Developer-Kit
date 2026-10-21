---
nav_exclude: true
search_exclude: false
---
# Workday Employee Request Time Off

This topic lets employees submit single-day or multi-day time off requests to Workday directly from a Copilot Studio agent.

When an employee triggers this topic, the agent:

1. Fetches current leave balances from Workday
2. Shows an Adaptive Card form with leave type, dates, hours, and reason
3. Submits the request to the Workday `Enter_Time_Off` API
4. Displays a confirmation card or a friendly error with retry options

**Example trigger phrases:** "Request time off" · "Request vacation from January 5th to January 10th" · "Submit sick leave for next week"

![Request Time Off form and adaptive card](requestTimeOffAdapativeCard.png)
![Request Time Off form submitted](requestTimeOffSubmitted.png)

{: .important }
> This topic ships with sample values from a reference Workday tenant. Every Workday tenant is configured differently — you must replace the Plan IDs, Reason IDs, leave types, and tenant URL with values from your own Workday setup before importing. See [Configure the topic](#configure-the-topic) for details.

## Prerequisites

Before you start, make sure you have:

- An editable ESS HR **DA GA** agent with its Workday integration and required HR system topics configured; this sample does not install those dependencies
- A Workday tenant with the **Absence_Management** module enabled
- A Workday connector configured with **User**-level authentication in your Power Platform environment
- The global variable **`Global.ESS_UserContext_Employee_Id`** populated at session start with the logged-in employee's Workday Employee ID
- The [shared template-config setup topic](../../WorkdayOSSTemplateConfigurationSetup.yaml) initialized before this scenario
- Your organization's Workday Absence Plan IDs, Time Off Type IDs, and Reason IDs

## What's in this folder

| File | Description | Do you need to edit it? |
|------|-------------|------------------------|
| `topic.yaml` | Conversation flow, Adaptive Card form, configuration tables, error handling | Yes — update tenant URL, Plan IDs, Reason IDs |
| [shared template-config setup topic](../../WorkdayOSSTemplateConfigurationSetup.yaml) | Workday request templates, including time off and vacation balance; configure once for the agent | No |
| `requestTimeOffAdapativeCard.png` | Screenshot of the Adaptive Card form | No |
| `requestTimeOffSubmitted.png` | Screenshot of the confirmation card | No |
| `README.md` | This file | No |

## Setup

Configure the [shared template-config setup topic](../../#set-up-the-shared-configuration-topic) once for your agent.

Configure the values below, then follow [Add a scenario](../../#add-a-scenario) to paste this folder's complete `topic.yaml` into a blank topic's code editor.

## Configure the topic

Open `topic.yaml` and update the following values to match your Workday tenant. All sample values shown below come from a reference tenant and **must** be replaced.

### Step 1: Set your Workday tenant URL

Find the `set_workday_url` node and replace `<TENANT_NAME>` with your tenant name:

```yaml
# Before
value: https://impl.workday.com/<TENANT_NAME>/home.htmld

# After — replace contoso_corp with your tenant
value: https://impl.workday.com/contoso_corp/home.htmld
```

Your Workday URL typically follows the pattern `https://<host>.workday.com/<tenant_name>/home.htmld`. Check your browser address bar when logged into Workday.

### Step 2: Update Plan IDs

Find the `set_plan_config` node. Replace each `PlanID` with the corresponding ID from your Workday tenant:

```
=Table(
  {PlanID: "ABSENCE_PLAN-6-139", DisplayName: "Floating holiday"},
  {PlanID: "ABSENCE_PLAN-6-159", DisplayName: "Sick leave"},
  {PlanID: "ABSENCE_PLAN-6-158", DisplayName: "Vacation"}
)
```

You can find your Plan IDs in Workday under **Setup > Absence Plans > Plan ID**. Only plans listed here **and** returned by the Workday API will appear in the balance header.

### Step 3: Update Reason IDs

Find the **second** `set_time_off_reason_config` node. Replace each `ReasonID` with your tenant's value:

| ReasonKey | TimeOffTypeID | ReasonID ← replace this |
|-----------|---------------|------------------------|
| `full_day` | `ESS_Vacation_Hours` | `Full Day_Vac` |
| `half_day_am` | `ESS_Vacation_Hours` | `Half Day_AM_Vac` |
| `half_day_pm` | `ESS_Vacation_Hours` | `Half Day_PM_Vac` |
| `full_day` | `ESS_Floating_Holiday_Hours` | `full_day_floating` |
| `half_day_am` | `ESS_Floating_Holiday_Hours` | `half_day_am_floating` |
| `half_day_pm` | `ESS_Floating_Holiday_Hours` | `half_day_pm_floating` |
| `full_day` | `ESS_Comp_Off` | `Full day-COI` |
| `half_day_am` | `ESS_Comp_Off` | `Half day AM-COI` |
| `half_day_pm` | `ESS_Comp_Off` | `Half day PM-COI` |
| `full_day` | `ESS_Sick_Time_Off` | `Full day_Sick_IN` |
| `half_day_am` | `ESS_Sick_Time_Off` | `Half day AM_Sick_IN` |
| `half_day_pm` | `ESS_Sick_Time_Off` | `Half day PM_Sick_IN` |

Don't rename the `ReasonKey` values — they're bound to the Adaptive Card "Reason for time off" dropdown.

### Step 4 (optional): Update leave-type choices

If your organization uses different leave types than Vacation, Floating holiday, Sick leave, and Comp off, update two places:

**The Adaptive Card dropdown** — in the `collect_time_off` node, edit the `choices` array. For example, to add Bereavement:

```json
{ "title": "Bereavement", "value": "ESS_Bereavement" }
```

**The keyword mapping** — in the `set_leave_type_config` node, add a row so the agent can pre-select the type from the user's utterance:

| Keywords (comma-separated) | LeaveTypeValue |
|---------------------------|----------------|
| `vacation,annual,pto,holiday pay` | `Vacation_Hours` |
| `floating,floater,float day` | `Floating_Holiday_Hours` |
| `sick,illness,medical,unwell,not feeling well` | `ESS_Sick_Time_Off` |

If you add a new leave type, also add matching rows to `TimeOffReasonConfig` (one per ReasonKey).

### Step 5 (optional): Update the Workday icon

Find the `set_workday_icon_url` node and replace the 1×1 pixel placeholder with your organization's Workday icon URL.

## Import and test the topic

1. In Copilot Studio, select **Topics > Add a topic > From blank**.
2. Open **More > Open code editor** and replace the contents with your configured `topic.yaml`. Return to the canvas, save, and enable the topic.
3. Start a **new** test conversation so the OOB initializer and shared template-config setup topic run in order, then try these with approved test data before publishing:

| What to test | What to expect |
|-------------|---------------|
| Say "I want to request time off" | Balance header appears, then the Adaptive Card form |
| Say "Request vacation from September 15 to September 19" and submit | Success card with date range, type, hours, and reason |
| Submit with end date before start date | Error: "The end date can't be earlier than the start date" with retry |
| Select "I don't see my leave type listed" and submit | Redirect message with a link to Workday |
| Click **Cancel** | "Leave request was cancelled - nothing was submitted" |
| Submit dates that overlap an existing request | Friendly AI-rewritten error with retry |

If balances show as empty but the form appears, your `PlanConfig` Plan IDs likely don't match your Workday tenant.

## Request template reference

The `msdyn_WorkdayHCMRuntimeEmployeeEnterTimeOff_MultiDay` template in the [shared template-config setup topic](../../WorkdayOSSTemplateConfigurationSetup.yaml) is a SOAP template for the Workday `Enter_Time_Off_Request` operation. You usually don't need to edit it — placeholder tokens like `{Employee_ID}` and `{timeoff_Dates}` are filled at runtime.

Two settings you might want to change:

| Setting | Default | Change if… |
|---------|---------|------------|
| `<wd:Auto_Complete>` | `false` (requires manager approval) | Your process skips approval — set to `true` |
| `<version>` and `wd:version` | `v42.0` | Your tenant uses a different API version |

{: .important }
> If you change the API version, update it in **both** the `<version>` element and the `wd:version` attribute. Mismatched versions cause API errors.

## What you can safely edit in the YAML

| What | Where in `topic.yaml` |
|------|----------------------|
| Workday tenant URL | `set_workday_url` node |
| Plan IDs | `set_plan_config` node |
| Reason IDs | Second `set_time_off_reason_config` node |
| Leave-type keywords | `set_leave_type_config` node |
| Adaptive Card dropdown choices | `collect_time_off` node → `choices` array |
| Trigger phrases | `modelDescription` block |
| Workday icon | `set_workday_icon_url` node |
| Balance effective date | `set_as_of_effective_date` node (defaults to `Today()`) |

**Don't** change these — they'll break the topic:

- Node `id` values (`id: main`, `id: collect_time_off`, etc.) — referenced by `GotoAction` jumps
- `kind:` values — Copilot Studio node types
- `dialog:` contracts — must resolve to the existing HR system topics in your agent; use the topic picker if a generated schema name differs
- `output: binding:` mappings — must match shared dialog outputs
- XML placeholder tokens (`{Employee_ID}`, `{timeoff_Dates}`, etc.) — filled at runtime
- The `EmployeeName` input — the model uses it to validate the request is for the logged-in user

## Dependencies

This topic depends on three external components:

- **Workday `Get_Time_Off_Plan_Balances`** — Absence_Management service, User-level auth. Uses the `msdyn_WorkdayHCMRuntimeEmployeeGetVacationBalance` template in the shared template-config setup topic. Called at topic start to show balances.

- **Workday `Enter_Time_Off`** — Absence_Management v42.0, User-level auth. Uses the `msdyn_WorkdayHCMRuntimeEmployeeEnterTimeOff_MultiDay` template in the shared template-config setup topic. Called after form submission.

- **`WorkdaySystemGetCommonExecution` dialog** — an existing HR DA GA system topic. Executes request templates against the Workday connector and must be configured before you add this scenario.

## Troubleshooting

**Balance header is empty or shows all zeros**
Your `PlanConfig` Plan IDs don't match your Workday tenant, or the balance template isn't registered. Verify the IDs and confirm `msdyn_WorkdayHCMRuntimeEmployeeGetVacationBalance` is in the `Global.ESS_WorkdayHCM_Template_Configurations` lookup.

**"Something went wrong" when submitting**
The `ReasonID` values in `TimeOffReasonConfig` don't match your Workday tenant. Check your IDs in Workday under **Setup > Time Off Reasons**.

**Authentication error**
`Global.ESS_UserContext_Employee_Id` is empty or the Workday connector isn't configured. Verify both.

**Vacation isn't pre-selected when the user says "request vacation"**
The keyword mapping uses `Vacation_Hours` but the dropdown value is `ESS_Vacation_Hours`. Update `LeaveTypeConfig` to use `ESS_Vacation_Hours`. See [Open Questions](#open-questions).

**Success card shows a raw ID like `ESS_Vacation_Hours`**
The `Switch()` expression in the success card doesn't match the dropdown values. See [Open Questions](#open-questions).

## Tips

- Initialize the shared template-config setup topic **before** this scenario — the balance lookup runs at topic start and requires its mapping to be present.
- Update `PlanConfig`, `TimeOffReasonConfig`, **and** the Adaptive Card `choices` together — they're interconnected but maintained separately.
- Test with a real Workday employee ID that has leave balances.
- Keep `ReasonKey` values as `full_day`, `half_day_am`, `half_day_pm` — they're bound to the Adaptive Card dropdown.

## Handle repo updates

When this repo publishes a new version of the topic:

Back up your topics and preserve your tenant URL, Plan IDs, Reason IDs, and leave-type keywords when applying updates. Update the shared template-config setup topic using [Customize and update configurations](../../#customize-and-update-configurations); its changes affect every scenario that uses the updated keys.

## Known limitations

- **Leave type pre-selection may not work for Vacation and Floating Holiday.** The keyword mapping (`LeaveTypeConfig`) uses `Vacation_Hours` and `Floating_Holiday_Hours`, but the Adaptive Card dropdown expects `ESS_Vacation_Hours` and `ESS_Floating_Holiday_Hours`. To fix this, update the `LeaveTypeValue` entries in `LeaveTypeConfig` to include the `ESS_` prefix.

- **Success card may show raw IDs instead of friendly names.** After a successful submission, the confirmation card may display `ESS_Vacation_Hours` instead of "Vacation". To work around this, update the `Switch()` expression in the success card to match the `ESS_`-prefixed values from the dropdown.
