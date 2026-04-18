"""Thin SQLite wrapper. WAL + foreign_keys on every connection."""
import sqlite3
from contextlib import contextmanager
from config import DB_PATH, BASE

SCHEMA = (BASE / "schema.sql").read_text()

def init():
    with connect() as c:
        c.executescript(SCHEMA)

@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()

def fetchall(sql, *params):
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]

def fetchone(sql, *params):
    with connect() as c:
        r = c.execute(sql, params).fetchone()
        return dict(r) if r else None

def execute(sql, *params):
    with connect() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid

if __name__ == "__main__":
    init()
    print("db initialised at", DB_PATH)
