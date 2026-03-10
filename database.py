import sqlite3
import pandas as pd
from pathlib import Path

BASE_DIR  = Path(__file__).parent
EXCEL_PATH = BASE_DIR / "sample_data.xlsx"

# Try to store the DB alongside main.py; fall back to system temp if the
# filesystem doesn't support SQLite locking (e.g. some network mounts).
_primary = BASE_DIR / "pharma_rep.db"
try:
    _test = sqlite3.connect(_primary)
    _test.execute("CREATE TABLE IF NOT EXISTS _ping (x INTEGER)")
    _test.close()
    DB_PATH = _primary
except Exception:
    import tempfile
    DB_PATH = Path(tempfile.gettempdir()) / "pharma_rep.db"


def init_db():
    """Load Excel sample data into SQLite on startup."""
    conn = sqlite3.connect(DB_PATH)
    try:
        df_personal = pd.read_excel(EXCEL_PATH, sheet_name="Personal Details")
        df_license = pd.read_excel(EXCEL_PATH, sheet_name="License Details")
        df_drugs = pd.read_excel(EXCEL_PATH, sheet_name="Drug Purchase Details")

        df_personal.to_sql("personal_details", conn, if_exists="replace", index=False)
        df_license.to_sql("license_details", conn, if_exists="replace", index=False)
        df_drugs.to_sql("drug_purchase_details", conn, if_exists="replace", index=False)

        conn.commit()
        print(f"✅ DB ready — {len(df_personal)} doctors, {len(df_drugs)} purchase records")
    finally:
        conn.close()


def _ensure_db():
    """Re-initialise the database if tables are missing (Vercel cold-start safety)."""
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='personal_details'")
        if not c.fetchone():
            conn.close()
            init_db()
    except Exception:
        conn.close()
        init_db()
    else:
        conn.close()


def run_query(sql: str) -> list[dict]:
    """Execute a SQL query and return rows as a list of dicts."""
    _ensure_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_stats() -> dict:
    """Return basic DB stats for the health endpoint."""
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM personal_details")
        doctors = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM drug_purchase_details")
        purchases = c.fetchone()[0]
        return {"doctors": doctors, "purchase_records": purchases}
    finally:
        conn.close()
