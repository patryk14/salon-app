"""Private object storage for client photos (F9).

The bucket is private end to end and no object is ever public. READS never
leave the API: a photo is streamed only to an authenticated, authorized caller
(see the /content endpoints) — there is deliberately NO presigned GET, because a
presigned URL is a bearer link: anyone holding it can open the photo without
logging in until it expires, and URLs leak (history, chats, logs). Only the
UPLOAD uses a presigned URL: it is write-only for one fresh key and short-lived.
Locally the same code talks to MinIO (path-style, endpoint set); in AWS to S3
(virtual-hosted style, credentials from the Lambda role).
"""

import uuid
from functools import lru_cache

import boto3
from botocore.config import Config

from app.config import get_settings

# How long a presigned UPLOAD URL stays valid — just long enough for the browser
# to PUT the file it has already prepared.
PRESIGN_TTL_SECONDS = 300

# A photo served through the API must fit Lambda's 6 MB response cap (base64
# inflates by 4/3). The panel re-encodes uploads to ~0.5 MB, so this is a guard.
MAX_SERVED_BYTES = 4_000_000


class ObjectTooLarge(Exception):
    """The stored object exceeds what the API can stream back."""


# Extension per stored content type — the object key keeps a sane suffix so the
# bucket is browsable and downloads land with the right name.
_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic"}
ALLOWED_CONTENT_TYPES = frozenset(_EXT)


def _make_client(endpoint_url: str | None):
    # Path-style addressing is required for MinIO (no per-bucket DNS); real S3
    # gets the standard virtual-hosted style. SigV4 works for both.
    style = "path" if endpoint_url else "virtual"
    cfg = Config(signature_version="s3v4", s3={"addressing_style": style})
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,  # set locally (MinIO), None in AWS
        region_name=get_settings().aws_region,
        config=cfg,
    )


@lru_cache
def _client():
    """Client for server-side calls (deletes) — the endpoint the API can reach."""
    return _make_client(get_settings().s3_endpoint_url)


@lru_cache
def _presign_client():
    """Client used only to SIGN urls. SigV4 signs the Host header, so the URL must
    be signed for the host the browser will actually call — locally that differs
    from the API's own view of MinIO (see s3_public_endpoint_url)."""
    s = get_settings()
    return _make_client(s.s3_public_endpoint_url or s.s3_endpoint_url)


def new_key(client_id: int, content_type: str) -> str:
    """Opaque object key for a new photo, namespaced per client so RODO erasure
    can sweep a whole prefix and the bucket stays legible."""
    ext = _EXT.get(content_type, "bin")
    return f"clients/{client_id}/photos/{uuid.uuid4().hex}.{ext}"


def presign_put(key: str, content_type: str) -> str:
    """Presigned PUT URL for a browser upload. The client MUST send the same
    Content-Type header, or the signature check fails."""
    return _presign_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": get_settings().s3_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=PRESIGN_TTL_SECONDS,
    )


def read_object(key: str) -> bytes:
    """Fetch one photo's bytes server-side, for an already-authorized caller."""
    obj = _client().get_object(Bucket=get_settings().s3_bucket, Key=key)
    if obj["ContentLength"] > MAX_SERVED_BYTES:
        raise ObjectTooLarge(key)
    return obj["Body"].read()


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
