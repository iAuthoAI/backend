"""
Push OneClick config to AWS Parameter Store
============================================
Creates all /oneclick/ parameters from the current .env values.
Safe: only touches /oneclick/ prefix — never modifies other parameters.

Usage:
  cd backend
  .venv/Scripts/python scripts/push_to_parameter_store.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import boto3
from dotenv import dotenv_values

REGION = "us-east-2"
PREFIX = "/oneclick"

# Load current .env
env = dotenv_values(Path(__file__).parent.parent / ".env")

# Define parameters: (path, value, type, description)
# String     = non-sensitive config
# SecureString = sensitive / secret values
PARAMETERS = [
    # App
    (f"{PREFIX}/app/name",          env.get("APP_NAME", "OneClick"),        "String",       "Application name"),
    (f"{PREFIX}/app/version",       env.get("APP_VERSION", "1.0.0"),        "String",       "Application version"),
    (f"{PREFIX}/app/env",           env.get("APP_ENV", "development"),      "String",       "Environment (development/production)"),

    # Database
    (f"{PREFIX}/db/url",            env.get("DATABASE_URL", ""),            "SecureString", "PostgreSQL connection URL"),
    (f"{PREFIX}/db/schema",         env.get("DB_SCHEMA", "OneClick"),       "String",       "Database schema name"),

    # Security / JWT
    (f"{PREFIX}/jwt/secret",        env.get("SECRET_KEY", ""),              "SecureString", "JWT signing secret key"),
    (f"{PREFIX}/jwt/algorithm",     env.get("ALGORITHM", "HS256"),          "String",       "JWT algorithm"),
    (f"{PREFIX}/jwt/access_expire_minutes",  str(env.get("ACCESS_TOKEN_EXPIRE_MINUTES", "60")),  "String", "Access token expiry in minutes"),
    (f"{PREFIX}/jwt/refresh_expire_days",    str(env.get("REFRESH_TOKEN_EXPIRE_DAYS", "7")),     "String", "Refresh token expiry in days"),

    # AI
    (f"{PREFIX}/ai/anthropic_api_key", env.get("ANTHROPIC_API_KEY", ""),   "SecureString", "Anthropic Claude API key"),
    (f"{PREFIX}/ai/model",          env.get("AI_MODEL", "claude-sonnet-4-6"), "String",    "Claude model ID"),

    # FHIR
    (f"{PREFIX}/fhir/smart_base_url", env.get("SMART_FHIR_BASE_URL", "https://r4.smarthealthit.org"), "String", "SMART Health IT FHIR base URL"),
    (f"{PREFIX}/fhir/epic_client_id", env.get("EPIC_CLIENT_ID", ""),       "SecureString", "Epic FHIR client ID"),
    (f"{PREFIX}/fhir/epic_base_url",  env.get("EPIC_FHIR_BASE_URL", ""),   "String",       "Epic FHIR base URL"),

    # CORS / Frontend
    (f"{PREFIX}/cors/allowed_origins", env.get("ALLOWED_ORIGINS", "http://localhost:3000"), "String", "Comma-separated allowed CORS origins"),
    (f"{PREFIX}/frontend/url",      env.get("FRONTEND_URL", "http://localhost:3000"), "String", "Frontend base URL"),
]


def push_parameters():
    client = boto3.client("ssm", region_name=REGION)
    created, updated, skipped = 0, 0, 0

    for name, value, param_type, description in PARAMETERS:
        if not value:
            print(f"  SKIP  {name}  (empty value)")
            skipped += 1
            continue

        try:
            # Check if exists
            existing = None
            try:
                existing = client.get_parameter(Name=name, WithDecryption=False)
            except client.exceptions.ParameterNotFound:
                pass

            client.put_parameter(
                Name=name,
                Value=value,
                Type=param_type,
                Description=description,
                Overwrite=True,
                Tier="Standard",
            )

            if existing:
                print(f"  UPDATE  {name}  [{param_type}]")
                updated += 1
            else:
                print(f"  CREATE  {name}  [{param_type}]")
                created += 1

        except Exception as e:
            print(f"  ERROR   {name}: {e}")

    print(f"\n  Created: {created}  Updated: {updated}  Skipped: {skipped}")


if __name__ == "__main__":
    print("=" * 60)
    print("  OneClick — Push config to AWS Parameter Store")
    print(f"  Region: {REGION}  Prefix: {PREFIX}/")
    print("=" * 60 + "\n")
    push_parameters()
    print("\nDone.")
