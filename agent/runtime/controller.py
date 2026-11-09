"""Compatibility API: one implementation lives in system.host.controller."""

from system.host.controller import (
    HostController as HostController,
    Stage as Stage,
    STAGE_ORDER as STAGE_ORDER,
    TaskState as TaskState,
    TransitionError as TransitionError,
)
