"""Scanner: detect checkpoint keys that lack attempt identity for retry safety."""

from __future__ import annotations

import ast
from pathlib import Path

from agent.scanners.core import Finding, _file_digest, _parse_ast


def scan_attempt_identity(root: Path, scope: Path) -> list[Finding]:
    """Find pre-effect checkpoint keys that don't include attempt identity."""
    findings: list[Finding] = []

    for path in _python_files_recursive(root, scope):
        tree = _parse_ast(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            node_src = ast.unparse(node)
            # Look for pre-effect checkpoint key patterns
            if ("pre-effect" in node_src or "pre_effect" in node_src) and "attempt" not in node_src.lower():
                rel = path.relative_to(root).as_posix()
                line = node.lineno
                findings.append(
                    Finding(
                        scanner="attempt_identity",
                        code="MISSING_ATTEMPT_IDENTITY",
                        severity="high",
                        path=rel,
                        line=line,
                        message="Pre-effect checkpoint key lacks attempt number; retry identity collision risk",
                        evidence_digest=_file_digest(path),
                    )
                )
    return findings


def _python_files_recursive(root: Path, scope: Path):
    from agent.scanners.core import _python_files

    yield from _python_files(root, scope)
