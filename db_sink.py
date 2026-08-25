"""
TimescaleDB sink for decoded AVL records.

Drop-in replacement for RecordSink. Keeps the JSON file stream (that is what
makes the database a replayable secondary sink rather than the system of
record) and additionally batches rows into Timescale.

Needs psycopg2:  pip install psycopg2-binary
"""

from __future__ import annotations

import atexit
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

import psycopg2
from psycopg2.extras import execute_values

from teltonika_listener import RecordSink

log = logging.getLogger("teltonika.db")

_COLUMNS = (
    "imei, ts, received_at, codec_id, priority, event_io_id, "
    "longitude, latitude, geom, altitude_m, angle_deg, satellites, "
    "speed_kmh, fix_valid, io"
)

# geom is built server-side from the same lon/lat, and left NULL without a fix.
_TEMPLATE = (
    "(%s,%s,%s,%s,%s,%s,%s,%s,"
    "CASE WHEN %s THEN ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography END,"
    "%s,%s,%s,%s,%s,%s)"
)

_INSERT = (
    f"INSERT INTO avl_records ({_COLUMNS}) VALUES %s "
    "ON CONFLICT (imei, ts, event_io_id) DO NOTHING"
)


class TimescaleSink(RecordSink):
    def __init__(
        self,
        dsn: str,
        pretty: bool = False,
        batch_size: int = 200,
        flush_interval: float = 2.0,
    ):
        super().__init__(pretty=pretty)
        self.dsn = dsn
        self.batch_size = batch_size
        self.flush_interval = flush_interval

        self._buf: list[tuple] = []
        self._buf_lock = threading.Lock()
        self._conn = None
        self._conn_lock = threading.Lock()
        self._stopping = threading.Event()

        self._timer = threading.Thread(target=self._flush_loop, daemon=True)
        self._timer.start()
        atexit.register(self.close)

    # -- connection ------------------------------------------------------

    def _connect(self):
        """Reconnect lazily so a database blip does not kill the listener."""
        with self._conn_lock:
            if self._conn is not None and self._conn.closed == 0:
                return self._conn
            self._conn = psycopg2.connect(self.dsn, connect_timeout=10)
            self._conn.autocommit = True
            log.info("connected to timescale")
            return self._conn

    # -- sink ------------------------------------------------------------

    def emit(self, imei, addr, decoded: dict[str, Any]) -> None:
        # File stream first, unchanged. If the database is unreachable the
        # records still land on disk and can be replayed later.
        super().emit(imei, addr, decoded)

        if not imei:
            # imei is part of the primary key, so an unidentified device has
            # nowhere to go. The allowlist normally prevents this.
            log.warning("dropping %d record(s) with no imei from %s",
                        decoded["record_count"], addr[0])
            return

        received_at = datetime.now(timezone.utc)
        rows = [self._row(imei, received_at, decoded, r) for r in decoded["records"]]

        with self._buf_lock:
            self._buf.extend(rows)
            full = len(self._buf) >= self.batch_size
        if full:
            self.flush()

    def _row(self, imei, received_at, decoded, record) -> tuple:
        gps = record["gps"]
        valid = bool(gps["valid"])
        lon = gps["longitude"] if valid else None
        lat = gps["latitude"] if valid else None
        ts = datetime.fromtimestamp(record["timestamp_ms"] / 1000, timezone.utc)
        return (
            imei, ts, received_at,
            decoded["codec_id"], record["priority"], record["event_io_id"],
            lon, lat,
            valid, lon, lat,           # geom CASE arguments
            gps["altitude_m"], gps["angle_deg"], gps["satellites"],
            gps["speed_kmh"], valid,
            json.dumps(record["io"]),
        )

    # -- flushing --------------------------------------------------------

    def flush(self) -> None:
        with self._buf_lock:
            if not self._buf:
                return
            batch, self._buf = self._buf, []

        try:
            conn = self._connect()
            with conn.cursor() as cur:
                execute_values(cur, _INSERT, batch, template=_TEMPLATE,
                               page_size=len(batch))
            log.debug("flushed %d row(s)", len(batch))
        except Exception:
            log.exception("flush of %d row(s) failed; rows remain in the "
                          "jsonl log and can be replayed", len(batch))
            with self._conn_lock:
                if self._conn is not None:
                    try:
                        self._conn.close()
                    finally:
                        self._conn = None

    def _flush_loop(self) -> None:
        while not self._stopping.wait(self.flush_interval):
            self.flush()

    def close(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        self.flush()
        with self._conn_lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
