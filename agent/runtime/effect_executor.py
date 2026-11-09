"""Compatibility API: one implementation lives in system.runtime.execution.executor."""

from system.runtime.execution.executor import (
    _is_within as _is_within,
    EffectExecutionError as EffectExecutionError,
    EffectExecutor as EffectExecutor,
)
