"""Settings read from environment variables (or a local .env file)."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # AWS
    aws_region: str = "ap-south-1"
    aws_endpoint_url: str | None = None  # LocalStack in dev; unset on AWS
    bucket: str = "injectshield-prompts"
    queue_url: str = ""

    # Database: either a full DATABASE_URL, or the parts (ECS injects DB_PASSWORD
    # from Secrets Manager, so the password never sits in a task definition).
    database_url: str | None = None
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "injectshield"
    db_user: str = "injectshield"
    db_password: str = ""

    # Auth
    auth_disabled: bool = False
    dev_user_id: str = "local-dev-user"
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""
    cors_origins: str = "*"  # comma-separated

    # Scoring
    threshold_suspicious: float = 0.4
    threshold_malicious: float = 0.7
    classifier_enabled: bool = False
    classifier_model: str = "protectai/deberta-v3-base-prompt-injection-v2"

    # Worker
    worker_wait_seconds: int = 20
    worker_max_receives: int = 3  # must match the queue's maxReceiveCount
    worker_retry_delay_seconds: int = 10

    @property
    def dsn(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{quote(self.db_user)}:{quote(self.db_password)}@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def cognito_issuer(self) -> str:
        return f"https://cognito-idp.{self.aws_region}.amazonaws.com/{self.cognito_user_pool_id}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
