"""Storing, resolving and authorising images that are embedded in rich text."""

from __future__ import annotations

import base64
import binascii
import io
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from almlight.core.config import get_settings
from almlight.core.errors import DomainError, ValidationFailed
from almlight.core.richtext import IMAGE_PREFIX, IMAGE_SRC
from almlight.modules.identity.models import User
from almlight.modules.images.models import InlineImage
from almlight.modules.items import storage
from almlight.modules.items.models import Blob
from almlight.modules.projects.models import Project, ProjectMember

# SVG is deliberately not accepted: it can carry scripts.
FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
_DATA_URI = re.compile(r"^data:(image/[a-z0-9.+-]+);base64,(.*)$", re.IGNORECASE | re.DOTALL)


class UnsupportedMedia(DomainError):
    status_code = 415
    code = "unsupported_media_type"


class TooLarge(DomainError):
    status_code = 413
    code = "too_large"


def image_url(sha256: str) -> str:
    return IMAGE_PREFIX + sha256


def inspect_image(data: bytes) -> tuple[str, int, int]:
    """Validate that ``data`` is a raster image we accept; returns (content type, width, height)."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise UnsupportedMedia("Not a supported image (PNG, JPEG, GIF or WebP)") from None
    if fmt not in FORMATS:
        raise UnsupportedMedia(f"Image format {fmt} is not supported — use PNG, JPEG, GIF or WebP")
    return FORMATS[fmt], width, height


def store_image(db: Session, project: Project, actor: User | None, data: bytes, filename: str = "image") -> InlineImage:
    limit = get_settings().max_image_mb * 1024 * 1024
    if len(data) > limit:
        raise TooLarge(f"Images may be at most {get_settings().max_image_mb} MB")
    if not data:
        raise ValidationFailed("The image is empty")
    content_type, width, height = inspect_image(data)
    sha, size = storage.store(io.BytesIO(data))
    db.execute(pg_insert(Blob).values(sha256=sha, size=size, content_type=content_type)
               .on_conflict_do_nothing(index_elements=["sha256"]))
    name = (filename or "image").replace("/", "_").replace("\\", "_")[:200]
    if "." not in name:
        name = f"{name}.{EXTENSIONS[content_type]}"
    db.execute(pg_insert(InlineImage).values(
        project_id=project.id, sha256=sha, filename=name, content_type=content_type, size=size, width=width,
        height=height, uploaded_by=actor.id if actor else None,
    ).on_conflict_do_nothing(constraint="uq_images_project_sha256"))
    db.flush()
    return db.execute(select(InlineImage).where(InlineImage.project_id == project.id,
                                                InlineImage.sha256 == sha)).scalar_one()


def register_existing(db: Session, project: Project, sha256: str, actor: User | None) -> bool:
    """Make an image already in the store available to ``project`` (copy/paste between projects)."""
    if db.execute(select(InlineImage.id).where(InlineImage.project_id == project.id,
                                               InlineImage.sha256 == sha256)).scalar():
        return True
    src = db.execute(select(InlineImage).where(InlineImage.sha256 == sha256).limit(1)).scalar_one_or_none()
    if src is None or not storage.exists(sha256):
        return False
    if actor is not None and not actor.is_admin and not can_read(db, actor, sha256):
        return False
    db.execute(pg_insert(InlineImage).values(
        project_id=project.id, sha256=sha256, filename=src.filename, content_type=src.content_type, size=src.size,
        width=src.width, height=src.height, uploaded_by=actor.id if actor else None,
    ).on_conflict_do_nothing(constraint="uq_images_project_sha256"))
    return True


def can_read(db: Session, user: User, sha256: str) -> bool:
    if user.is_admin:
        return db.execute(select(InlineImage.id).where(InlineImage.sha256 == sha256).limit(1)).scalar() is not None
    return db.execute(
        select(InlineImage.id).join(ProjectMember, ProjectMember.project_id == InlineImage.project_id)
        .where(InlineImage.sha256 == sha256, ProjectMember.user_id == user.id).limit(1)
    ).scalar() is not None


def find(db: Session, sha256: str) -> InlineImage | None:
    return db.execute(select(InlineImage).where(InlineImage.sha256 == sha256).limit(1)).scalar_one_or_none()


class ProjectImages:
    """Image resolver for rich text saved into ``project``.

    Keeps references to stored images (registering them for the project if needed), turns pasted ``data:``
    images into stored images and drops everything else (external URLs are never fetched).
    """

    def __init__(self, db: Session, project: Project, actor: User | None, extra: dict[str, bytes] | None = None):
        self.db, self.project, self.actor = db, project, actor
        self.extra = extra or {}  # e.g. files of a .reqifz archive, keyed by their path
        self._ok: dict[str, bool] = {}

    def __call__(self, src: str, attrs: dict[str, Any]) -> str | None:
        src = (src or "").strip()
        m = IMAGE_SRC.match(src)
        if m:
            sha = m.group(1)
            if sha not in self._ok:
                self._ok[sha] = register_existing(self.db, self.project, sha, self.actor)
            return src if self._ok[sha] else None
        d = _DATA_URI.match(src)
        if d:
            try:
                data = base64.b64decode(d.group(2), validate=False)
            except (binascii.Error, ValueError):
                return None
            return self._store(data, attrs.get("alt") or "pasted-image")
        if src in self.extra:
            return self._store(self.extra[src], src.rsplit("/", 1)[-1])
        return None

    def _store(self, data: bytes, name: str) -> str | None:
        try:
            img = store_image(self.db, self.project, self.actor, data, name)
        except DomainError:
            return None
        self._ok[img.sha256] = True
        return image_url(img.sha256)
