from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from almlight.core.db import get_db
from almlight.core.deps import current_user
from almlight.core.errors import NotFound
from almlight.modules.identity.models import User
from almlight.modules.images import service
from almlight.modules.items import storage
from almlight.modules.projects.access import get_project

router = APIRouter(tags=["images"])


@router.post("/projects/{project_key}/images", status_code=201,
             summary="Upload an image for rich text (PNG, JPEG, GIF, WebP)")
def upload_image(project_key: str, file: UploadFile = File(...), user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict:
    project = get_project(db, project_key, user, "contributor")
    limit = service.get_settings().max_image_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    img = service.store_image(db, project, user, data, file.filename or "image")
    db.commit()
    return {"sha256": img.sha256, "url": service.image_url(img.sha256), "width": img.width, "height": img.height,
            "content_type": img.content_type, "size": img.size}


@router.get("/images/{sha256}", summary="Image content (immutable; cached by the browser)")
def get_image(sha256: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> FileResponse:
    if len(sha256) != 64 or not all(c in "0123456789abcdef" for c in sha256) or not service.can_read(db, user,
                                                                                                    sha256):
        raise NotFound("Image not found")
    img = service.find(db, sha256)
    path = storage.blob_path(sha256)
    if img is None or not path.exists():
        raise NotFound("Image not found")
    return FileResponse(path, media_type=img.content_type, headers={
        "Cache-Control": "private, max-age=31536000, immutable",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    })
