import os
import pymysql
from functools import lru_cache

DB_HOST     = os.getenv("DB_HOST")
DB_PORT     = int(os.getenv("DB_PORT", "3306"))
DB_NAME     = os.getenv("DB_NAME")
DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")


def get_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        charset="utf8mb4",
        connect_timeout=10,
    )


def test_connection() -> tuple[bool, str]:
    """Testet die DB-Verbindung. Gibt (True, Info) oder (False, Fehlermeldung) zurück."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM tracks")
            count = cur.fetchone()[0]
        conn.close()
        return True, f"Verbindung OK – {count} Strecken in DB."
    except Exception as e:
        return False, f"Verbindung fehlgeschlagen: {e}"


def check_connection_on_startup():
    """Wird beim Bot-Start aufgerufen – loggt DB-Status."""
    ok, msg = test_connection()
    if ok:
        print(f"[INFO] DB: {msg}")
    else:
        print(f"[ERROR] DB: {msg}")
    return ok
