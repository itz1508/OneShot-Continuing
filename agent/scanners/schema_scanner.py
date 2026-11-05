"""Scanner: detect SQLite tables that share names across stores with incompatible schemas."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from agent.scanners.core import Finding, _file_digest, _parse_ast


def scan_schema_compatibility(root: Path, scope: Path) -> list[Finding]:
    """Find CREATE TABLE statements using the same table name with different columns."""
    findings: list[Finding] = []
    table_defs: dict[str, list[tuple[str, int, Path, set[str]]]] = {}

    for path in _python_files_recursive(root, scope):
        src = path.read_text(encoding="utf-8")
        for match in re.finditer(
            r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\(([^)]+)\)", src, re.IGNORECASE | re.DOTALL
        ):
            table_name = match.group(1)
            cols_str = match.group(2)
            line = src[: match.start()].count("\n") + 1
            cols = {c.strip().split()[0].lower() for c in cols_str.split(",") if c.strip()}
            table_defs.setdefault(table_name, []).append((str(path), line, path, cols))

    for table_name, defs in table_defs.items():
        if len(defs) < 2:
            continue
        col_sets = [d[3] for d in defs]
        if any(cols != col_sets[0] for cols in col_sets[1:]):
            for _file_path, line, path, cols in defs:
                rel = path.relative_to(root).as_posix()
                findings.append(
                    Finding(
                        scanner="schema_compatibility",
                        code="SHARED_TABLE_NAME_MISMATCHED_SCHEMA",
                        severity="high",
                        path=rel,
                        line=line,
                        message=f"Table '{table_name}' defined with different columns in multiple stores: {cols}",
                        evidence_digest=_file_digest(path),
                    )
                )

    # Also check for missing schema compatibility checks
    for path in _python_files_recursive(root, scope):
        tree = _parse_ast(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name != "_init_db" and not node.name.startswith("__init__"):
                continue
            src = ast.unparse(node)
            if "CREATE TABLE" in src and "PRAGMA table_info" not in src and "SchemaCompatibilityError" not in src:
                rel = path.relative_to(root).as_posix()
                findings.append(
                    Finding(
                        scanner="schema_compatibility",
                        code="MISSING_SCHEMA_COMPATIBILITY_CHECK",
                        severity="medium",
                        path=rel,
                        line=node.lineno,
                        message=f"{node.name}() creates tables without checking for incompatible existing schemas",
                        evidence_digest=_file_digest(path),
                    )
                )
    return findings


def _python_files_recursive(root: Path, scope: Path):
    from agent.scanners.core import _python_files

    yield from _python_files(root, scope)
