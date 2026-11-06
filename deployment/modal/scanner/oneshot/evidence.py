"""Source identity and execution receipts for independent verifier commands."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from oneshot.source import MAX_SOURCE_BYTES, open_authorized

EXCLUDED_DIRECTORIES = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "dist",
    "node_modules",
}


def fingerprint(manifest: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source_manifest(root: Path, excluded: Path | None = None) -> dict[str, str]:
    root = root.resolve(strict=True)
    ignored = excluded.resolve() if excluded else None
    result: dict[str, str] = {}
    total = 0
    for directory, folders, names in os.walk(root, followlinks=False):
        folders[:] = sorted(name for name in folders if name not in EXCLUDED_DIRECTORIES)
        for name in folders:
            folder = Path(directory) / name
            if folder.is_symlink() or folder.is_junction():
                raise PermissionError("source fingerprints do not traverse links or junctions")
        for name in sorted(names):
            path = Path(directory) / name
            if name == ".env" or name.startswith(".env.") or path.resolve() == ignored:
                continue
            if path.is_symlink() or path.is_junction():
                raise PermissionError("source fingerprints do not follow file links")
            if len(result) >= 5000:
                raise ValueError("source fingerprint exceeds 5000 files")
            with open_authorized(path.resolve(strict=True), root) as handle:
                before = os.fstat(handle.fileno())
                if before.st_size > MAX_SOURCE_BYTES:
                    raise ValueError(f"source fingerprint file exceeds 8 MiB: {name}")
                total += before.st_size
                if total > 128 * 1024 * 1024:
                    raise ValueError("source fingerprint exceeds 128 MiB")
                raw = handle.read(MAX_SOURCE_BYTES + 1)
                after = os.fstat(handle.fileno())
                if len(raw) != before.st_size or (before.st_size, before.st_mtime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise ValueError("source changed while computing its fingerprint")
            result[path.relative_to(root).as_posix()] = hashlib.sha256(raw).hexdigest()
    return result


def validate_receipt_identity(receipt: dict[str, Any]) -> None:
    manifest = receipt["source_files"]
    for name in manifest:
        path = Path(name)
        if path.is_absolute() or path.drive or ".." in path.parts or "\\" in name or ":" in name:
            raise ValueError("receipt source names must be relative portable paths")
    expected = fingerprint(manifest)
    if (
        receipt["source_before_sha256"] != expected
        or receipt["source_after_sha256"] != expected
        or not receipt["source_unchanged"]
    ):
        raise ValueError("receipt source identity is inconsistent or changed during verification")


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute a check and fingerprint its sources")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--revision", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.revision < 0 or args.timeout <= 0:
        parser.error("command, nonnegative revision and positive timeout are required")
    if args.output.exists():
        parser.error("receipt output already exists; command was not executed")
    before = source_manifest(args.cwd, args.output)
    try:
        result = subprocess.run(
            command,
            cwd=args.cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout,
            check=False,
        )
        exit_code = result.returncode
        observed = result.stdout + result.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        observed = f"Command timed out after {args.timeout} seconds: {exc}"
    except OSError as exc:
        exit_code = 127
        observed = f"Command could not start: {exc}"
    after = source_manifest(args.cwd, args.output)
    unchanged = before == after
    receipt = {
        "task_id": args.task_id,
        "thread_id": args.thread_id,
        "revision": args.revision,
        "command": command,
        "cwd": str(args.cwd.resolve()),
        "receipt_path": str(args.output.resolve()),
        "exit_code": exit_code,
        "observed": observed or "Command produced no output.",
        "timestamp": datetime.now(UTC).isoformat(),
        "source_files": before,
        "source_before_sha256": fingerprint(before),
        "source_after_sha256": fingerprint(after),
        "source_unchanged": unchanged,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(receipt, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    print(observed, end="")
    print(f"receipt: {args.output.resolve()}")
    print(f"sha256: {hashlib.sha256(args.output.read_bytes()).hexdigest()}")
    if not unchanged:
        print("Source changed during the command; evidence is not valid.", file=sys.stderr)
    sys.exit(exit_code if exit_code else 0 if unchanged else 1)


if __name__ == "__main__":
    main()
