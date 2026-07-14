"""Unit tests for the typed pipeline framework."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from core.pipeline import (
    Pipeline,
    PipelineConfigurationError,
    PipelineExecutionError,
    PipelineStep,
)


@dataclass
class ExampleContext:
    events: list[str] = field(default_factory=list)


class RecordingContextStep(PipelineStep[ExampleContext, ExampleContext]):
    def __init__(self, event: str, *, can_run: bool = True) -> None:
        super().__init__(
            input_type=ExampleContext,
            output_type=ExampleContext,
            name=event,
            description=f"Record {event}",
        )
        self._event = event
        self._can_run = can_run

    def can_execute(self, context: ExampleContext) -> bool:
        return self._can_run

    def execute(self, context: ExampleContext) -> ExampleContext:
        context.events.append(self._event)
        return context


class FailingContextStep(PipelineStep[ExampleContext, ExampleContext]):
    def __init__(self) -> None:
        super().__init__(
            input_type=ExampleContext,
            output_type=ExampleContext,
            name="fail",
            description="Fail",
        )

    def execute(self, context: ExampleContext) -> ExampleContext:
        raise RuntimeError("step failed")


class WrongOutputStep(PipelineStep[ExampleContext, ExampleContext]):
    def __init__(self) -> None:
        super().__init__(
            input_type=ExampleContext,
            output_type=ExampleContext,
            name="wrong-output",
            description="Return an incompatible output",
        )

    def execute(self, context: ExampleContext) -> ExampleContext:
        return "not a context"  # type: ignore[return-value]


class IntToStringStep(PipelineStep[int, str]):
    def __init__(self) -> None:
        super().__init__(input_type=int, output_type=str, name="int-to-string")

    def execute(self, context: int) -> str:
        return str(context)


class StringToBytesStep(PipelineStep[str, bytes]):
    def __init__(self) -> None:
        super().__init__(input_type=str, output_type=bytes, name="string-to-bytes")

    def execute(self, context: str) -> bytes:
        return context.encode()


class FloatToStringStep(PipelineStep[float, str]):
    def __init__(self) -> None:
        super().__init__(input_type=float, output_type=str, name="float-to-string")

    def execute(self, context: float) -> str:
        return str(context)


def test_pipeline_builder_constructs_immutable_ordered_pipeline() -> None:
    builder = Pipeline.builder("migration", input_type=ExampleContext)
    first_builder = builder.use(RecordingContextStep("discover"))
    second_builder = first_builder.use(RecordingContextStep("migrate"))

    pipeline = second_builder.build()

    assert builder.build().steps == ()
    assert [step.name() for step in pipeline.steps] == ["discover", "migrate"]
    with pytest.raises(AttributeError):
        pipeline.steps.append(RecordingContextStep("mutate"))  # type: ignore[attr-defined]


def test_pipeline_runs_steps_in_order_and_threads_context_without_global_state() -> None:
    context = ExampleContext()
    pipeline = (
        Pipeline.builder("context", input_type=ExampleContext)
        .use(RecordingContextStep("input"))
        .use(RecordingContextStep("migration", can_run=False))
        .use(RecordingContextStep("output"))
        .build()
    )

    result = pipeline.run(context)

    assert result is context
    assert result.events == ["input", "output"]


def test_type_threading_supports_type_changing_steps() -> None:
    pipeline = (
        Pipeline.builder("typed", input_type=int)
        .use(IntToStringStep())
        .use(StringToBytesStep())
        .build()
    )

    result = pipeline.run(42)

    assert result == b"42"
    assert pipeline.input_type is int
    assert pipeline.output_type is bytes


def test_incompatible_adjacent_step_types_fail_during_construction() -> None:
    builder = Pipeline.builder("invalid", input_type=int).use(IntToStringStep())

    with pytest.raises(PipelineConfigurationError, match="expects float"):
        builder.use(FloatToStringStep())


def test_pipeline_registry_rejects_duplicate_step_names() -> None:
    builder = Pipeline.builder("duplicates", input_type=ExampleContext).use(
        RecordingContextStep("same"),
    )

    with pytest.raises(PipelineConfigurationError, match="already registered"):
        builder.use(RecordingContextStep("same"))


def test_empty_pipeline_returns_input_unchanged() -> None:
    context = ExampleContext()
    pipeline = Pipeline.builder("empty", input_type=ExampleContext).build()

    result = pipeline.run(context)

    assert result is context
    assert result.events == []


def test_pipeline_propagates_step_failures_without_suppressing_them() -> None:
    pipeline = (
        Pipeline.builder("failing", input_type=ExampleContext).use(FailingContextStep()).build()
    )

    with pytest.raises(RuntimeError, match="step failed"):
        pipeline.run(ExampleContext())


def test_pipeline_rejects_incompatible_runtime_output() -> None:
    pipeline = (
        Pipeline.builder("bad-output", input_type=ExampleContext).use(WrongOutputStep()).build()
    )

    with pytest.raises(PipelineExecutionError, match="produced incompatible output"):
        pipeline.run(ExampleContext())
