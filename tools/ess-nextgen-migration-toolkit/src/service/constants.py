"""Shared constants for the ESS Migration Toolkit."""

# Supported execution modes for the ESS migration pipeline.
SUPPORTED_MODES = ("READONLY", "WRITEBACK")

# ESS customer-facing report filename (the product deliverable). The generic
# framework defaults to a neutral name; the ESS toolkit supplies this one.
REPORT_FILENAME = "migration_report.md"

# ESS-owned base (managed) solution unique names, sourced from the HR/IT
# solution manifests (Solution.xml -> <UniqueName>). Customization discovery
# queries dependencies-for-uninstall against these fixed solutions based on the
# selected agent's vertical.
ESS_SOLUTION_BY_VERTICAL = {
    "hr": "msdyn_CopilotForEmployeeSelfServiceHR",
    "it": "msdyn_CopilotForEmployeeSelfServiceIT",
}
