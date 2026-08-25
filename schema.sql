-- TimescaleDB + PostGIS schema for decoded Teltonika AVL records.
--   psql "$DATABASE_URL" -f schema.sql

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS avl_records (
    imei         text        NOT NULL,
    ts           timestamptz NOT NULL,   -- device clock, from the AVL record
    received_at  timestamptz NOT NULL,   -- server clock, for lag analysis
    codec_id     smallint    NOT NULL,
    priority     smallint    NOT NULL,
    event_io_id  integer     NOT NULL,
    longitude    double precision,
    latitude     double precision,
    geom         geography(Point, 4326), -- NULL when the device had no fix
    altitude_m   integer,
    angle_deg    integer,
    satellites   smallint,
    speed_kmh    integer,
    fix_valid    boolean     NOT NULL,
    io           jsonb       NOT NULL,

    -- Retransmits are normal: a device resends a batch whenever an ACK is
    -- lost. This key is what makes re-inserting the same batch a no-op.
    PRIMARY KEY (imei, ts, event_io_id)
);

-- Timescale requires the partitioning column in every unique index, which is
-- why ts is part of the primary key above.
SELECT create_hypertable('avl_records', 'ts', if_not_exists => TRUE);

-- "Where was vehicle X recently" — the dominant query for a tracking UI.
CREATE INDEX IF NOT EXISTS avl_records_imei_ts_idx
    ON avl_records (imei, ts DESC);

-- Spatial queries (inside this depot, near this stop). Partial: unfixed rows
-- have a NULL geom and would only bloat the index.
CREATE INDEX IF NOT EXISTS avl_records_geom_idx
    ON avl_records USING GIST (geom)
    WHERE geom IS NOT NULL;

-- Lookups by IO element, e.g. every record where ignition (id 239) was on.
CREATE INDEX IF NOT EXISTS avl_records_io_idx
    ON avl_records USING GIN (io jsonb_path_ops);
