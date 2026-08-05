"""core.outbound — Dataverse client layer (OData/Web API communication)."""

from core.outbound.dataverse_client import DataverseClient
from core.outbound.exceptions import AuthenticationExpiredError, DataverseApiError

__all__ = [
    "AuthenticationExpiredError",
    "DataverseApiError",
    "DataverseClient",
]
