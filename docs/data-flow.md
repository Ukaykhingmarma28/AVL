# Device to database: the full path

Line numbers are `teltonika_listener.py` unless stated otherwise.

```
┌──────────────────────────────────────────────────────────────────────┐
│  FMB920 tracker in the vehicle                                       │
│  configured with setparam 2004:<server_ip>, 2005:5027                │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  raw TCP, port 5027
                                │  (not HTTP — no proxy can carry this)
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  TeltonikaServer.accept loop                            :834         │
│  one thread per connection, cap --max-connections                    │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  ClientHandler.run()                                    :682         │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
                 ┌──────────────────────────────┐
                 │ _do_imei_handshake()   :610  │
                 │ 2-byte len + ASCII IMEI      │
                 └──────────────┬───────────────┘
                                ▼
                        ╱────────────────╲
                       ╱ IMEI allowed?    ╲───── no ──▶ send 0x00, close   :642
                       ╲ (--allowlist)    ╱             allowed_imeis.txt
                        ╲────────────────╱
                                │ yes: send 0x01
                                ▼
        ┌───────────────────────────────────────────────┐
        │  _serve_packets() loop                 :707   │
        └───────────────────────┬───────────────────────┘
                                ▼
                 ┌──────────────────────────────┐
                 │ _read_packet()         :652  │  framing: read 8 bytes,
                 │ 8-byte header → length       │  then exactly length+4.
                 │ then body + 4-byte CRC       │  handles split AND
                 └──────────────┬───────────────┘  coalesced TCP writes
                                │
                                ├──▶ logs/raw.jsonl        :720  (--no-raw disables)
                                ▼
                 ┌──────────────────────────────┐
                 │ parse_avl_packet()     :425  │◀── io_definitions.json
                 │  preamble 0x00000000   :438  │    (IO id → name/unit/scale)
                 │  declared length match :447  │
                 │  CRC-16/IBM verify     :453  │
                 │  per-record decode           │
                 │  Codec 8 / 8E / 16           │
                 └──────────────┬───────────────┘
                                ▼
                        ╱────────────────╲
                       ╱  parse ok?       ╲──── no ──▶ log hex dump + byte
                       ╲                  ╱            offset, NO ACK  :729
                        ╲────────────────╱             device retransmits
                                │ yes
                                ▼
   ╔══════════════════════════════════════════════════════════════════╗
   ║  sink.emit()  — BEFORE the ACK                            :759   ║
   ║  Teltonika drops records from device memory once ACKed, so       ║
   ║  acknowledging first would lose data on a write failure.         ║
   ╚═════════════════════════════════┬════════════════════════════════╝
                                     ▼
        ┌────────────────────────────────────────────────────┐
        │  TimescaleSink.emit()          db_sink.py:85       │
        │                                                    │
        │  1. super().emit()  ─────▶ logs/records.jsonl      │
        │     synchronous, durable. This is the system of    │
        │     record; the database is a replayable sink.     │
        │                                                    │
        │  2. buffer rows in memory (batch_size=200)         │
        └────────────────────────────┬───────────────────────┘
                                     ▼
                 ┌───────────────────────────────────┐
                 │ flush()            db_sink.py:127 │
                 │ on 200 rows, or every 2s by the   │
                 │ background thread, or at exit     │
                 └────────────────┬──────────────────┘
                                  │ execute_values, one round trip
                                  ▼
                 ┌───────────────────────────────────┐
                 │ INSERT INTO avl_records ...       │
                 │ ON CONFLICT (imei, ts,            │
                 │   event_io_id) DO NOTHING         │
                 │ ← retransmits become no-ops       │
                 └────────────────┬──────────────────┘
                                  │ psycopg2, TCP
                                  ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  TimescaleDB 18.4 + PostGIS 3.6            schema.sql            │
   │                                                                  │
   │  avl_records  hypertable on ts                                   │
   │    geom  geography(Point,4326)  ← built server-side from lon/lat │
   │                                   NULL when the device had no fix│
   │    io    jsonb                  ← full IO element set, GIN index │
   │                                                                  │
   │  local:  docker-compose.yml, bound to 127.0.0.1                  │
   │  remote: Railway TCP proxy, *.proxy.rlwy.net:<random port>       │
   └──────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                   4-byte ACK (record count) → device      :761
                   device now frees those records
```

## Files

| File | Role in the path |
|---|---|
| `teltonika_listener.py` | accept, IMEI handshake, framing, decode, ACK |
| `io_definitions.json` | IO id → name/unit/scale; unknown ids decode unnamed |
| `db_sink.py` | JSONL passthrough, batching, idempotent insert |
| `schema.sql` | hypertable, PostGIS column, indexes, notify trigger |
| `api/api_server.py` | reads the table for a frontend; not on the device path (`docs/api.md`) |
| `docker-compose.yml` | production: listener + database on one host |
| `check_db.py` | pre-flight verification of a database target |
| `mock_device.py` | fake devices; replaces the top box for testing |
| `allowed_imeis.txt` | allowlist consulted at the handshake |
| `.env` | `DATABASE_URL`, `POSTGRES_PASSWORD` (never committed) |

## Two ordering rules that matter

**Emit before ACK.** A device deletes records from its own memory the moment
it is acknowledged. Acknowledging first would turn any sink failure into
permanent data loss.

**Parse failures are never acknowledged.** The device retransmits the same
batch, which is what you want while the parser is still being proven. This is
also why the insert must be idempotent: honest retransmits are routine.
