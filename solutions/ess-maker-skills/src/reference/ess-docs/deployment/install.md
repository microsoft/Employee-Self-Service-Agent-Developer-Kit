# Install the Employee Self-Service agent

After completing the required steps in the [preparation](prepare.md) stage, you can install either or both the following Employee Self-Service agent starters in a specific Power Platform environment:

- Employee Self-Service HR agent
- Employee Self-Service IT agent

## Activities summary

|Role                      |Activities to perform |Configuration area |
|--------------------------|----------------------|-------------------|
|Environment administrator |- Select the right environment </br>- Set up a preferred solution </br>- Install the IT or HR ESS agent (or both agents) |Microsoft Copilot Studio |

## Select the right environment

1. Sign in to [Microsoft Copilot Studio](https://copilotstudio.microsoft.com) as an assigned Environment Administrator.
1. Before installing the agent, make sure that the correct Power Platform environment is selected by verifying the name in the ribbon.

## Set up a preferred solution

1. Set up a preferred solution before performing any customizations, as the default solution contains all the core components of Dataverse, which can't be exported or imported into another environment.
1. Based on the application lifecycle management guidelines, create a *new unmanaged solution* in the Dev environment so the customizations can be performed and exported as managed solution to a Test/UAT/PROD environment.
1. Select the ellipsis (**...**) in the left navigation pane and then select the **Solutions** option from the pop-out menu.
1. Select **+New solution** and fill in the required information.
    1. **Display name** - the human-readable name shown in solution lists. Can include spaces and capitalization.
    1. **Name** - the internal/schema name (no spaces, alphanumeric + underscore). Auto-generated from the display name; safe to leave as-is.
    1. **Publisher** - the publisher record that owns the solution and supplies the customization prefix (see the next step). Reuse an existing org publisher rather than creating a new one per solution.
    1. **Version** - semantic version (`1.0.0.0`). Bump per ALM export so target environments can detect and install upgrades; `1.0.0.0` is the right starting value for a new solution.

    For deeper context on each field, see the Power Platform [Create a solution](https://learn.microsoft.com/power-apps/maker/data-platform/create-solution) documentation.
1. Provide publisher information. Make sure to provide the prefix value, which is used to create objects for this solution prefixed with the given string. For example, if your prefix is "contoso," a new object might be named "contoso_Object".
1. Select the **Create** button to finish creating the solution.
1. Select **Back to solutions** in the left navigation pane.
1. Select the ellipsis (**...**) and choose **Set preferred solution** for the new solution that you created.

> [!NOTE]
> If you intend to create both the HR and IT agents, you need to repeat this process. You must install agents one at a time.

## Install the Employee Self-Service agent

1. Go to the Copilot Studio home page.
1. Select **Create** in the navigation pane. You should see an **Employee Self-Service HR** agent and an **Employee Self-Service IT** agent.
1. Select the Employee Self-Service agent you wish to create, and choose **Install** in the popup.

The Employee Self-Service agent is now installed in your selected Power Platform environment with a preferred solution. To export this solution and import it into another environment, follow the ALM steps in [Deployment overview - ALM](deploy-overview-alm.md).

## Installation checklist

|Role                      |Verification steps |Result |
|--------------------------|-------------------|-------|
|Environment Administrator |1. Sign in to Copilot Studio. </br>2. Select Agents to confirm whether your newly created agent is listed. </br>3. Confirm the Employee Self-Service agent is listed. |Pass/Fail |
|Environment Maker         |Access the newly created agent from Copilot Studio. |Pass/Fail |
