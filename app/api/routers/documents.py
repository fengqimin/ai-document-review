"""Local PDF document store.

Replaces direct browser-to-Azure-Blob-Storage access. All uploads, listing and
downloads go through this API and are protected by the same JWT as the review
endpoints. Files live under DATA_DIR/documents; doc_id == file name.
"""

import asyncio
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from common.logger import get_logger
from config.config import settings
from database.issues_repository import IssuesRepository
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from security.auth import validate_authenticated

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
logging = get_logger(__name__)

# Whitelist: word chars, dash, dot, space, parentheses; must end with .pdf.
# Rejects "..", path separators and control characters (path traversal).
_NAME_PATTERN = re.compile(r"^[\w\-. ()]+\.pdf$", re.IGNORECASE)


class DocumentInfo(BaseModel):
    name: str
    size: int
    last_modified: str


def _validate_name(name: str) -> str:
    if not name or name != Path(name).name or not _NAME_PATTERN.fullmatch(name):
        raise HTTPException(status_code=400, detail="Invalid PDF file name")
    return name


def _doc_path(name: str) -> Path:
    return settings.documents_dir / name


def _list_documents_sync() -> list[DocumentInfo]:
    docs: list[DocumentInfo] = []
    if settings.documents_dir.is_dir():
        for path in settings.documents_dir.iterdir():
            if path.is_file() and _NAME_PATTERN.fullmatch(path.name):
                stat = path.stat()
                docs.append(
                    DocumentInfo(
                        name=path.name,
                        size=stat.st_size,
                        last_modified=datetime.fromtimestamp(
                            stat.st_mtime, tz=timezone.utc
                        ).isoformat(),
                    )
                )
    return sorted(docs, key=lambda d: d.name)


@router.get(
    "",
    summary="List uploaded PDF documents",
    response_model=list[DocumentInfo],
)
async def list_documents(user=Depends(validate_authenticated)) -> list[DocumentInfo]:
    return await asyncio.to_thread(_list_documents_sync)


@router.post(
    "",
    summary="Upload a PDF document (same name overwrites and clears old issues)",
    response_model=DocumentInfo,
    status_code=201,
)
async def upload_document(
    file: UploadFile = File(...), user=Depends(validate_authenticated)
) -> DocumentInfo:
    name = _validate_name(file.filename or "")
    content = await file.read()

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.max_upload_mb} MB upload limit",
        )
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Not a valid PDF file")

    path = _doc_path(name)
    overwritten = path.exists()
    await asyncio.to_thread(path.write_bytes, content)

    if overwritten:
        # Blob overwrite semantics: stale issues must not survive a re-upload.
        await IssuesRepository().delete_issues_by_doc(name)
        logging.info(f"Document '{name}' overwritten; previous issues cleared.")

    stat = path.stat()
    return DocumentInfo(
        name=name,
        size=stat.st_size,
        last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    )


@router.get(
    "/{name}/file",
    summary="Download a PDF document",
    response_class=FileResponse,
)
async def download_document(name: str, user=Depends(validate_authenticated)) -> FileResponse:
    name = _validate_name(name)
    path = _doc_path(name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(path, media_type="application/pdf", filename=name)


@router.delete(
    "/{name}",
    summary="Delete a PDF document and its issues",
    status_code=204,
)
async def delete_document(name: str, user=Depends(validate_authenticated)):
    name = _validate_name(name)
    path = _doc_path(name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    await asyncio.to_thread(os.remove, path)
    await IssuesRepository().delete_issues_by_doc(name)
    logging.info(f"Document '{name}' deleted along with its issues.")
    return None
