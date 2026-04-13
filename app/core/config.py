import os
import boto3
from botocore.exceptions import ClientError
from pydantic_settings import BaseSettings
from typing import List


def _load_parameter_store(prefix: str = "/oneclick", region: str = "us-east-2") -> dict:
    """Fetch all /oneclick/ parameters from AWS Parameter Store."""
    try:
        client = boto3.client("ssm", region_name=region)
        params = {}
        paginator = client.get_paginator("get_parameters_by_path")
        for page in paginator.paginate(Path=prefix, Recursive=True, WithDecryption=True):
            for p in page["Parameters"]:
                # /oneclick/db/url → db/url → store as-is for lookup
                params[p["Name"]] = p["Value"]
        return params
    except Exception:
        return {}


# Load once at startup
_ps = _load_parameter_store()


def _get(key: str, default: str = "") -> str:
    env_key = key.replace("/oneclick/", "").replace("/", "_").upper()
    return os.getenv(env_key, _ps.get(key, default))


class Settings(BaseSettings):
    APP_NAME: str                       = _get("/oneclick/app/name", "OneClick")
    APP_VERSION: str                    = _get("/oneclick/app/version", "1.0.0")
    APP_ENV: str                        = _get("/oneclick/app/env", "development")
    DEBUG: bool                         = APP_ENV == "development"

    # Database
    DATABASE_URL: str                   = _get("/oneclick/db/url", os.getenv("DATABASE_URL", "sqlite:///./test.db"))
    DB_SCHEMA: str                      = _get("/oneclick/db/schema", os.getenv("DB_SCHEMA", "OneClick"))

    # Security
    SECRET_KEY: str                     = _get("/oneclick/jwt/secret", os.getenv("SECRET_KEY", "supersecret"))
    ALGORITHM: str                      = _get("/oneclick/jwt/algorithm", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int    = int(_get("/oneclick/jwt/access_expire_minutes", "60"))
    REFRESH_TOKEN_EXPIRE_DAYS: int      = int(_get("/oneclick/jwt/refresh_expire_days", "7"))

    # AWS
    AWS_REGION: str                     = "us-east-2"
    AWS_PARAMETER_STORE_PREFIX: str     = "/oneclick"

    # Epic FHIR
    EPIC_CLIENT_ID: str                 = _get("/oneclick/fhir/epic_client_id", "")
    EPIC_FHIR_BASE_URL: str             = _get("/oneclick/fhir/epic_base_url", "")
    SMART_FHIR_BASE_URL: str            = _get("/oneclick/fhir/smart_base_url", "https://r4.smarthealthit.org")
    SMART_LAUNCH_URL: str               = "https://launch.smarthealthit.org"

    # AI
    ANTHROPIC_API_KEY: str              = _get("/oneclick/ai/anthropic_api_key", "")
    AI_MODEL: str                       = _get("/oneclick/ai/model", "claude-sonnet-4-6")

    # CORS
    ALLOWED_ORIGINS: str                = _get("/oneclick/cors/allowed_origins", "http://localhost:3000")

    # Frontend
    FRONTEND_URL: str                   = _get("/oneclick/frontend/url", "http://localhost:3000")

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    class Config:
        # Load from .env if it exists
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Environment variables take precedence over Param Store if both are set
        extra = "ignore"


settings = Settings()
