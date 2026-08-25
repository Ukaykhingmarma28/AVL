#!/usr/bin/env python3
"""
Look at what the fleet has reported.

    .venv/bin/python show_data.py                 # latest position per device
    .venv/bin/python show_data.py --recent 20     # last 20 records
    .venv/bin/python show_data.py --imei 3563...  # one device
    .venv/bin/python show_data.py --watch         # live, refreshes every 5s
    .venv/bin/python show_data.py --io            # decode the IO elements too

Reads DATABASE_URL from the environment:
    set -a; . ./.env; set +a
"""

import argparse
import os
import sys
import time

try:
    import psycopg2
except ImportError:
    sys.exit("psycopg2 missing. Run: .venv/bin/pip install psycopg2-binary")


def fmt_row(r):
    imei, ts, lon, lat, spd, sats, ang, valid = r
    when = ts.strftime("%Y-%m-%d %H:%M:%S")
    where = f"{lat:9.5f},{lon:10.5f}" if valid else "     no fix        "
    return f"  {imei}  {when}  {where}  {spd or 0:3d} km/h  {sats or 0:2d} sat  {ang or 0:3d}deg"


def latest(cur):
    cur.execute("""
        select distinct on (imei) imei, ts, longitude, latitude,
               speed_kmh, satellites, angle_deg, fix_valid
        from avl_records order by imei, ts desc
    """)
    rows = cur.fetchall()
    if not rows:
        print("  no data yet")
        return
    print("  IMEI             LAST SEEN (UTC)      LATITUDE, LONGITUDE   SPEED    SATS  HEADING")
    for r in rows:
        print(fmt_row(r))


def recent(cur, n, imei=None, show_io=False):
    where, args = ("where imei = %s", (imei, n)) if imei else ("", (n,))
    cur.execute(f"""
        select imei, ts, longitude, latitude, speed_kmh, satellites,
               angle_deg, fix_valid, io
        from avl_records {where} order by ts desc limit %s
    """, args)
    rows = cur.fetchall()
    if not rows:
        print("  no matching records")
        return
    for r in rows:
        print(fmt_row(r[:8]))
        if show_io:
            named = {v.get("name") or f"id{k}": v.get("value")
                     for k, v in (r[8] or {}).items()}
            for k, v in sorted(named.items()):
                print(f"        {k}: {v}")


def summary(cur):
    cur.execute("select count(*), count(distinct imei) from avl_records")
    total, devices = cur.fetchone()
    print(f"  {total} record(s) from {devices} device(s)")
    if not total:
        return
    cur.execute("""
        select imei, count(*), min(ts), max(ts),
               count(geom) filter (where geom is not null),
               round(max(speed_kmh))
        from avl_records group by imei order by imei
    """)
    print("\n  IMEI             ROWS   WITH FIX  MAX KM/H  LAST SEEN (UTC)")
    for imei, n, first, last, fix, mx in cur.fetchall():
        print(f"  {imei}  {n:6d}  {fix:8d}  {mx or 0:8}  {last:%Y-%m-%d %H:%M:%S}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recent", type=int, metavar="N", help="show the last N records")
    ap.add_argument("--imei", help="filter to one device")
    ap.add_argument("--io", action="store_true", help="also print IO elements")
    ap.add_argument("--watch", action="store_true", help="refresh every 5 seconds")
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL not set. Run:  set -a; . ./.env; set +a")

    conn = psycopg2.connect(dsn, connect_timeout=10)
    conn.autocommit = True
    try:
        while True:
            if args.watch:
                print("\033[2J\033[H", end="")   # clear
            with conn.cursor() as cur:
                summary(cur)
                print()
                if args.recent:
                    recent(cur, args.recent, args.imei, args.io)
                else:
                    latest(cur)
            if not args.watch:
                break
            print("\n  (ctrl-c to stop)")
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()


if __name__ == "__main__":
    main()
