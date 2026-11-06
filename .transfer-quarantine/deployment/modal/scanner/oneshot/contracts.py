"""Validate persisted and exchanged records against packaged canonical schemas."""

import json
from dataclasses import asdict, dataclass
from functools import cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from oneshot.evidence import validate_receipt_identity


@cache
def validator(kind: str) -> Draft202012Validator:
    schema = json.loads(files("oneshot.schema").joinpath(f"{kind}.json").read_text("utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate(kind: str, value: dict[str, Any]) -> None:
    validator(kind).validate(value)
    if kind in {"source", "evidence"} and value["sha256"] != value["object_name"]:
        raise ValidationError("object name must match the source fingerprint")
    if kind == "task" and value["revision"] > value["budget"]:
        raise ValidationError("task revision cannot exceed its mutation budget")
    if kind == "evidence":
        validate_receipt_identity(value["receipt"])


@dataclass(frozen=True)
class Task:
    task_id: str
    thread_id: str
    owner: str
    objective: str
    summary: str
    checkpoint: str
    revision: int
    budget: int
    lifecycle: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        validate("task", result)
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Task":
        validate("task", value)
        return cls(**value)
