"""Typed outbound exceptions for Dataverse client failures."""

from __future__ import annotations


class DataverseApiError(RuntimeError):
    """Raised when the Dataverse Web API returns a non-authentication failure."""

    def __init__(
        self,
        *,
        status: int,
        operation: str,
        entity_set: str | None,
        request_id: str | None = None,
        message: str | None = None,
    ) -> None:
        self.status = status
        self.operation = operation
        self.entity_set = entity_set
        self.request_id = request_id
        super().__init__(message or self._default_message())

    def _default_message(self) -> str:
        target = self.entity_set or "Dataverse resource"
        message = f"Dataverse {self.operation} failed for {target} (HTTP {self.status})."
        if self.request_id is None:
            return message
        return f"{message} Request ID: {self.request_id}."


class AuthenticationExpiredError(DataverseApiError):
    """Raised when a Dataverse request fails because the bearer token expired."""

    def __init__(
        self,
        *,
        operation: str,
        entity_set: str | None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(
            status=401,
            operation=operation,
            entity_set=entity_set,
            request_id=request_id,
            message="Dataverse authentication expired or is no longer valid.",
        )
