"""Client progress photos (F9) — staff/admin facing.

Two-step upload keeps photo bytes off the API entirely: the panel asks for a
presigned PUT URL, uploads straight to the private bucket, then registers the
object here. Every photo carries an accountable uploader (Cognito sub) and is
gated by the client's explicit photo consent — no consent, no upload. Photos
are read back ONLY through the authenticated /content endpoint — never via a
shareable URL (see app.storage).
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.auth import UserDep, require_role
from app.deps import get_db
from app.models import Client, Photo, Visit
from app.schemas import (
    PhotoCreate,
    PhotoOut,
    PhotoUploadRequest,
    PhotoUploadResponse,
)

router = APIRouter(tags=["photos"], dependencies=[require_role("staff")])

DbDep = Annotated[Session, Depends(get_db)]


def _client_or_404(db: Session, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="client not found")
    return client


def _require_consent(client: Client) -> None:
    if not client.photo_consent:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="client has not consented to progress photos — record consent first",
        )


def photo_response(photo: Photo) -> Response:
    """The photo's bytes for a caller the endpoint has ALREADY authorized.
    no-store: a face photo must not linger in a shared salon computer's cache."""
    try:
        data = storage.read_object(photo.s3_key)
    except storage.ObjectTooLarge:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="photo too large to serve"
        ) from None
    return Response(
        content=data,
        media_type=photo.content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/clients/{client_id}/photos/upload-url")
def create_upload_url(
    client_id: int, payload: PhotoUploadRequest, db: DbDep
) -> PhotoUploadResponse:
    """Step 1: a presigned PUT URL for a browser upload straight to the bucket."""
    _require_consent(_client_or_404(db, client_id))
    key = storage.new_key(client_id, payload.content_type)
    return PhotoUploadResponse(
        s3_key=key,
        upload_url=storage.presign_put(key, payload.content_type),
        content_type=payload.content_type,
    )


@router.post("/clients/{client_id}/photos", status_code=status.HTTP_201_CREATED)
def register_photo(client_id: int, payload: PhotoCreate, user: UserDep, db: DbDep) -> PhotoOut:
    """Step 2: register the object just uploaded to the bucket."""
    _require_consent(_client_or_404(db, client_id))
    if payload.visit_id is not None:
        visit = db.get(Visit, payload.visit_id)
        if visit is None or visit.client_id != client_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="visit does not belong to this client"
            )
    photo = Photo(
        client_id=client_id,
        visit_id=payload.visit_id,
        kind=payload.kind,
        s3_key=payload.s3_key,
        content_type=payload.content_type,
        note=payload.note,
        taken_on=payload.taken_on or date.today(),
        uploaded_by=user.sub,
    )
    db.add(photo)
    db.flush()
    return PhotoOut.model_validate(photo)


@router.get("/clients/{client_id}/photos")
def list_photos(client_id: int, db: DbDep) -> list[PhotoOut]:
    """The client's gallery (metadata), newest first. Bytes: /photos/{id}/content."""
    _client_or_404(db, client_id)
    photos = db.scalars(
        select(Photo)
        .where(Photo.client_id == client_id)
        .order_by(Photo.taken_on.desc(), Photo.created_at.desc())
    ).all()
    return [PhotoOut.model_validate(p) for p in photos]


@router.get("/photos/{photo_id}/content")
def photo_content(photo_id: int, db: DbDep) -> Response:
    """The image itself — staff/admin only (router gate), token in the header."""
    photo = db.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="photo not found")
    return photo_response(photo)


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo(photo_id: int, db: DbDep) -> None:
    """Remove one photo — the S3 object first (retryable if it fails), then the
    row, so a failure never orphans bytes in the bucket."""
    photo = db.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="photo not found")
    storage.delete_objects([photo.s3_key])
    db.delete(photo)
