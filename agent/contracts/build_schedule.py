"""Build task, batch, and wave contracts over admitted TaskTodo records."""

from __future__ import annotations

from pydantic import Field, model_validator

from agent.contracts.common import ArtifactRef, ContractModel, Sha256
from agent.contracts.host import ReceiptRef
from agent.contracts.task_todo import TaskTodo, paths_overlap
from agent.contracts.tool_registry import safe_relative_path


class BuildTask(ContractModel):
    task_id: str = Field(min_length=1)
    todo: TaskTodo

    @model_validator(mode="after")
    def identity_matches(self) -> BuildTask:
        if self.task_id != self.todo.todo_id:
            raise ValueError("Build task must identify its admitted TaskTodo")
        return self


class BuildBatch(ContractModel):
    batch_id: str = Field(min_length=1)
    tasks: tuple[BuildTask, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def distinct_tasks_and_paths(self) -> BuildBatch:
        seen_tasks: set[str] = set()
        paths: set[str] = set()
        for task in self.tasks:
            if task.task_id in seen_tasks:
                raise ValueError("duplicate Build task in batch")
            seen_tasks.add(task.task_id)
            for path in task.todo.authorized_paths:
                if any(paths_overlap(path, occupied) for occupied in paths):
                    raise ValueError("overlapping Build batch paths")
                paths.add(path)
        return self


class BuildWave(ContractModel):
    wave_id: str = Field(min_length=1)
    wave_index: int = Field(ge=1)
    batches: tuple[BuildBatch, ...] = Field(min_length=1)
    expected_preimages: dict[str, Sha256 | None]
    previous_wave_result_ref: ArtifactRef | None = None
    previous_wave_receipt_ref: ReceiptRef | None = None

    @model_validator(mode="after")
    def validate_pins(self) -> BuildWave:
        if self.wave_index == 1 and (
            self.previous_wave_result_ref is not None or self.previous_wave_receipt_ref is not None
        ):
            raise ValueError("first Build wave cannot cite previous wave evidence")
        if self.wave_index > 1 and (self.previous_wave_result_ref is None or self.previous_wave_receipt_ref is None):
            raise ValueError("later Build waves require previous accepted wave evidence")
        if (
            self.previous_wave_result_ref is not None
            and self.previous_wave_receipt_ref is not None
            and (
                self.previous_wave_result_ref.contract_id != "verified_wave_result"
                or self.previous_wave_receipt_ref.issuer_id != "host"
            )
        ):
            raise ValueError("previous Build wave evidence has wrong contract or issuer")
        paths: set[str] = set()
        tasks: set[str] = set()
        batches: set[str] = set()
        for batch in self.batches:
            if batch.batch_id in batches:
                raise ValueError("duplicate Build batch")
            batches.add(batch.batch_id)
            for task in batch.tasks:
                if task.task_id in tasks:
                    raise ValueError("Build task scheduled more than once")
                tasks.add(task.task_id)
                for path in task.todo.authorized_paths:
                    if any(paths_overlap(path, occupied) for occupied in paths):
                        raise ValueError("overlapping Build wave paths")
                    paths.add(path)
        if set(self.expected_preimages) != paths:
            raise ValueError("wave preimage pins must cover every authorized path")
        for path, digest in self.expected_preimages.items():
            if safe_relative_path(path) != path:
                raise ValueError("non-canonical Build wave path")
            if self.wave_index == 1:
                expected = next(
                    task.todo.expected_preimages[path]
                    for batch in self.batches
                    for task in batch.tasks
                    if path in task.todo.expected_preimages
                )
                if digest != expected:
                    raise ValueError("first wave preimage differs from admitted TaskTodo")
        return self

    def require_action_preimages(self, action_id: str, observed: dict[str, str | None]) -> None:
        """Effect-time check for one action against this exact wave's pins."""
        paths = {
            path
            for batch in self.batches
            for task in batch.tasks
            if action_id in task.todo.source_action_ids
            for path in task.todo.authorized_paths
        }
        if not paths or set(observed) != paths:
            raise ValueError("action is absent from wave or preimage observation is incomplete")
        if any(observed[path] != self.expected_preimages[path] for path in paths):
            raise ValueError("Build wave preimage changed before effect")


class VerifiedWaveResult(ContractModel):
    """Host-accepted previous wave state used to pin the next wave."""

    wave_id: str = Field(min_length=1)
    accepted: bool
    output_digests: dict[str, Sha256 | None]
