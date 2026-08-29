import os
import mysql.connector
from mysql.connector import pooling

# Set these via environment variables, or fall back to local-dev defaults
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", 3306)),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", "Aswath@466"),
    "database": os.environ.get("DB_NAME", "thookkupalam_feeder2"),
}

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="thookkupalam_pool",
            pool_size=5,
            **DB_CONFIG
        )
    return _pool


def get_conn():
    return get_pool().get_connection()


def query(sql, params=None, fetch=True):
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params or ())
        if fetch:
            result = cur.fetchall()
        else:
            conn.commit()
            result = cur.rowcount
        cur.close()
        return result
    finally:
        conn.close()