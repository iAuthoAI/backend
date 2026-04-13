"""
Database Initializer
====================
Creates the OneClick schema, all tables, and seeds demo users + sample data.

Usage:
  cd backend
  .venv/Scripts/python scripts/init_db.py
"""
import sys
import uuid
from pathlib import Path
from datetime import date, datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.db.session import engine, SessionLocal, Base
import bcrypt

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

# Import ALL models so Base knows about them
import app.models


def create_schema_and_tables():
    print("Creating schema 'OneClick'...")
    with engine.connect() as conn:
        conn.execute(text('CREATE SCHEMA IF NOT EXISTS "OneClick"'))
        conn.commit()
    print("  ✓ Schema ready")

    print("Creating all tables...")
    Base.metadata.create_all(bind=engine)
    print("  ✓ Tables created")


def seed_demo_data():
    from app.models.user import Organization, User
    from app.models.payer import Payer, Plan

    db = SessionLocal()
    try:
        # ── Organizations ──────────────────────────────────────────────────
        print("Seeding organizations...")
        provider_org = db.query(Organization).filter_by(name="Metro Medical Center").first()
        if not provider_org:
            provider_org = Organization(
                name="Metro Medical Center",
                type="provider",
                npi="1234567890",
                address_line1="123 Medical Drive",
                city="Chicago",
                state="IL",
                zip="60601",
                phone="312-555-0100",
            )
            db.add(provider_org)

        payer_org = db.query(Organization).filter_by(name="BlueCross BlueShield").first()
        if not payer_org:
            payer_org = Organization(
                name="BlueCross BlueShield",
                type="payer",
                npi="9876543210",
                address_line1="456 Insurance Blvd",
                city="Chicago",
                state="IL",
                zip="60602",
                phone="312-555-0200",
            )
            db.add(payer_org)

        db.flush()
        print("  ✓ Organizations seeded")

        # ── Users ──────────────────────────────────────────────────────────
        print("Seeding users...")
        demo_users = [
            {
                "email": "dr.chen@metro.com",
                "password": "OneClick@2026!",
                "role": "provider",
                "first_name": "Sarah",
                "last_name": "Chen",
                "title": "Dr.",
                "specialty": "Orthopedic Surgery",
                "npi": "1111111111",
                "organization_id": provider_org.id,
            },
            {
                "email": "intake@bcbs.com",
                "password": "OneClick@2026!",
                "role": "payer_intake",
                "first_name": "Marcus",
                "last_name": "Johnson",
                "organization_id": payer_org.id,
            },
            {
                "email": "clinical@bcbs.com",
                "password": "OneClick@2026!",
                "role": "payer_clinical",
                "first_name": "Emily",
                "last_name": "Rodriguez",
                "title": "Dr.",
                "specialty": "Internal Medicine",
                "organization_id": payer_org.id,
            },
            {
                "email": "decision@bcbs.com",
                "password": "OneClick@2026!",
                "role": "payer_decision",
                "first_name": "Robert",
                "last_name": "Kim",
                "organization_id": payer_org.id,
            },
            {
                "email": "admin@metro.com",
                "password": "OneClick@2026!",
                "role": "admin",
                "first_name": "Admin",
                "last_name": "User",
                "organization_id": provider_org.id,
            },
        ]

        for u in demo_users:
            if not db.query(User).filter_by(email=u["email"]).first():
                user = User(
                    organization_id=u["organization_id"],
                    email=u["email"],
                    password_hash=get_password_hash(u["password"]),
                    role=u["role"],
                    first_name=u["first_name"],
                    last_name=u["last_name"],
                    title=u.get("title"),
                    specialty=u.get("specialty"),
                    npi=u.get("npi"),
                    is_active=True,
                )
                db.add(user)
                print(f"  + {u['email']} ({u['role']})")
            else:
                print(f"  ~ {u['email']} already exists")

        db.flush()
        print("  ✓ Users seeded")

        # ── Payers ─────────────────────────────────────────────────────────
        print("Seeding payers...")
        payers_data = [
            {"code": "BCBS", "name": "BlueCross BlueShield", "type": "commercial"},
            {"code": "AETNA", "name": "Aetna", "type": "commercial"},
            {"code": "CIGNA", "name": "Cigna", "type": "commercial"},
            {"code": "UHC", "name": "UnitedHealthcare", "type": "commercial"},
            {"code": "HUMANA", "name": "Humana", "type": "commercial"},
            {"code": "MEDICARE", "name": "Medicare", "type": "medicare"},
            {"code": "MEDICAID", "name": "Medicaid", "type": "medicaid"},
        ]
        for p in payers_data:
            if not db.query(Payer).filter_by(code=p["code"]).first():
                payer = Payer(
                    code=p["code"],
                    name=p["name"],
                    type=p["type"],
                    is_active=True,
                    epa_supported=True,
                )
                db.add(payer)
        print("  ✓ Payers seeded")

        db.commit()
        print("\n✓ All demo data seeded successfully!")

    except Exception as e:
        db.rollback()
        print(f"\n✗ Error: {e}")
        raise
    finally:
        db.close()


def print_summary():
    print("\n" + "=" * 55)
    print("  Database initialized!")
    print("=" * 55)
    print("\n  Demo credentials (all use password: OneClick@2026!)")
    print("  ─────────────────────────────────────────────────")
    print("  Provider:  dr.chen@metro.com")
    print("  Intake:    intake@bcbs.com")
    print("  Clinical:  clinical@bcbs.com")
    print("  Decision:  decision@bcbs.com")
    print("  Admin:     admin@metro.com")
    print("\n  API Docs:  http://localhost:9001/api/docs")
    print("=" * 55)


if __name__ == "__main__":
    print("=" * 55)
    print("  OneClick — Database Initializer")
    print("=" * 55 + "\n")
    create_schema_and_tables()
    print()
    seed_demo_data()
    print_summary()
