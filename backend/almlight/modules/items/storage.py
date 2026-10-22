"""Content-addressed file store on the local filesystem (a volume in Docker).

Files are stored once per SHA-256 under ``files/ab/cd/<sha256>`` and never modified,
which makes versioned attachments and baselines cheap and exact. An S3-compatible
backend can implement the same three functions later.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO

from almlight.core.config import get_settings
from almlight.core.errors import ValidationFailed

CHUNK = 1024 * 1024


def blob_path(sha256: str) -> Path:
    return get_settings().files_dir / sha256[:2] / sha256[2:4] / sha256


def store(stream: BinaryIO) -> tuple[str, int]:
    """Stream into the store; returns (sha256, size). Enforces the configured upload limit."""
    settings = get_settings()
    limit = settings.max_upload_mb * 1024 * 1024
    settings.files_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    fd, tmp_name = tempfile.mkstemp(dir=settings.files_dir, prefix=".upload-")
    try:
        with os.fdopen(fd, "wb") as tmp:
            while chunk := stream.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise ValidationFailed(f"File exceeds the upload limit of {settings.max_upload_mb} MB")
                digest.update(chunk)
                tmp.write(chunk)
        sha = digest.hexdigest()
        target = blob_path(sha)
        if target.exists():
            os.unlink(tmp_name)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(tmp_name, target)
        return sha, size
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def exists(sha256: str) -> bool:
    return blob_path(sha256).exists()
