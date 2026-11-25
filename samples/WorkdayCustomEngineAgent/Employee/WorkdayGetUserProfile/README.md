---
nav_exclude: true
search_exclude: false
---
# Workday Get User Profile

This scenario enables employees to retrieve their profile information from Workday through a conversational interface. It provides comprehensive employee data including personal details, employment information, contact details, and tenure calculations.

## Features

- **Personal Information**: Name, Date of Birth, Gender
- **Employment Details**: Employee ID, Business Title, Organization/Department, Manager, Location
- **Contact Information**: Work Email, Work Phone, Home Email, Home Phone, Home Address
- **Employment Status**: Active/Inactive status, Hire Date
- **Tenure Calculation**: Continuous Service Date and calculated Length of Service (years, months, days)

## Trigger Phrases

Users can activate this topic with phrases like:
- "What is my profile?"
- "Show my profile"
- "What is my employee ID?"
- "What is my job title?"
- "What is my work email?"
- "Who is my manager?"
- "What department am I in?"
- "What is my tenure?"
- "How long have I been with the company?"
- "What is my hire date?"
- "Am I an active employee?"

## Files

| File | Description |
|------|-------------|
| `topic.yaml` | Main Copilot Studio topic definition |
| `msdyn_HRWorkdayHCMEmployeeGetUserProfile.xml` | XML template with XPath extractions for profile data |

## Setup

Follow the [CEA prerequisites](../#before-you-start) and [register the template configuration](../#register-the-template-configurations) with **Unique name** `msdyn_HRWorkdayHCMEmployeeGetUserProfile` and the complete XML in **Value**.

Then [add this scenario](../#add-a-scenario) by pasting the entire `topic.yaml` into a blank topic's code editor, resolving the CEA common-execution reference, saving, and enabling it. This scenario uses `Global.ESS_UserContext_Employee_Id` and today's effective date.

You can customize `modelDescription` and response labels while preserving the `finalizedData` output contract and XML extraction keys. Review which personal fields your organization permits the agent to display; the record includes date of birth and home-contact details.

## Workday APIs Used

| API | Service | Version | Purpose |
|-----|---------|---------|---------|
| `Get_Workers` | Human_Resources | v45.0 | Retrieve comprehensive employee profile data |

## Data Retrieved

The topic extracts the following fields from Workday:

| Field | XPath Source | Description |
|-------|--------------|-------------|
| `EmployeeID` | Worker_Data/Worker_ID | Employee's Workday ID |
| `Name` | Worker_Descriptor | Employee's full name |
| `DOB` | Personal_Information_Data/Birth_Date | Date of birth |
| `Gender` | Gender_Reference/@Descriptor | Gender |
| `BusinessTitle` | Position_Data/Business_Title | Job title |
| `Organization` | Organization_Reference (SUPERVISORY_ORGANIZATION) | Department/Org |
| `Manager` | Manager_Reference/@Descriptor | Direct manager's name |
| `Location` | Location_Reference/@Descriptor | Work location |
| `HireDate` | Worker_Status_Data/Hire_Date | Original hire date |
| `WorkEmail` | Email_Address (WORK usage type) | Work email address |
| `HomeAddress` | Address_Data (HOME usage type) | Formatted home address |
| `HomeEmail` | Email_Address (HOME usage type, primary) | Personal email |
| `HomePhone` | Phone_Data (HOME usage type, primary) | Home phone number |
| `WorkPhone` | Phone_Data (WORK usage type, primary) | Work phone number |
| `Status` | Worker_Status_Data/Active | Employment status (Active/Inactive) |
| `ContinuousServiceDate` | Worker_Status_Data/Continuous_Service_Date | Service start date |
| `LengthOfService` | *Calculated* | Years, months, days of service |

## Flow Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    User Triggers Topic                       │
│         (e.g., "What is my profile?")                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Call Get_Workers API                            │
│         (with Employee_ID and As_Of_Date)                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│           Parse Response via XPath                           │
│      (Extract all profile fields)                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│         Calculate Length of Service                          │
│    (Years, Months, Days from Continuous Service Date)       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│           Return finalizedData Record                        │
│       (All fields available for AI to respond)              │
└─────────────────────────────────────────────────────────────┘
```

## Length of Service Calculation

The topic automatically calculates the employee's length of service from their Continuous Service Date:

```
Years:  RoundDown(DateDiff(ServiceDate, Today, Months) / 12, 0)
Months: Mod(DateDiff(ServiceDate, Today, Months), 12)
Days:   DateDiff(AdjustedDate, Today, Days)
```

Output format: "X year(s) Y month(s) Z day(s)"

## Dependencies

This topic requires the following system topics/dialogs:
- `msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemGetCommonExecution` - For executing Workday API calls

## Global Variables Used

| Variable | Description |
|----------|-------------|
| `Global.ESS_UserContext_Employee_Id` | The logged-in employee's Workday Employee ID |

## Output

The topic outputs a `finalizedData` record containing all profile fields that can be used by the AI orchestrator to formulate responses based on what the user specifically asked for.

```yaml
outputType:
  properties:
    finalizedData:
      type: Record
      properties:
        EmployeeID: String
        Name: String
        DOB: String
        Gender: String
        BusinessTitle: String
        Organization: String
        Manager: String
        Location: String
        HireDate: String
        WorkEmail: String
        HomeAddress: String
        HomeEmail: String
        HomePhone: String
        WorkPhone: String
        Status: String
        ContinuousServiceDate: String
        LengthOfService: String
```

## Important Notes

1. **Privacy**: Requests use the signed-in employee's ID, and the model description instructs the agent not to answer questions about other employees. That instruction is not an authorization boundary; retain Workday's user-level permissions.

2. **Tenure Information**: Length of Service is only included in the AI's response when the user specifically asks about tenure, service length, or how long they've been with the company.

3. **Status Conversion**: The raw `Active` field from Workday (1 or 0) is converted to human-readable "Active" or "Inactive".

4. **Response Optimization**: The Get_Workers request is optimized to exclude unnecessary data (benefits, qualifications, photos, etc.) to improve performance.

## Test and troubleshoot

In fresh conversations, ask for a profile, manager, and length of service. Compare the returned `finalizedData` fields and tenure with approved Workday test data. Include a request about another employee and an employee with absent optional contact fields.

The service calculation parses `ContinuousServiceDate` with `DateValue`, without a blank-date guard. Validate employees without a continuous-service date before rollout. If the read or parser fails, inspect the common-execution `isSuccess`/`errorResponse` and XML response keys before changing bindings. Use the [shared CEA troubleshooting checks](../#troubleshooting) before publishing.

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | December 2025 | Initial release with comprehensive profile retrieval |
