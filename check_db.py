#!/usr/bin/env python3
"""
Verify a TimescaleDB target before pointing the listener at it.

    .venv/bin/python check_db.py "$DATABASE_URL"
    .venv/bin/python check_db.py "$DATABASE_URL" --apply-schema

Checks the connection, the two required extensions, and the table.
"""

import argparse
import pathlib
import sys

try:
    import psycopg2
except ImportError:
    sys.exit("psycopg2 missing. Run: .venv/bin/pip install psycopg2-binary")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dsn", nargs="?", help="postgres DSN (or set DATABASE_URL)")
    ap.add_argument("--apply-schema", action="store_true",
                    help="run schema.sql before checking")
    args = ap.parse_args()

    import os
    dsn = args.dsn or os.environ.get("DATABASE_URL")
    if not dsn:
        return ap.error("pass a DSN or set DATABASE_URL")

    if ".railway.internal" in dsn:
        print("FAIL: that is Railway's private hostname. It only resolves from")
        print("      inside Railway. Use DATABASE_PUBLIC_URL (*.proxy.rlwy.net).")
        return 2
    if ".up.railway.app" in dsn:
        print("FAIL: *.up.railway.app is an HTTP-only edge and cannot carry")
        print("      Postgres. Use DATABASE_PUBLIC_URL (*.proxy.rlwy.net).")
        return 2

    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
    except Exception as exc:
        print(f"FAIL: could not connect: {exc}")
        return 1

    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT version()")
        print("connected:", cur.fetchone()[0].split(",")[0])

        if args.apply_schema:
            sql = pathlib.Path(__file__).with_name("schema.sql").read_text()
            cur.execute(sql)
            print("schema applied")

        cur.execute("SELECT extname, extversion FROM pg_extension ORDER BY extname")
        exts = dict(cur.fetchall())
        for name in ("timescaledb", "postgis"):
            mark = "ok" if name in exts else "MISSING"
            print(f"  {name:12} {exts.get(name, '-'):10} {mark}")

        cur.execute("SELECT to_regclass('avl_records')")
        if cur.fetchone()[0] is None:
            print("  avl_records  -          MISSING (run with --apply-schema)")
        else:
            cur.execute("SELECT count(*) FROM avl_records")
            print(f"  avl_records  rows={cur.fetchone()[0]}")

    conn.close()
    missing = [n for n in ("timescaledb", "postgis") if n not in exts]
    if missing:
        print("\nmissing extension(s):", ", ".join(missing))
        print("re-run with --apply-schema, or CREATE EXTENSION manually")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
