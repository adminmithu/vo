import os
import sqlite3
from datetime import datetime
import config

# Determine if Supabase PostgreSQL is enabled
USE_POSTGRES = bool(config.DATABASE_URL and config.DATABASE_URL.startswith("postgres"))

if USE_POSTGRES:
    import psycopg2
    from psycopg2.extras import RealDictCursor

def get_connection():
    if USE_POSTGRES:
        conn = psycopg2.connect(config.DATABASE_URL, cursor_factory=RealDictCursor)
        conn.autocommit = True
        return conn
    else:
        conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

def adapt_query(query: str) -> str:
    """Translates SQLite query to PostgreSQL dialect if running on Supabase."""
    if USE_POSTGRES:
        # Replace ? with %s for PostgreSQL
        query = query.replace("?", "%s")
        # Replace AUTOINCREMENT with SERIAL in CREATE TABLE
        query = query.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        # Replace INTEGER PRIMARY KEY with BIGINT PRIMARY KEY for Telegram user_id
        query = query.replace("user_id INTEGER PRIMARY KEY", "user_id BIGINT PRIMARY KEY")
        query = query.replace("user_id INTEGER", "user_id BIGINT")
    return query

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Users table
    cursor.execute(adapt_query("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            selected_domain TEXT DEFAULT '',
            selected_service TEXT DEFAULT 'General / Auto',
            is_banned INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    
    # 2. History table (permanently stored)
    cursor.execute(adapt_query("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            email TEXT NOT NULL,
            token TEXT,
            cookie TEXT DEFAULT '',
            service TEXT,
            expires_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # Try adding cookie column if upgrading from older SQLite
    if not USE_POSTGRES:
        try:
            cursor.execute("ALTER TABLE history ADD COLUMN cookie TEXT DEFAULT ''")
        except Exception:
            pass
    
    # 3. Settings table
    cursor.execute(adapt_query("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """))
    
    # 4. Seen messages cache
    cursor.execute(adapt_query("""
        CREATE TABLE IF NOT EXISTS seen_messages (
            message_id TEXT PRIMARY KEY,
            email TEXT,
            seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # 5. Activity logs table
    cursor.execute(adapt_query("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            action TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    if not USE_POSTGRES:
        conn.commit()
    conn.close()

def log_activity(user_id: int, username: str, first_name: str, action: str, details: str = ""):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("""
        INSERT INTO activity_logs (user_id, username, first_name, action, details)
        VALUES (?, ?, ?, ?, ?)
    """), (user_id, username or "", first_name or "", action, details or ""))
    if not USE_POSTGRES:
        conn.commit()
    conn.close()

def get_recent_activity_logs(limit: int = 15):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("""
        SELECT * FROM activity_logs ORDER BY id DESC LIMIT ?
    """), (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def register_user(user_id: int, username: str, first_name: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("""
        INSERT INTO users (user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
    """), (user_id, username or "", first_name or ""))
    if not USE_POSTGRES:
        conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("SELECT * FROM users WHERE user_id = ?"), (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def set_user_domain(user_id: int, domain: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("UPDATE users SET selected_domain = ? WHERE user_id = ?"), (domain, user_id))
    if not USE_POSTGRES:
        conn.commit()
    conn.close()

def set_user_service(user_id: int, service: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("UPDATE users SET selected_service = ? WHERE user_id = ?"), (service, user_id))
    if not USE_POSTGRES:
        conn.commit()
    conn.close()

def add_mail_history(user_id: int, email: str, token: str = "", cookie: str = "", service: str = "", expires_at: str = ""):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("""
        INSERT INTO history (user_id, email, token, cookie, service, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """), (user_id, email, token, cookie, service, expires_at))
    if not USE_POSTGRES:
        conn.commit()
    conn.close()

def get_user_history(user_id: int, limit: int = 10):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("""
        SELECT * FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?
    """), (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_mail_by_address(address: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("SELECT * FROM history WHERE email = ? ORDER BY id DESC LIMIT 1"), (address,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def clear_user_history(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("DELETE FROM history WHERE user_id = ?"), (user_id,))
    if not USE_POSTGRES:
        conn.commit()
    conn.close()

def get_all_active_mails(limit: int = 50):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("""
        SELECT user_id, email, token, cookie FROM history ORDER BY id DESC LIMIT ?
    """), (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def is_message_seen(message_id: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("SELECT 1 FROM seen_messages WHERE message_id = ?"), (str(message_id),))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def mark_message_seen(message_id: str, email: str):
    conn = get_connection()
    cursor = conn.cursor()
    if USE_POSTGRES:
        cursor.execute("""
            INSERT INTO seen_messages (message_id, email)
            VALUES (%s, %s)
            ON CONFLICT(message_id) DO NOTHING
        """, (str(message_id), email))
    else:
        cursor.execute("""
            INSERT OR IGNORE INTO seen_messages (message_id, email)
            VALUES (?, ?)
        """, (str(message_id), email))
        conn.commit()
    conn.close()

def get_all_users():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("SELECT user_id FROM users WHERE is_banned = 0"))
    rows = cursor.fetchall()
    conn.close()
    return [r["user_id"] for r in rows]

def get_stats():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("SELECT COUNT(*) as total_users FROM users"))
    total_users = cursor.fetchone()["total_users"]

    cursor.execute(adapt_query("SELECT COUNT(*) as total_mails FROM history"))
    total_mails = cursor.fetchone()["total_mails"]

    cursor.execute(adapt_query("SELECT COUNT(*) as banned_users FROM users WHERE is_banned = 1"))
    banned_users = cursor.fetchone()["banned_users"]

    cursor.execute(adapt_query("SELECT COUNT(*) as total_logs FROM activity_logs"))
    total_logs = cursor.fetchone()["total_logs"]

    conn.close()
    return {
        "total_users": total_users,
        "total_mails": total_mails,
        "banned_users": banned_users,
        "total_logs": total_logs
    }

def set_ban_status(user_id: int, is_banned: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("UPDATE users SET is_banned = ? WHERE user_id = ?"), (is_banned, user_id))
    if not USE_POSTGRES:
        conn.commit()
    conn.close()

def is_banned(user_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("SELECT is_banned FROM users WHERE user_id = ?"), (user_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row["is_banned"]) if row else False

def get_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("SELECT value FROM settings WHERE key = ?"), (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("""
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """), (key, value))
    if not USE_POSTGRES:
        conn.commit()
    conn.close()
