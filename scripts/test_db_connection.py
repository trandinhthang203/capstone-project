import os
import sys

# Load .env
try:
    # pyrefly: ignore [missing-import]
    from dotenv import load_dotenv
    load_dotenv()
    print("[OK] dotenv loaded")
except ImportError:
    print("[WARN] python-dotenv not found, reading env vars directly")

# Test psycopg2
try:
    import psycopg2
    print("[OK] psycopg2 installed")
except ImportError:
    print("[FAIL] psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

def mask_url(url):
    """Mask password in URL for safe display."""
    try:
        at_idx = url.index("@")
        # Find the password part between : and @
        prefix = url[:at_idx]
        suffix = url[at_idx:]
        colon_idx = prefix.rindex(":")
        return prefix[:colon_idx] + ":***" + suffix
    except Exception:
        return url

urls = {
    "AWS RDS (Singapore) - SQL_DATABASE_URL": os.getenv("SQL_DATABASE_URL"),
    "Local PostgreSQL - ASYNC_DB_URL": (os.getenv("ASYNC_DB_URL") or "").replace("postgresql+asyncpg", "postgresql"),
}

print("\n" + "="*60)
print("DATABASE CONNECTION TEST")
print("="*60)

for name, url in urls.items():
    print(f"\n>> Testing: {name}")
    if not url:
        print("   [SKIP] URL not set in .env")
        continue
    print(f"   URL: {mask_url(url)}")
    try:
        conn = psycopg2.connect(url, connect_timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()[0]
        print(f"   [OK] Connected!")
        print(f"   [OK] PostgreSQL: {version.split(',')[0]}")
        cur.execute("SELECT current_database();")
        db = cur.fetchone()[0]
        print(f"   [OK] Database: {db}")
        # List tables
        cur.execute("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename;
        """)
        tables = [row[0] for row in cur.fetchall()]
        print(f"   [OK] Tables found: {tables if tables else '(none)'}")
        cur.close()
        conn.close()
    except psycopg2.OperationalError as e:
        print(f"   [FAIL] Connection failed: {e}")
    except Exception as e:
        print(f"   [FAIL] {type(e).__name__}: {e}")

print("\n" + "="*60)
print("Test complete.")
print("="*60)
