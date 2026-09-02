from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.backend.api.dependencies import require_customer_service
from app.backend.db import get_db
from app.backend.imports.workbook import MAX_WORKBOOK_BYTES, commit_preview, create_preview
from app.backend.models import ImportBatch
from app.backend.schemas import WorkbookCommitOut, WorkbookPreviewOut

router = APIRouter(
    prefix="/api/v1/imports/workbook",
    tags=["imports"],
    dependencies=[Depends(require_customer_service)],
)


def _preview_response(batch: ImportBatch) -> WorkbookPreviewOut:
    public = batch.summary["public"]
    return WorkbookPreviewOut(
        batch_id=batch.id,
        filename=batch.filename,
        file_sha256=batch.file_sha256,
        status=batch.status,
        can_commit=batch.status == "ready",
        **public,
    )


@router.post("/preview", response_model=WorkbookPreviewOut, status_code=status.HTTP_201_CREATED)
async def preview_workbook(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> WorkbookPreviewOut:
    filename = file.filename or "workbook.xlsx"
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=422, detail="仅支持 .xlsx 工作簿")
    content = await file.read(MAX_WORKBOOK_BYTES + 1)
    if len(content) > MAX_WORKBOOK_BYTES:
        raise HTTPException(status_code=413, detail="工作簿不能超过 20 MB")
    if not content:
        raise HTTPException(status_code=422, detail="工作簿为空")
    return _preview_response(create_preview(db, filename, content))


@router.post("/{batch_id}/commit", response_model=WorkbookCommitOut)
def commit_workbook(batch_id: str, db: Session = Depends(get_db)) -> WorkbookCommitOut:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="导入预览不存在")
    try:
        result = commit_preview(db, batch)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return WorkbookCommitOut(batch_id=batch.id, status="committed", **result)
