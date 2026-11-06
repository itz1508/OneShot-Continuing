"""Host-selected runtime roots and safe output allocation."""

from __future__ import annotations

import re
from pathlib import Path

_IDENTITY = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class RuntimeRootRegistry:
    """Only trusted host setup can register roots; callers select known IDs."""

    def __init__(self) -> None:
        self._roots: dict[str, Path] = {}

    def register(self, root_id: str, path: str | Path) -> None:
        if _IDENTITY.fullmatch(root_id) is None:
            raise ValueError("invalid runtime root identity")
        candidate = Path(path)
        if not candidate.is_absolute() or candidate.is_symlink():
            raise ValueError("runtime root must be an absolute non-symlink path")
        resolved = candidate.resolve(strict=False)
        if candidate != resolved:
            raise ValueError("runtime root traverses a symlink")
        if root_id in self._roots and self._roots[root_id] != resolved:
            raise ValueError("conflicting runtime root registration")
        self._roots[root_id] = resolved

    def resolve(self, root_id: str, *segments: str) -> Path:
        root = self._roots.get(root_id)
        if root is None:
            raise ValueError("runtime root is not registered")
        if any(_IDENTITY.fullmatch(segment) is None for segment in segments):
            raise ValueError("invalid runtime path segment")
        target = root.joinpath(*segments)
        if target.resolve(strict=False) != target:
            raise ValueError("runtime path traverses a symlink")
        return target
