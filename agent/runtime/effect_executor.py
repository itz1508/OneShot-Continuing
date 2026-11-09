"""Compatibility API: one implementation lives in system.runtime.execution.executor."""

from system.runtime.execution.executor import (
    EffectExecutionError as EffectExecutionError,
    _is_within as _is_within,
    EffectExecutor as EffectExecutor,
)
