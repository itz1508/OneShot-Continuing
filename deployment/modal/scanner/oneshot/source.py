"""Bounded admission into content-addressed snapshots outside inspected repositories."""

import hashlib
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, BinaryIO
from uuid import NAMESPACE_URL, uuid5

MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_READ_BYTES = 256 * 1024


def open_authorized(path: Path, root: Path) -> BinaryIO:
    """Bind validation to the opened handle, including a parent-directory replacement race."""
    if sys.platform != "win32":
        relative = path.relative_to(root)
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in relative.parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
        return open(descriptor, "rb", closefd=True)

    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    final_path = kernel.GetFinalPathNameByHandleW
    final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    final_path.restype = wintypes.DWORD
    # Deny writes/deletes for the read; OPEN_REPARSE_POINT prevents a final symlink traversal.
    handle = create(str(path), 0x80000000, 1, None, 3, 0x00200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    transferred = False
    try:
        required = final_path(handle, None, 0, 0)
        if not required:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(required + 1)
        written = final_path(handle, buffer, len(buffer), 0)
        if not written or written >= len(buffer):
            raise OSError("could not determine the opened source path")
        physical = buffer.value
        if physical.startswith("\\\\?\\UNC\\"):
            physical = "\\\\" + physical[8:]
        elif physical.startswith("\\\\?\\"):
            physical = physical[4:]
        if not Path(physical).is_relative_to(root):
            raise PermissionError("opened source escaped the configured root")
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        transferred = True
        return open(descriptor, "rb", closefd=True)
    finally:
        if not transferred:
            close(handle)


class SourceAccess:
    def __init__(self, objects: Path, roots: dict[str, Path]) -> None:
        self.objects = objects
        self.roots = {name: root.resolve(strict=True) for name, root in roots.items()}
        objects.mkdir(parents=True, exist_ok=True)

    def snapshot(self, root_name: str, relative_name: str) -> tuple[str, bytes]:
        if root_name not in self.roots:
            raise PermissionError("source root is not configured by the host")
        relative = Path(relative_name)
        if (
            not relative_name
            or relative.is_absolute()
            or relative.drive
            or ".." in relative.parts
            or ":" in relative_name
        ):
            raise PermissionError("source path must be relative without traversal or streams")
        root = self.roots[root_name]
        candidate = root
        for part in relative.parts:
            candidate = candidate / part
            metadata = candidate.lstat()
            attributes = getattr(metadata, "st_file_attributes", 0)
            if stat.S_ISLNK(metadata.st_mode) or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise PermissionError("symlinks and reparse points are not admitted")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise PermissionError("source is outside its configured root or is not a regular file")
        with open_authorized(resolved, root) as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise PermissionError("opened source is not a regular file")
            if not os.path.samestat(opened, candidate.stat()):
                raise PermissionError("source identity changed while opening")
            if opened.st_size > MAX_SOURCE_BYTES:
                raise ValueError("source exceeds the 8 MiB admission limit")
            raw = handle.read(MAX_SOURCE_BYTES + 1)
            after = os.fstat(handle.fileno())
            if (
                len(raw) > MAX_SOURCE_BYTES
                or opened.st_size != len(raw)
                or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            ):
                raise ValueError("source changed during admission or exceeded its limit")
            if not os.path.samestat(after, candidate.stat()):
                raise PermissionError("source path changed during admission")
        digest = hashlib.sha256(raw).hexdigest()
        return digest, raw

    def put(self, raw: bytes) -> str:
        if len(raw) > MAX_SOURCE_BYTES:
            raise ValueError("object exceeds the 8 MiB limit")
        digest = hashlib.sha256(raw).hexdigest()
        target = self.objects / digest
        if target.exists():
            if self.get(digest) != raw:
                raise ValueError("content-addressed object collision or corruption")
            return digest
        with tempfile.NamedTemporaryFile(dir=self.objects, prefix=".pending-", delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            except BaseException:
                handle.close()
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return digest

    def get(self, digest: str) -> bytes:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid object fingerprint")
        with (self.objects / digest).open("rb") as handle:
            raw = handle.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("source snapshot integrity check failed")
        return raw

    def admit(self, thread_id: str, task_id: str, root: str, name: str) -> dict[str, Any]:
        digest, raw = self.snapshot(root, name)
        self.put(raw)
        identity = f"{thread_id}/{task_id}/{root}/{name}/{digest}"
        return {
            "source_id": str(uuid5(NAMESPACE_URL, identity)),
            "task_id": task_id,
            "thread_id": thread_id,
            "name": name,
            "sha256": digest,
            "size": len(raw),
            "object_name": digest,
        }

    def extract(self, source: dict[str, Any], start: int, maximum: int) -> dict[str, Any]:
        if type(start) is not int or type(maximum) is not int:
            raise ValueError("byte offsets and limits must be integers")
        if start < 0 or maximum < 0 or maximum > MAX_READ_BYTES:
            raise ValueError("invalid byte range; maximum is 256 KiB")
        raw = self.get(source["object_name"])
        if start > len(raw):
            raise ValueError("start byte is beyond the source")
        end = min(start + maximum, len(raw))
        try:
            content = raw[start:end].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("range is not UTF-8; select complete character boundaries") from exc
        if "\x00" in content:
            raise ValueError("binary source is not supported for text extraction")
        return {
            "source_id": source["source_id"],
            "sha256": source["sha256"],
            "start_byte": start,
            "end_byte": end,
            "source_size": len(raw),
            "content": content,
            "complete_source": start == 0 and end == len(raw),
            "truncated": start > 0 or end < len(raw),
        }
