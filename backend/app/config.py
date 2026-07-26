"""Application settings loaded from environment variables."""
import os
import warnings

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env" if os.path.isfile(".env") else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    APP_NAME: str = "Enterprise Private RAG"
    DEBUG: bool = False

    # PostgreSQL
    POSTGRES_USER: str = "rag"
    POSTGRES_PASSWORD: str = "rag"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "rag"
    DATABASE_URL: str | None = None

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_URL: str | None = None

    # RabbitMQ / AMQP
    RABBITMQ_HOST: str = "localhost"
    RABBITMQ_PORT: int = 5672
    RABBITMQ_USER: str = "guest"
    RABBITMQ_PASSWORD: str = "guest"
    RABBITMQ_URL: str | None = None

    # Vector store backend selection
    VECTOR_STORE_BACKEND: str = "milvus"  # "milvus" | "pgvector"
    PGVECTOR_COLLECTION_PREFIX: str = "rag"

    # Milvus
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_COLLECTION_PREFIX: str = "rag"

    # File storage backend selection
    FILE_STORAGE_BACKEND: str = "s3"  # "s3" | "local"
    LOCAL_STORAGE_PATH: str = "/data/rag-documents"

    # MinIO (S3-compatible) — credentials MUST be provided via environment.
    # No hard-coded defaults remain in code; see .env.example for placeholders.
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET: str = "rag-documents"
    MINIO_SECURE: bool = False

    # Celery broker selection
    CELERY_BROKER_TYPE: str = "rabbitmq"  # "rabbitmq" | "redis"
    CELERY_TASK_ALWAYS_EAGER: bool = False

    # JWT — accepts JWT_SECRET_KEY or SECRET_KEY as a fallback.
    # Generate a strong random value for production (e.g. `openssl rand -hex 32`).
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # CORS
    CORS_ORIGINS: str | None = None
    CORS_ALLOW_CREDENTIALS: bool = True

    # Admin usernames (comma-separated) for elevated management endpoints.
    ADMIN_USERNAMES: str = "admin"

    @model_validator(mode="before")
    @classmethod
    def _load_secret_key_aliases(cls, values):
        """Allow SECRET_KEY to act as a fallback for JWT_SECRET_KEY."""
        jwt = values.get("JWT_SECRET_KEY")
        secret = values.get("SECRET_KEY") or os.environ.get("SECRET_KEY")
        if (not jwt or jwt == "change-me-in-production") and secret:
            values["JWT_SECRET_KEY"] = secret
        return values

    @model_validator(mode="after")
    def _warn_default_jwt_secret(self):
        if self.JWT_SECRET_KEY in (None, "", "change-me-in-production"):
            warnings.warn(
                "JWT_SECRET_KEY is not set or is using the default value. "
                "Set JWT_SECRET_KEY (or SECRET_KEY) in the environment before deploying.",
                RuntimeWarning,
                stacklevel=2,
            )
        return self

    # Model service endpoints
    EMBEDDING_SERVICE_URL: str = "http://localhost:8001/embed"
    EMBEDDING_API_URL: str | None = None
    EMBEDDING_MODEL: str = "text-embedding-3-large"
    EMBEDDING_API_KEY: str | None = None
    EMBEDDING_DIMENSION: int = 1024

    # Phase 2: query cache toggle — off by default, never breaks existing behavior.
    ENABLE_QUERY_CACHE: bool = False

    RERANK_SERVICE_URL: str = "http://localhost:8002/rerank"
    RERANK_API_URL: str | None = None
    RERANK_MODEL: str = "bge-reranker-large"
    RERANK_API_KEY: str | None = None

    LLM_API_URL: str | None = None
    LLM_MODEL: str = "minimax-m3"
    LLM_API_KEY: str | None = None
    MINIMAX_API_KEY: str | None = None
    MINIMAX_BASE_URL: str = "https://api.minimax.chat"

    @property
    def async_database_url(self) -> str:
        """Return asyncpg-compatible database URL."""
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def sync_database_url(self) -> str:
        """Return synchronous psycopg2-compatible database URL (used by pgvector)."""
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("postgresql+asyncpg://"):
                url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
            return url
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def redis_url(self) -> str:
        return self.REDIS_URL or f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def rabbitmq_url(self) -> str:
        return (
            self.RABBITMQ_URL
            or f"amqp://{self.RABBITMQ_USER}:{self.RABBITMQ_PASSWORD}"
            f"@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}/"
        )

    @property
    def celery_broker_url(self) -> str:
        """Return the Celery broker URL based on CELERY_BROKER_TYPE."""
        if self.CELERY_BROKER_TYPE.lower() == "redis":
            return self.redis_url
        return self.rabbitmq_url

    @property
    def celery_result_backend(self) -> str:
        """Redis is used as the result backend in both modes."""
        return self.redis_url


settings = Settings()
