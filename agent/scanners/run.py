"""Scanner CLI — run source scanners on a repository tree.

Usage:
    python -m agent.scanners.run [ROOT] [--scope SCOPE] [--scanners SC1,SC2,...] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.scanners.core import scan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run source scanners on a repository tree.")
    parser.add_argument("root", type=Path, help="Repository root directory.")
    parser.add_argument("--scope", default=".", help="Subdirectory to scan (default: '.').")
    parser.add_argument("--scanners", default="", help="Comma-separated scanner names.")
    parser.add_argument("--json", action="store_true", help="Output findings as JSON.")
    args = parser.parse_args(argv)

    scanners = tuple(args.scanners.split(",")) if args.scanners else ()
    result = scan(args.root, scope=args.scope, scanners=scanners)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"Scanners: {', '.join(result.scanners_run)}")
        print(f"Root: {result.root}")
        print(f"Findings: {len(result.findings)}")
        print(f"Limitations: {'; '.join(result.limitations)}")
        print()
        for finding in result.findings:
            print(f"[{finding.severity.upper()}] {finding.scanner}/{finding.code} at {finding.path}:{finding.line}")
            print(f"  {finding.message}")
            print()

    return 1 if result.has_findings else 0


if __name__ == "__main__":
    sys.exit(main())
