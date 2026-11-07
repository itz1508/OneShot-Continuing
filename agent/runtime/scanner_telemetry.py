"""Optional Logfire observation of authoritative scanner work.

Disabled by default. Never export source, evidence payloads, or prompts.
The ArtifactStore is the record of truth; spans cannot authorize edits.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Iterator

_attempted = False
_enabled = False


def configure_logfire() -> None:
    """Configure at most once on application startup; fail open for telemetry only."""
    global _attempted, _enabled
    if _attempted:
        return
    _attempted = True
    if os.environ.get("ONESHOT_LOGFIRE_ENABLED") != "1":
        return
    try:
        import logfire

        logfire.configure()
        _enabled = True
    except Exception:
        _enabled = False


@contextmanager
def scanner_span(task_id: str, run_id: str, artifact_id: str) -> Iterator[None]:
    """Exporter failures cannot replace or interrupt host-owned persistence."""
    if not _enabled:
        yield
        return
    try:
        import logfire

        span = logfire.span(
            "scanner.run",
            task_id=task_id,
            run_id=run_id,
            artifact_id=artifact_id,
        )
        span.__enter__()
    except Exception:
        yield
        return
    try:
        yield
    finally:
        try:
            span.__exit__(*sys.exc_info())
        except Exception:
            pass
