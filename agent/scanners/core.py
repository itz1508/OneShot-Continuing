"""Scanner core — Finding model and scan orchestrator."""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    """A single scanner observation with stable identity."""

    scanner: str
    code: str
    severity: str
    path: str
    line: int
    message: str
    evidence_digest: str = ""


@dataclass(frozen=True)
class ScannerResult:
    """Result of running all scanners on a source tree."""

    root: str
    findings: tuple[Finding, ...]
    scanners_run: tuple[str, ...]
    limitations: tuple[str, ...] = ()

    @property
    def has_findings(self) -> bool:
        return len(self.findings) > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "root": self.root,
            "scanners_run": list(self.scanners_run),
            "findings_count": len(self.findings),
            "findings": [
                {
                    "scanner": f.scanner,
                    "code": f.code,
                    "severity": f.severity,
                    "path": f.path,
                    "line": f.line,
                    "message": f.message,
                    "finding_id": "SCP-"
                    + hashlib.sha256(f"{f.scanner}|{f.path}|{f.line}|{f.code}".encode()).hexdigest()[:16],
                }
                for f in self.findings
            ],
            "limitations": list(self.limitations),
        }


def _python_files(root: Path, scope: Path) -> Iterable[Path]:
    """Yield Python files in scope, excluding venvs and caches."""
    for path in sorted(scope.rglob("*.py")):
        if any(
            part in {".git", ".venv", "venv", "__pycache__", "node_modules"} for part in path.relative_to(root).parts
        ):
            continue
        if path.is_file() and not path.is_symlink():
            yield path


def _file_digest(path: Path) -> str:
    """SHA-256 of file bytes for evidence."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_ast(path: Path) -> ast.AST | None:
    """Parse a Python file, returning None on syntax error."""
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None


Scanner = Callable[[Path, Path], list[Finding]]


def scan(root: Path, scope: str = ".", scanners: tuple[str, ...] = ()) -> ScannerResult:
    """Run scanner tools on a source tree. Returns structured findings."""
    from agent.scanners.attempt_scanner import scan_attempt_identity
    from agent.scanners.checkpoint_scanner import scan_checkpoint_integrity
    from agent.scanners.effect_scanner import scan_effect_executor
    from agent.scanners.recovery_scanner import scan_recovery_classification
    from agent.scanners.schema_scanner import scan_schema_compatibility

    available: dict[str, Scanner] = {
        "checkpoint_integrity": scan_checkpoint_integrity,
        "schema_compatibility": scan_schema_compatibility,
        "attempt_identity": scan_attempt_identity,
        "recovery_classification": scan_recovery_classification,
        "effect_executor": scan_effect_executor,
    }

    requested = scanners or tuple(available)
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise ValueError(f"unknown scanners: {', '.join(unknown)}")

    root = root.resolve(strict=True)
    target = (root / scope).resolve(strict=True)
    if not target.is_relative_to(root):
        raise ValueError("scan scope escapes repository root")

    findings: list[Finding] = []
    executed: list[str] = []
    for name in dict.fromkeys(requested):
        try:
            findings.extend(available[name](root, target))
            executed.append(name)
        except (OSError, UnicodeError, SyntaxError, ValueError):
            executed.append(name)

    findings.sort(key=lambda f: (f.scanner, f.path, f.line, f.code))
    limitations = (
        "Static observations are not runtime verification.",
        "AST-based; dynamic wiring requires runtime evidence.",
    )
    return ScannerResult(
        root=str(root),
        findings=tuple(findings),
        scanners_run=tuple(executed),
        limitations=limitations,
    )
