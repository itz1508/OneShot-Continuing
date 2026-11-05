"""Scanner: detect effect executor gaps: missing prior-attempt checks."""

from __future__ import annotations

import ast
from pathlib import Path

from agent.scanners.core import Finding, _file_digest, _parse_ast


def scan_effect_executor(root: Path, scope: Path) -> list[Finding]:
    """Find execute_admitted methods that don't check for prior crashed attempts."""
    findings: list[Finding] = []

    for path in _python_files_recursive(root, scope):
        tree = _parse_ast(path)
        if tree is None:
            continue

        # 1. Check execute_admitted for missing prior-attempt detection
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if "execute" not in node.name or "admitted" not in node.name:
                continue
            src = ast.unparse(node)
            has_prior_check = "_has_pre_effect_checkpoint" in src and "prior" in src.lower()
            if not has_prior_check:
                rel = path.relative_to(root).as_posix()
                findings.append(
                    Finding(
                        scanner="effect_executor",
                        code="MISSING_PRIOR_ATTEMPT_CHECK",
                        severity="high",
                        path=rel,
                        line=node.lineno,
                        message=(f"{node.name}() missing prior crashed attempt pre-effect checkpoint check"),
                        evidence_digest=_file_digest(path),
                    )
                )

        # 2. Check _clear_pre_effect_checkpoint for missing guard
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if "clear" not in node.name.lower():
                continue
            child_src = ast.unparse(node)
            if "pre_effect" not in child_src:
                continue
            if (
                child_src.count("checkpoint_cas") > 0
                and "load_checkpoint" not in child_src
                and "is None" not in child_src
            ):
                rel = path.relative_to(root).as_posix()
                findings.append(
                    Finding(
                        scanner="effect_executor",
                        code="CLEAR_FAILS_ON_MISSING_CHECKPOINT",
                        severity="medium",
                        path=rel,
                        line=node.lineno,
                        message=(f"{node.name}() calls checkpoint_cas without checking if pre-effect exists"),
                        evidence_digest=_file_digest(path),
                    )
                )

    return findings


def _python_files_recursive(root: Path, scope: Path):
    from agent.scanners.core import _python_files

    yield from _python_files(root, scope)
