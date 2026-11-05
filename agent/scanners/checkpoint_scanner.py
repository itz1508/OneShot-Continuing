"""Scanner: detect checkpoint read paths that skip integrity verification."""

from __future__ import annotations

import ast
from pathlib import Path

from agent.scanners.core import Finding, _file_digest, _parse_ast

_DIGEST_FUNCS = {"digest", "hexdigest", "digest_raw", "sha256"}


def scan_checkpoint_integrity(root: Path, scope: Path) -> list[Finding]:
    """Find load/get methods that return stored data without digest verification."""
    findings: list[Finding] = []

    for path in _python_files_recursive(root, scope):
        tree = _parse_ast(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not any(name in node.name for name in ("load", "get")):
                continue
            src = ast.unparse(node)
            if "state_digest" not in src and "digest" not in node.name.lower():
                continue
            has_recalc = any(
                isinstance(n, ast.Call)
                and (
                    (isinstance(n.func, ast.Attribute) and n.func.attr in _DIGEST_FUNCS)
                    or (isinstance(n.func, ast.Name) and n.func.id in _DIGEST_FUNCS)
                )
                for n in ast.walk(node)
            )
            has_compare = any(isinstance(n, ast.Compare) for n in ast.walk(node))
            has_return = any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(node))
            if has_return and not (has_recalc and has_compare):
                rel = path.relative_to(root).as_posix()
                findings.append(
                    Finding(
                        scanner="checkpoint_integrity",
                        code="DIGEST_NOT_VERIFIED_ON_READ",
                        severity="high",
                        path=rel,
                        line=node.lineno,
                        message=(
                            f"Method {node.name}() returns stored data without recalculating and comparing digest"
                        ),
                        evidence_digest=_file_digest(path),
                    )
                )
    return findings


def _python_files_recursive(root: Path, scope: Path):
    from agent.scanners.core import _python_files

    yield from _python_files(root, scope)
