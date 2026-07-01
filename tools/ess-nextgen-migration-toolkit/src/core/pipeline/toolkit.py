"""Fluent ESS migration super-pipeline composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from core.pipeline.exceptions import PipelineConfigurationError
from core.pipeline.pipeline import Pipeline

TContext = TypeVar("TContext")


@dataclass(frozen=True)
class EssMigrationToolkit(Generic[TContext]):
    """Composes the Input, Migration, and Output stage pipelines.

    Purpose:
        Represent the product-level super-pipeline over a shared context.
    Responsibilities:
        Accept one context-preserving pipeline per stage, execute stages in the
        deterministic Input → Migration → Output order, and return the context.
    Inputs:
        A shared ``TContext`` owned by the caller and stage pipelines declared as
        ``Pipeline[TContext, TContext]``.
    Outputs:
        The same context type enriched by all configured stages.
    """

    _input_pipeline: Pipeline[TContext, TContext] | None = None
    _migration_pipeline: Pipeline[TContext, TContext] | None = None
    _output_pipeline: Pipeline[TContext, TContext] | None = None

    def input(self, pipeline: Pipeline[TContext, TContext]) -> EssMigrationToolkit[TContext]:
        """Return a toolkit configured with the Input stage pipeline."""
        return EssMigrationToolkit(
            _input_pipeline=pipeline,
            _migration_pipeline=self._migration_pipeline,
            _output_pipeline=self._output_pipeline,
        )

    def migrate(self, pipeline: Pipeline[TContext, TContext]) -> EssMigrationToolkit[TContext]:
        """Return a toolkit configured with the Migration stage pipeline."""
        return EssMigrationToolkit(
            _input_pipeline=self._input_pipeline,
            _migration_pipeline=pipeline,
            _output_pipeline=self._output_pipeline,
        )

    def output(self, pipeline: Pipeline[TContext, TContext]) -> EssMigrationToolkit[TContext]:
        """Return a toolkit configured with the Output stage pipeline."""
        return EssMigrationToolkit(
            _input_pipeline=self._input_pipeline,
            _migration_pipeline=self._migration_pipeline,
            _output_pipeline=pipeline,
        )

    def run(self, context: TContext) -> TContext:
        """Run the configured super-pipeline against ``context``."""
        if self._input_pipeline is None:
            raise PipelineConfigurationError("Input pipeline is not configured.")
        if self._migration_pipeline is None:
            raise PipelineConfigurationError("Migration pipeline is not configured.")
        if self._output_pipeline is None:
            raise PipelineConfigurationError("Output pipeline is not configured.")

        current = self._input_pipeline.run(context)
        current = self._migration_pipeline.run(current)
        return self._output_pipeline.run(current)
