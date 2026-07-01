"""Typed exceptions raised by the pipeline framework."""

from __future__ import annotations


class PipelineConfigurationError(ValueError):
    """Raised when a pipeline cannot be constructed from the provided steps."""


class PipelineExecutionError(RuntimeError):
    """Raised when a pipeline receives or produces values of incompatible types."""
