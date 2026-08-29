"""
db.py - one shared PostgreSQL connection helper (Neon).

The app was migrated from MySQL (PyMySQL) to PostgreSQL (psycopg2).
The schema and data live in a Neon Postgres database; point the app at
it via .env (see .env.example).

Two ways to configure:
  1. DATABASE_URL - a full libpq DSN, e.g.
       postgresql://user:pass@host:5432/dbname?sslmode=require
  2. Individual vars - DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME,
     DB_SSLMODE. sslmode defaults to 'require' for remote hosts and
     'prefer' for localhost.

Connections are autocommit and return real dict rows (RealDictCursor),
matching the behavior the app already expects from PyMySQL's DictCursor.
"""

import os
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras


def get_connection():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        # Neon's pooler requires TLS - force sslmode=require for remote hosts
        # if the DSN doesn't already specify one.
        parsed = urlparse(database_url)
        if parsed.hostname not in ("localhost", "127.0.0.1") and "sslmode" not in parsed.query:
            sep = "&" if parsed.query else "?"
            database_url = f"{database_url}{sep}sslmode=require"
        conn = psycopg2.connect(
            database_url,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        conn.autocommit = True
        return conn

    host = os.environ.get("DB_HOST", "localhost")
    sslmode = os.environ.get("DB_SSLMODE")
    if not sslmode:
        sslmode = "require" if host not in ("localhost", "127.0.0.1") else "prefer"

    conn = psycopg2.connect(
        host=host,
        port=int(os.environ.get("DB_PORT") or 5432),
        user=os.environ.get("DB_USER", "feeder_monitor"),
        password=os.environ.get("DB_PASSWORD", ""),
        dbname=os.environ.get("DB_NAME", "feeder_monitor"),
        sslmode=sslmode,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = True
    return conn


def query(sql, params=None, fetch=True):
    """Drop-in replacement for the old MySQL-based query() helper.
    Returns a list of dict rows when fetch=True, or the affected
    row count when fetch=False (autocommit is already on, so no
    explicit commit call is needed)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        if fetch:
            result = cur.fetchall()
        else:
            result = cur.rowcount
        cur.close()
        return result
    finally:
        conn.close()