from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile

TYPE_PREFIXES = {
    "image": "image/",
    "audio": "audio/",
    "video": "video/",
}
SAFE_EXTENSION = re.compile(r"^\.[A-Za-z0-9]{1,10}$")


@dataclass(frozen=True, slots=True)
class StoredMedia:
    path: Path
    url: str
    original_filename: str
    mime_type: str
    size_bytes: int


async def store_upload(
    upload: UploadFile,
    declared_type: str,
    media_dir: Path,
    max_bytes: int,
) -> StoredMedia:
    mime_type = (upload.content_type or "application/octet-stream").lower()
    expected_prefix = TYPE_PREFIXES.get(declared_type)
    if expected_prefix and not mime_type.startswith(expected_prefix):
        raise HTTPException(
            status_code=415,
            detail=f"上传文件 MIME 类型 {mime_type} 与消息类型 {declared_type} 不匹配",
        )

    original_filename = Path(upload.filename or "unnamed").name[:300]
    extension = Path(original_filename).suffix.lower()
    if not SAFE_EXTENSION.fullmatch(extension):
        extension = ""
    stored_name = f"{uuid.uuid4().hex}{extension}"
    media_dir.mkdir(parents=True, exist_ok=True)
    destination = (media_dir / stored_name).resolve()
    if media_dir.resolve() not in destination.parents:
        raise HTTPException(status_code=400, detail="非法文件路径")

    total = 0
    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过大小限制 {max_bytes} bytes",
                    )
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    if total == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="不能上传空文件")

    return StoredMedia(
        path=destination,
        url=f"/media/{stored_name}",
        original_filename=original_filename,
        mime_type=mime_type,
        size_bytes=total,
    )
