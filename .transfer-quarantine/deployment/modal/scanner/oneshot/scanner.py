"""Deterministic duplicate, overlap, dependency and archive inspection."""

import ast
import base64
import binascii
import hashlib
import io
import json
import re
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from oneshot.contracts import validate
from oneshot.source import MAX_SOURCE_BYTES, SourceAccess

MAX_SCAN_BYTES = 32 * 1024 * 1024
MAX_EXCERPTS = 256
MAX_ANALYSIS_LINES = 20000
MAX_RESULT_BYTES = 512 * 1024
WINDOWS_RESERVED = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)
}


def inspect_archive(raw: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > 2000:
            raise ValueError("archive exceeds the 2000 entry limit")
        total = sum(item.file_size for item in entries)
        if total > 64 * 1024 * 1024:
            raise ValueError("archive expanded size exceeds 64 MiB")
        seen: set[str] = set()
        file_names: set[str] = set()
        metadata_bytes = 0
        for item in entries:
            name = item.orig_filename
            path = PurePosixPath(name)
            components = name.rstrip("/").split("/")
            normalized = name.rstrip("/").casefold()
            mode = item.external_attr >> 16
            metadata_bytes += len(name.encode("utf-8"))
            if (
                not name
                or len(name) > 1024
                or metadata_bytes > 64000
                or any(ord(character) < 32 for character in name)
                or any(
                    part in {"", ".", ".."}
                    or part.endswith((".", " "))
                    or part.split(".")[0].casefold() in WINDOWS_RESERVED
                    for part in components
                )
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in name
                or ":" in name
                or stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}
                or normalized in seen
            ):
                raise ValueError(f"unsafe or ambiguous archive entry: {name}")
            if item.file_size > MAX_SOURCE_BYTES or item.flag_bits & 1:
                raise ValueError(f"oversized or encrypted archive entry: {name}")
            seen.add(normalized)
            if not item.is_dir():
                file_names.add(normalized)
        for name in seen:
            if any(str(parent) in file_names for parent in PurePosixPath(name).parents):
                raise ValueError(f"unsafe archive hierarchy: {name}")
        return {
            "entries": [{"name": item.filename, "size": item.file_size} for item in entries],
            "expanded_bytes": total,
            "content_inspected": False,
        }


def scan(
    sources: list[dict[str, Any]],
    access: SourceAccess,
    query: str,
    maximum_bytes: int,
    baseline_source_id: str | None = None,
) -> dict[str, Any]:
    if not 1 <= len(sources) <= 32:
        raise ValueError("scan requires between 1 and 32 admitted sources")
    if not 1 <= maximum_bytes <= 256 * 1024:
        raise ValueError("reduced output budget must be between 1 and 256 KiB")
    if sum(source["size"] for source in sources) > MAX_SCAN_BYTES:
        raise ValueError("scan exceeds the 32 MiB aggregate source limit")
    if len(query) > 10000:
        raise ValueError("query exceeds 10000 characters")
    identities = [source["source_id"] for source in sources]
    if baseline_source_id is not None and baseline_source_id not in identities:
        raise ValueError("baseline must identify one of the admitted input sources")
    digests: dict[str, list[str]] = {}
    documents: list[dict[str, Any]] = []
    excerpts: list[dict[str, Any]] = []
    line_sets: list[set[str]] = []
    remaining = maximum_bytes
    terms = set(re.findall(r"\w+", query.casefold()))
    for source in sources:
        raw = access.get(source["object_name"])
        digests.setdefault(source["sha256"], []).append(source["source_id"])
        document: dict[str, Any] = {
            "source_id": source["source_id"],
            "name": source["name"],
            "sha256": source["sha256"],
            "size": len(raw),
        }
        documents.append(document)
        if zipfile.is_zipfile(io.BytesIO(raw)):
            document["archive"] = inspect_archive(raw)
            document["coverage"] = "metadata_only"
            line_sets.append(set())
            continue
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            document["coverage"] = "unsupported_encoding"
            line_sets.append(set())
            continue
        if "\x00" in content:
            document["coverage"] = "binary_unsupported"
            line_sets.append(set())
            continue
        compared_lines: set[str] = set()
        line_sets.append(compared_lines)
        document["analysis_limited"] = False
        if source["name"].endswith(".py") and len(raw) > 1024 * 1024:
            document["dependency_error"] = "Python syntax analysis exceeds its 1 MiB limit"
        elif source["name"].endswith(".py"):
            try:
                tree = ast.parse(content)
            except (SyntaxError, RecursionError, ValueError) as exc:
                document["dependency_error"] = str(exc)
            else:
                imports: set[str] = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.update(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        prefix = "." * node.level
                        if node.module:
                            imports.add(prefix + node.module)
                        else:
                            imports.update(prefix + alias.name for alias in node.names)
                ordered = sorted(imports)
                document["imports"] = [name for name in ordered[:512] if len(name) <= 512]
                if len(document["imports"]) != len(ordered):
                    document["dependency_error"] = "Import output limited to 512 names of 512 characters"
        selected_bytes = 0
        offset = 0
        for number, line in enumerate(io.StringIO(content, newline=""), 1):
            if number > MAX_ANALYSIS_LINES:
                document["analysis_limited"] = True
                break
            if line.strip():
                compared_lines.add(line.strip())
            encoded = line.encode("utf-8")
            size = len(encoded)
            if (
                (not terms or terms.intersection(re.findall(r"\w+", line.casefold())))
                and size <= remaining
                and len(excerpts) < MAX_EXCERPTS
            ):
                excerpts.append(
                    {
                        "source_id": source["source_id"],
                        "sha256": source["sha256"],
                        "line": number,
                        "start_byte": offset,
                        "end_byte": offset + size,
                        "content": line,
                    }
                )
                remaining -= size
                selected_bytes += size
            offset += size
        document["coverage"] = "complete" if selected_bytes == len(raw) else "partial"
        document["selected_bytes"] = selected_bytes
    overlaps = []
    for left in range(len(sources)):
        for right in range(left + 1, len(sources)):
            union = line_sets[left] | line_sets[right]
            shared = line_sets[left] & line_sets[right]
            if shared:
                overlaps.append(
                    {
                        "left": sources[left]["source_id"],
                        "right": sources[right]["source_id"],
                        "shared_lines": len(shared),
                        "jaccard": len(shared) / len(union),
                    }
                )
    comparisons = []
    if baseline_source_id is not None:
        baseline = identities.index(baseline_source_id)
        for target, source in enumerate(sources):
            if target == baseline:
                continue
            supported = all("analysis_limited" in documents[index] for index in (baseline, target))
            coverage = (
                "unsupported"
                if not supported
                else "partial"
                if any(documents[index]["analysis_limited"] for index in (baseline, target))
                else "complete"
            )
            comparisons.append(
                {
                    "baseline_id": baseline_source_id,
                    "target_id": source["source_id"],
                    "baseline_sha256": sources[baseline]["sha256"],
                    "target_sha256": source["sha256"],
                    "byte_relation": "identical" if sources[baseline]["sha256"] == source["sha256"] else "different",
                    "comparison_coverage": coverage,
                    "added_distinct_lines": len(line_sets[target] - line_sets[baseline]) if supported else None,
                    "removed_distinct_lines": len(line_sets[baseline] - line_sets[target]) if supported else None,
                }
            )
    result = {
        "mode": "extractive",
        "query": query,
        "documents": documents,
        "exact_duplicates": [ids for ids in digests.values() if len(ids) > 1],
        "line_overlaps": overlaps,
        "baseline_comparisons": comparisons,
        "excerpts": excerpts,
        "output_bytes": maximum_bytes - remaining,
        "limitations": [
            "Lexical extraction does not establish semantic equivalence or completeness.",
            "Archive inspection reports metadata only and does not extract entries.",
            "Comparison inspects 20000 lines per source; analysis_limited reports this.",
            "Extractive output contains at most 256 excerpts across all sources.",
        ],
    }
    if len(json.dumps(result).encode("utf-8")) > MAX_RESULT_BYTES:
        raise ValueError("scan result exceeds 512 KiB; reduce sources, excerpt budget or query scope")
    return result


def scan_request(request: dict[str, Any]) -> dict[str, Any]:
    """Inspect hash-bound serialized snapshots without granting any local filesystem access."""
    validate("scan_request", request)
    if len(json.dumps(request).encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("serialized scan request exceeds 2 MiB")
    references = []
    contents: dict[str, bytes] = {}
    total = 0
    for item in request["sources"]:
        source = item["reference"]
        validate("source", source)
        identity = source["source_id"]
        if identity in contents:
            raise ValueError("serialized source IDs must be unique")
        try:
            raw = base64.b64decode(item["content_base64"], validate=True)
        except binascii.Error as exc:
            raise ValueError("invalid base64 source payload") from exc
        total += len(raw)
        if total > 1024 * 1024:
            raise ValueError("serialized Scanner input exceeds 1 MiB")
        if len(raw) != source["size"] or hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("source payload size or fingerprint does not match its admitted reference")
        references.append(source)
        contents[identity] = raw
    with tempfile.TemporaryDirectory(prefix="oneshot-scan-") as directory:
        access = SourceAccess(Path(directory), {})
        for source in references:
            access.put(contents[source["source_id"]])
        result = scan(
            references,
            access,
            request["query"],
            request["maximum_bytes"],
            request.get("baseline_source_id"),
        )
        validate("scan", result)
        return result
