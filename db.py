import sqlite3
import json
import secrets
import string

# 数据库文件路径
DATABASE_FILE = "cases_db.sqlite"

def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_results (
            key TEXT PRIMARY KEY,
            json_data TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def generate_unique_key(length=8):
    characters = string.ascii_letters + string.digits
    while True:
        key = ''.join(secrets.choice(characters) for _ in range(length))
        if not get_result_by_key(key):
            return key

def save_result(json_data: dict) -> str:
    key = generate_unique_key()
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    try:
        json_str = json.dumps(json_data, ensure_ascii=False)
        cursor.execute(
            "INSERT INTO saved_results (key, json_data) VALUES (?, ?)",
            (key, json_str)
        )
        conn.commit()
        return key
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_result_by_key(key: str) -> dict | None:
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT json_data FROM saved_results WHERE key = ?",
        (key,)
    )
    row = cursor.fetchone()
    conn.close()

    if row:
        return json.loads(row[0])
    return None

init_db()