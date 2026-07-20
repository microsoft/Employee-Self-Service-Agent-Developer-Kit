"""Authentication constants for the ESS Migration Toolkit."""

# Microsoft public client ID for Power Platform CLI / Dataverse delegated access.
# Source: https://learn.microsoft.com/power-platform/admin/programmability-authentication-v2
# Scope: user_impersonation only (delegated, no admin consent).
DATAVERSE_CLIENT_ID = "51f81489-12ee-4a9e-aaae-a2591f45987d"

# Supported execution modes — all input pipeline steps run in both.
SUPPORTED_MODES = ("READONLY", "WRITEBACK")
