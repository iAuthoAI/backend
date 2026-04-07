"""
CMS Public Code Seeder
======================
Downloads and seeds ICD-10-CM, HCPCS, and CPT codes into the OneClick database.

Sources (all free/public):
  ICD-10-CM : CDC/CMS annual release (tabular text file)
  HCPCS     : CMS annual Alpha-Numeric HCPCS file (Excel)
  CPT (RVU) : CMS Physician Fee Schedule relative value file (tab-delimited)

Usage:
  cd backend
  .venv/Scripts/python scripts/seed_codes.py
  .venv/Scripts/python scripts/seed_codes.py --only icd10
  .venv/Scripts/python scripts/seed_codes.py --only hcpcs
  .venv/Scripts/python scripts/seed_codes.py --only cpt
"""
import re
import sys
import io
import os
import zipfile
import argparse
from pathlib import Path

# Make sure the app package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from sqlalchemy.orm import Session
from app.db.session import SessionLocal, engine, Base
from app.models.codes import CptCode, HcpcsCode, Icd10Code

# ── Download URLs (CMS / CDC public) ─────────────────────────────────────────

ICD10_URLS = [
    # FY2025 (try first)
    "https://www.cms.gov/files/zip/2025-code-descriptions-tabular-order.zip",
    # FY2024 fallback
    "https://www.cms.gov/files/zip/2024-code-descriptions-tabular-order.zip",
]

HCPCS_URLS = [
    "https://www.cms.gov/files/zip/april-2025-alpha-numeric-hcpcs-file.zip",
    "https://www.cms.gov/files/zip/january-2025-alpha-numeric-hcpcs-file.zip",
    "https://www.cms.gov/files/zip/october-2024-alpha-numeric-hcpcs-file.zip",
    "https://www.cms.gov/files/zip/july-2024-alpha-numeric-hcpcs-file.zip",
]

CPT_RVU_URLS = [
    # CMS PFS Relative Value file (lists all CPT codes with RVU)
    "https://www.cms.gov/files/zip/rvu25a-updated-01/10/2025.zip",
    "https://www.cms.gov/files/zip/rvu24a-updated-04/01/2024.zip",
]

BATCH_SIZE = 500


# ── Helpers ───────────────────────────────────────────────────────────────────

def download_zip(urls: list[str]) -> zipfile.ZipFile:
    for url in urls:
        try:
            print(f"  Downloading: {url}")
            resp = httpx.get(url, follow_redirects=True, timeout=120)
            resp.raise_for_status()
            return zipfile.ZipFile(io.BytesIO(resp.content))
        except Exception as e:
            print(f"  Failed ({e}), trying next URL...")
    raise RuntimeError(f"All download URLs failed: {urls}")


def find_file_in_zip(zf: zipfile.ZipFile, extensions: list[str],
                     name_keywords: list[str] = None) -> str:
    """Find the best matching file in a ZIP by extension and optional name keywords."""
    names = zf.namelist()
    for ext in extensions:
        candidates = [n for n in names if n.lower().endswith(ext.lower())]
        if name_keywords:
            scored = []
            for c in candidates:
                score = sum(1 for kw in name_keywords if kw.lower() in c.lower())
                scored.append((score, c))
            scored.sort(reverse=True)
            if scored and scored[0][0] > 0:
                return scored[0][1]
        if candidates:
            return candidates[0]
    raise FileNotFoundError(f"No file with extensions {extensions} found in ZIP. Contents: {names}")


def batch_upsert(db: Session, model, records: list[dict], unique_field: str):
    """Bulk upsert using PostgreSQL INSERT ON CONFLICT DO UPDATE."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    if not records:
        return 0

    table = model.__table__
    total_new = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        stmt = pg_insert(table).values(batch)
        # On conflict on the unique code field, update description fields
        update_cols = {c.name: stmt.excluded[c.name]
                       for c in table.columns
                       if c.name not in ("id", unique_field)}
        stmt = stmt.on_conflict_do_update(index_elements=[unique_field], set_=update_cols)
        result = db.execute(stmt)
        total_new += result.rowcount
        db.commit()
    return total_new


# ── ICD-10-CM ────────────────────────────────────────────────────────────────

_ICD10_RE = re.compile(r'^[A-Z][0-9A-Z]{2,6}$')


def seed_icd10(db: Session):
    print("\n[ICD-10-CM] Downloading from CMS...")
    zf = download_zip(ICD10_URLS)

    # Prefer the order file (not addenda) — has seq_num, code, valid_flag, short_desc, long_desc
    names = zf.namelist()
    txt_files = [n for n in names if n.lower().endswith(".txt") and "addenda" not in n.lower()]
    order_files = [n for n in txt_files if "order" in n.lower()]
    filename = (order_files or txt_files)[0] if (order_files or txt_files) else None
    if not filename:
        raise FileNotFoundError(f"No suitable .txt file found in ZIP. Contents: {names}")

    print(f"  Parsing: {filename}")
    content = zf.read(filename).decode("utf-8", errors="ignore")

    records = []
    skipped = 0
    for line in content.splitlines():
        line = line.rstrip()
        if len(line) < 17:
            skipped += 1
            continue

        # Fixed-width format: cols 0-4 seq, col 6-12 code, col 14 valid_flag, col 16-76 short_desc, 77+ long_desc
        code = line[6:13].strip()
        valid_flag = line[14:15].strip()
        short_desc = line[16:77].strip()
        long_desc = line[77:].strip() if len(line) > 77 else ""
        description = long_desc or short_desc

        # Only accept valid ICD-10 codes (letter + 2-6 alphanumeric chars)
        if not _ICD10_RE.match(code):
            skipped += 1
            continue

        records.append({
            "code": code,
            "description": description[:500],
            "short_description": short_desc[:100],
            "billable": valid_flag == "1",
            "is_active": True,
        })

    print(f"  Parsed {len(records)} ICD-10 codes ({skipped} skipped)")
    new_count = batch_upsert(db, Icd10Code, records, "code")
    print(f"  Done — {new_count} rows upserted")


# ── HCPCS ─────────────────────────────────────────────────────────────────────

def seed_hcpcs(db: Session):
    print("\n[HCPCS] Downloading from CMS...")
    zf = download_zip(HCPCS_URLS)

    # Prefer the main ANWEB Excel file; avoid corrections/transaction files
    names = zf.namelist()
    xlsx_files = [n for n in names if n.lower().endswith(".xlsx")]
    # Rank: prefer "anweb" files, exclude corrections/transaction
    def _hcpcs_rank(n):
        nl = n.lower()
        if "correction" in nl or "transaction" in nl or "noc" in nl:
            return 2
        if "anweb" in nl:
            return 0
        return 1
    xlsx_files.sort(key=_hcpcs_rank)
    if xlsx_files:
        filename = xlsx_files[0]
        print(f"  Parsing Excel: {filename}")
        _seed_hcpcs_excel(db, zf, filename)
    else:
        txt_files = [n for n in names if n.lower().endswith(".txt") and "hcpc" in n.lower() and "layout" not in n.lower()]
        if txt_files:
            print(f"  Parsing text: {txt_files[0]}")
            _seed_hcpcs_text(db, zf, txt_files[0])
        else:
            raise FileNotFoundError(f"No HCPCS data file found in ZIP. Contents: {names}")


def _seed_hcpcs_excel(db: Session, zf: zipfile.ZipFile, filename: str):
    try:
        import openpyxl
    except ImportError:
        print("  openpyxl not installed — run: pip install openpyxl")
        return

    data = zf.read(filename)
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
    ws = wb.active

    records = []
    header_found = False
    code_col = desc_col = short_col = None

    for row in ws.iter_rows(values_only=True):
        if not header_found:
            # Find header row
            row_lower = [str(c).lower() if c else "" for c in row]
            if any("hcpc" in c for c in row_lower):
                for i, c in enumerate(row_lower):
                    if "hcpc" in c:
                        code_col = i
                    elif "long" in c and "desc" in c:
                        desc_col = i
                    elif "short" in c and "desc" in c:
                        short_col = i
                header_found = True
            continue

        if code_col is None:
            continue
        code = str(row[code_col]).strip() if row[code_col] else None
        if not code or len(code) < 2 or len(code) > 7:
            continue

        description = str(row[desc_col]).strip()[:500] if desc_col and row[desc_col] else code
        short = str(row[short_col]).strip()[:200] if short_col and row[short_col] else description[:100]

        records.append({
            "code": code,
            "description": description,
            "short_description": short,
            "is_active": True,
        })

    print(f"  Parsed {len(records)} HCPCS codes")
    new_count = batch_upsert(db, HcpcsCode, records, "code")
    print(f"  Done — {new_count} new codes inserted")


def _seed_hcpcs_text(db: Session, zf: zipfile.ZipFile, filename: str):
    content = zf.read(filename).decode("utf-8", errors="ignore")
    records = []
    for line in content.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            parts = line.split(",")
        if len(parts) < 2:
            continue
        code = parts[0].strip().strip('"')
        if len(code) != 5:
            continue
        description = parts[1].strip().strip('"')[:500]
        records.append({
            "code": code,
            "description": description,
            "short_description": description[:100],
            "is_active": True,
        })

    print(f"  Parsed {len(records)} HCPCS codes")
    new_count = batch_upsert(db, HcpcsCode, records, "code")
    print(f"  Done — {new_count} new codes inserted")


# ── CPT (from CMS PFS RVU file) ───────────────────────────────────────────────

def seed_cpt(db: Session):
    print("\n[CPT] Downloading CMS Physician Fee Schedule (RVU file)...")
    zf = download_zip(CPT_RVU_URLS)

    filename = find_file_in_zip(zf, [".txt", ".csv"], ["rvu", "pprrvu", "pfs"])
    print(f"  Parsing: {filename}")
    content = zf.read(filename).decode("utf-8", errors="ignore")

    records = []
    skipped = 0
    header_skipped = False

    for line in content.splitlines():
        line = line.rstrip()
        if not line:
            continue

        # Tab or pipe delimited
        if "\t" in line:
            parts = line.split("\t")
        elif "|" in line:
            parts = line.split("|")
        else:
            parts = line.split()

        if len(parts) < 4:
            skipped += 1
            continue

        code = parts[0].strip()

        # Skip header rows
        if not code or not code[0].isdigit():
            if not header_skipped:
                header_skipped = True
            skipped += 1
            continue

        # CPT codes: exactly 5 digits
        if len(code) != 5 or not code.isdigit():
            skipped += 1
            continue

        description = parts[2].strip()[:500] if len(parts) > 2 else code

        # RVU value: typically column index 5 or 6
        rvu = None
        import math
        for i in range(4, min(8, len(parts))):
            try:
                val = float(parts[i].strip())
                if val > 0 and math.isfinite(val) and val < 999999:
                    rvu = round(val, 2)
                    break
            except (ValueError, AttributeError):
                pass

        records.append({
            "code": code,
            "description": description,
            "short_description": description[:100],
            "rvu": rvu,
            "is_active": True,
        })

    print(f"  Parsed {len(records)} CPT codes ({skipped} lines skipped)")
    new_count = batch_upsert(db, CptCode, records, "code")
    print(f"  Done — {new_count} new codes inserted")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Seed medical codes from CMS public datasets")
    parser.add_argument("--only", choices=["icd10", "hcpcs", "cpt"],
                        help="Seed only a specific code type")
    args = parser.parse_args()

    print("=" * 60)
    print("  OneClick — CMS Code Seeder")
    print("=" * 60)

    db: Session = SessionLocal()
    try:
        run_all = args.only is None
        if run_all or args.only == "icd10":
            seed_icd10(db)
        if run_all or args.only == "hcpcs":
            seed_hcpcs(db)
        if run_all or args.only == "cpt":
            seed_cpt(db)
    finally:
        db.close()

    print("\n" + "=" * 60)
    print("  Seeding complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
