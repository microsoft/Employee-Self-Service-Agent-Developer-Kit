"""Unit tests for the generic StagedPipeline composition."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.pipeline import Pipeline, PipelineStep, StagedPipeline


@dataclass
class ExampleContext:
    events: list[str] = field(default_factory=list)


class RecordingContextStep(PipelineStep[ExampleContext, ExampleContext]):
    def __init__(self, event: str) -> None:
        super().__init__(
            input_type=ExampleContext,
            output_type=ExampleContext,
            name=event,
            description=f"Record {event}",
        )
        self._event = event

    def execute(self, context: ExampleContext) -> ExampleContext:
        context.events.append(self._event)
        return context


def _stage(event: str) -> Pipeline[ExampleContext, ExampleContext]:
    return (
        Pipeline.builder(event, input_type=ExampleContext).use(RecordingContextStep(event)).build()
    )


def test_add_appends_stages_in_declaration_order() -> None:
    staged = StagedPipeline[ExampleContext]().add(_stage("first")).add(_stage("second"))

    assert [stage.name for stage in staged.stages] == ["first", "second"]


def test_run_threads_context_through_every_stage_in_order() -> None:
    context = ExampleContext()

    result = (
        StagedPipeline[ExampleContext]()
        .add(_stage("first"))
        .add(_stage("second"))
        .add(_stage("third"))
        .run(context)
    )

    assert result is context
    assert result.events == ["first", "second", "third"]


def test_empty_staged_pipeline_returns_context_unchanged() -> None:
    context = ExampleContext()

    result = StagedPipeline[ExampleContext]().run(context)

    assert result is context
    assert result.events == []


def test_add_returns_new_instance_without_mutating_original() -> None:
    base = StagedPipeline[ExampleContext]()
    extended = base.add(_stage("first"))

    assert base.stages == ()
    assert [stage.name for stage in extended.stages] == ["first"]
