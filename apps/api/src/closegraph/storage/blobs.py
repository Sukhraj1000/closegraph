"""Bounded, scoped content addressing with atomic create-only writes.

Scope is server-resolved by the caller. A hash is an identifier, not permission.
Local filesystem ownership remains an installation responsibility.
"""
import hashlib
import errno
import json
import os
import re
import secrets
import stat
import shutil
from contextlib import contextmanager
from pathlib import Path

from closegraph.contracts import Scope


class BlobNotFound(FileNotFoundError): pass
class BlobIntegrityError(OSError): pass


class LocalBlobStore:
    def __init__(self, root: str | Path, *, max_bytes: int = 32 * 1024 * 1024):
        if max_bytes < 1: raise ValueError("max_bytes must be positive")
        original = Path(root).absolute()
        if any(p.is_symlink() for p in (original, *original.parents)):
            raise ValueError("blob root must not contain symlinks")
        original.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root, self.max_bytes = original, max_bytes

    @contextmanager
    def _directory(self, scope: Scope, *, create=False):
        scope = Scope.model_validate(scope)
        namespace = hashlib.sha256(json.dumps(scope.model_dump(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = None
        try:
            if create:
                try: os.mkdir(namespace, mode=0o700, dir_fd=root_fd)
                except FileExistsError: pass
            try:
                fd = os.open(namespace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
            except FileNotFoundError as exc:
                raise BlobNotFound("blob not found") from exc
            except OSError as exc:
                raise BlobIntegrityError("invalid blob namespace") from exc
            yield fd
        finally:
            if fd is not None: os.close(fd)
            os.close(root_fd)

    def _read(self, directory, key):
        try:
            fd = os.open(key, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError as exc:
            raise BlobNotFound("blob not found") from exc
        except OSError as exc:
            raise BlobIntegrityError("invalid blob object") from exc
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > self.max_bytes:
                raise BlobIntegrityError("blob has invalid type or size")
            data = stream.read(self.max_bytes + 1)
        if len(data) > self.max_bytes or hashlib.sha256(data).hexdigest() != key:
            raise BlobIntegrityError("blob content does not match its immutable hash")
        return data

    def read(self, scope: Scope, key: str) -> bytes:
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("invalid content hash")
        with self._directory(scope) as directory:
            return self._read(directory, key)

    def put(self, scope: Scope, data: bytes) -> str:
        if not isinstance(data, bytes) or len(data) > self.max_bytes:
            raise ValueError("blob requires bytes within the configured limit")
        key = hashlib.sha256(data).hexdigest()
        with self._directory(scope, create=True) as directory:
            # A retry of an immutable object needs no second on-disk copy.
            try:
                self._read(directory, key)
                return key
            except BlobNotFound:
                pass
            if shutil.disk_usage(self.root).free < len(data) + 64 * 1024 * 1024:
                raise OSError(errno.ENOSPC, "Storage is full. Free disk space on the app's computer, then retry.")
            temp = ".upload-" + secrets.token_hex(16)
            fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data); stream.flush(); os.fchmod(stream.fileno(), 0o400); os.fsync(stream.fileno())
                try:
                    os.link(temp, key, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                    os.fsync(directory)
                except FileExistsError:
                    self._read(directory, key)
            finally:
                os.unlink(temp, dir_fd=directory)
        return key
