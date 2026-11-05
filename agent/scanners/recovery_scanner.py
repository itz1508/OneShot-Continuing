"""Scanner: detect recovery methods that return strings instead of structured results."""

from __future__ import annotations

import ast
from pathlib import Path

from agent.scanners.core import Finding, _file_digest, _parse_ast


def scan_recovery_classification(root: Path, scope: Path) -> list[Finding]:
    """Find reconcile() methods that return strings instead of structured data."""
    findings: list[Finding] = []

    for path in _python_files_recursive(root, scope):
        tree = _parse_ast(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if "reconcile" not in node.name:
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and child.value is not None:
                    if isinstance(child.value, ast.Constant) and isinstance(child.value.value, str):
                        rel = path.relative_to(root).as_posix()
                        findings.append(
                            Finding(
                                scanner="recovery_classification",
                                code="RECONCILE_RETURNS_STRING",
                                severity="medium",
                                path=rel,
                                line=child.lineno,
                                message=(f"{node.name}() returns a string instead of structured recovery result"),
                                evidence_digest=_file_digest(path),
                            )
                        )
                    elif isinstance(child.value, ast.JoinedStr):
                        rel = path.relative_to(root).as_posix()
                        findings.append(
                            Finding(
                                scanner="recovery_classification",
                                code="RECONCILE_RETURNS_FSTRING",
                                severity="medium",
                                path=rel,
                                line=child.lineno,
                                message=f"{node.name}() returns an f-string instead of structured recovery result",
                                evidence_digest=_file_digest(path),
                            )
                        )
    return findings


def _python_files_recursive(root: Path, scope: Path):
    from agent.scanners.core import _python_files

    yield from _python_files(root, scope)
