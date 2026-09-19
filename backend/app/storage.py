"""Private object storage for client photos (F9).

The bucket is private end to end: the browser never touches it directly with
credentials, and no object is ever public. Uploads and views both go through
short-lived presigned URLs the API signs on demand. Locally the same code talks
to MinIO (S3 API, path-style addressing, endpoint set); in AWS it talks to S3
(virtual-hosted style, credentials from the Lambda role). Presigning is a local
signing operation — it does not call S3 — so building an upload/view URL needs
no network round trip.
"""

import uuid
from functools import lru_cache

import boto3
from botocore.config import Config

from app.config import get_settings

# How long a presigned upload/view URL stays valid. Short: a link that leaks is
# useless within the quarter hour, and the panel re-signs on every page load.
PRESIGN_TTL_SECONDS = 900

# Extension per stored content type — the object key keeps a sane suffix so the
# bucket is browsable and downloads land with the right name.
_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic"}
ALLOWED_CONTENT_TYPES = frozenset(_EXT)


@lru_cache
def _client():
    s = get_settings()
    # Path-style addressing is required for MinIO (no per-bucket DNS); harmless on
    # real S3. SigV4 for presigned URLs that MinIO and S3 both accept.
    cfg = Config(signature_version="s3v4", s3={"addressing_style": "path"})
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,  # set locally (MinIO), None in AWS
        region_name=s.aws_region,
        config=cfg,
    )


def new_key(client_id: int, content_type: str) -> str:
    """Opaque object key for a new photo, namespaced per client so RODO erasure
    can sweep a whole prefix and the bucket stays legible."""
    ext = _EXT.get(content_type, "bin")
    return f"clients/{client_id}/photos/{uuid.uuid4().hex}.{ext}"


def presign_put(key: str, content_type: str) -> str:
    """Presigned PUT URL for a browser upload. The client MUST send the same
    Content-Type header, or the signature check fails."""
    return _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": get_settings().s3_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=PRESIGN_TTL_SECONDS,
    )


def presign_get(key: str) -> str:
    """Presigned GET URL to view one photo."""
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": get_settings().s3_bucket, "Key": key},
        ExpiresIn=PRESIGN_TTL_SECONDS,
    )


def delete_objects(keys: list[str]) -> None:
    """Delete objects from the bucket (single-photo delete + RODO erasure). No-op
    on an empty list. S3's delete API takes up to 1000 keys per call."""
    if not keys:
        return
    bucket = get_settings().s3_bucket
    client = _client()
    for i in range(0, len(keys), 1000):
        chunk = keys[i : i + 1000]
        client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in chunk]})
