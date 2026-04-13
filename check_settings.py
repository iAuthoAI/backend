from app.core.config import settings
import sys

print(f"Python: {sys.executable}")
print(f"APP_NAME: {settings.APP_NAME}")
print(f"DATABASE_URL: {settings.DATABASE_URL[:20]}...")
print(f"DB_SCHEMA: {settings.DB_SCHEMA}")
print(f"SECRET_KEY: {settings.SECRET_KEY[:5]}...")

from sqlalchemy import create_engine, text
try:
    engine = create_engine(settings.DATABASE_URL)
    with engine.connect() as conn:
        res = conn.execute(text("SELECT email FROM \"OneClick\".users WHERE email = 'intake@bcbs.com'")).fetchone()
        print(f"DB Connection Successful. User 'intake@bcbs.com' exists: {res is not None}")
except Exception as e:
    print(f"DB Connection Failed: {e}")
