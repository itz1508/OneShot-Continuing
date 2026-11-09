"""Compatibility API: one implementation lives in system.host.controller."""

from system.host.controller import (
    Stage as Stage,
    STAGE_ORDER as STAGE_ORDER,
    TransitionError as TransitionError,
    TaskState as TaskState,
    HostController as HostController,
)
