"""Application configuration — from environment variables only.

The same container image runs locally (docker compose) and in AWS (App Runner);
the only differences are env vars. Secrets and environment-dependent values have
NO defaults — a missing variable is a startup error, not a silent fallback to a
"dev" password or a dev origin.

AWS credentials (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) are deliberately not
declared here: boto3 resolves them itself through the standard credential chain
(env vars for MinIO locally; the container's IAM role in AWS — where these
variables do not exist at all).
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_env: Literal["local", "dev", "lab", "prod"] = "local"

    # Secret (contains the password) — required.
    database_url: SecretStr

    # S3: MinIO locally (endpoint set), real S3 in AWS (endpoint empty).
    s3_bucket: str
    s3_endpoint_url: str | None = None
    aws_region: str = "eu-central-1"

    # SMTP: Mailpit locally, SES in AWS.
    smtp_host: str
    smtp_port: int = 587

    # CORS: the frontend is static and calls the API from the browser (different origin).
    # Comma-separated list of origins; "http://localhost:4321" locally,
    # e.g. "https://charmskin.pl" in AWS. No default: a forgotten variable in prod
    # must stop startup, not silently trust the dev origin.
    cors_origins: str

    # Auth: Cognito OIDC issuer + expected client id. The app validates Bearer
    # JWTs itself (signature via the issuer's JWKS, exp, token_use, client_id) —
    # independently of the API Gateway authorizer. Same values locally: the
    # boundary rule says never emulate Cognito, so compose talks to the real
    # dev user pool. No defaults — missing auth config must stop startup.
    auth_issuer: str
    auth_audience: str

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """One instance per process; env validation happens on the first call."""
    return Settings()  # type: ignore[call-arg]  # required fields come from env
