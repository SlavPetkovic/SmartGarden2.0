-- Layer 02 -- Storage. DATA-1...6, STOR-1...6.
--
-- One source of schema truth (STOR-1): this file and the ones that follow it
-- in this directory, applied in order and recorded in schema_migrations.
-- Nothing elsewhere creates or alters a table.
--
-- `reading` is deliberately narrow (DATA-1): channel_id, ts, value, quality.
-- Adding a sensor is a row in `sensor` and `channel`, never a column here.

CREATE TABLE node (
    id                   INTEGER PRIMARY KEY,
    slug                 TEXT NOT NULL UNIQUE,
    kind                 TEXT NOT NULL,
    description          TEXT NOT NULL DEFAULT '',
    stale_after_seconds  REAL NOT NULL,
    last_seen_at         TEXT
);

CREATE TABLE zone (
    id                     INTEGER PRIMARY KEY,
    slug                   TEXT NOT NULL UNIQUE,
    name                   TEXT NOT NULL,
    timezone               TEXT NOT NULL DEFAULT 'UTC',
    watering_start_hour    INTEGER NOT NULL DEFAULT 7,
    watering_end_hour      INTEGER NOT NULL DEFAULT 21,
    daily_budget_seconds   REAL NOT NULL DEFAULT 120.0,
    max_pulses_per_hour    INTEGER NOT NULL DEFAULT 6,
    cooldown_seconds       REAL NOT NULL DEFAULT 900.0,
    settle_seconds         REAL NOT NULL DEFAULT 600.0,
    enabled                INTEGER NOT NULL DEFAULT 1
);

-- A plant's care fields are nullable on purpose (DATA-5): unset means "use
-- this zone's default", resolved by the caller, not by a default value here.
CREATE TABLE plant (
    id                       INTEGER PRIMARY KEY,
    slug                     TEXT NOT NULL UNIQUE,
    name                     TEXT NOT NULL,
    zone_id                  INTEGER NOT NULL REFERENCES zone(id),
    species                  TEXT NOT NULL DEFAULT '',
    location                 TEXT NOT NULL DEFAULT '',
    moisture_low             REAL,
    moisture_high            REAL,
    dli_target_moles         REAL,
    photoperiod_start_hour   INTEGER,
    photoperiod_end_hour     INTEGER,
    notes                    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE device (
    id               INTEGER PRIMARY KEY,
    slug             TEXT NOT NULL UNIQUE,
    kind             TEXT NOT NULL,
    zone_id          INTEGER NOT NULL REFERENCES zone(id),
    pin              INTEGER NOT NULL,
    active_low       INTEGER NOT NULL DEFAULT 1,
    max_on_seconds   REAL NOT NULL,
    enabled          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE sensor (
    id                 INTEGER PRIMARY KEY,
    slug               TEXT NOT NULL UNIQUE,
    node_id            INTEGER NOT NULL REFERENCES node(id),
    driver             TEXT NOT NULL,
    address            INTEGER,
    mux_address        INTEGER,
    mux_channel        INTEGER,
    interval_seconds   REAL NOT NULL,
    enabled            INTEGER NOT NULL DEFAULT 1
);

-- Reconciled at startup from each driver's channels() declaration (DATA-2).
-- `role` is nullable: a channel with no role is still recorded and charted,
-- it just cannot drive a decision (DATA-3).
CREATE TABLE channel (
    id              INTEGER PRIMARY KEY,
    sensor_id       INTEGER NOT NULL REFERENCES sensor(id),
    key             TEXT NOT NULL,
    unit            TEXT NOT NULL,
    precision       INTEGER NOT NULL DEFAULT 2,
    role            TEXT,
    plausible_min   REAL,
    plausible_max   REAL,
    zone_id         INTEGER REFERENCES zone(id),
    plant_id        INTEGER REFERENCES plant(id),
    description     TEXT NOT NULL DEFAULT '',
    UNIQUE (sensor_id, key)
);

CREATE TABLE reading (
    id           INTEGER PRIMARY KEY,
    channel_id   INTEGER NOT NULL REFERENCES channel(id),
    ts           TEXT NOT NULL,
    value        REAL NOT NULL,
    quality      TEXT NOT NULL DEFAULT 'ok'
);

CREATE INDEX idx_reading_channel_ts ON reading (channel_id, ts);

-- Rollups (STOR-2, STOR-3): one row per (channel, tier, bucket_start), storing
-- min/max/mean/count rather than just mean, so variability survives
-- downsampling. Re-running the job over a window replaces those rows rather
-- than adding to them, which is what makes it idempotent.
CREATE TABLE reading_rollup (
    id             INTEGER PRIMARY KEY,
    channel_id     INTEGER NOT NULL REFERENCES channel(id),
    tier           TEXT NOT NULL,
    bucket_start   TEXT NOT NULL,
    min_value      REAL NOT NULL,
    max_value      REAL NOT NULL,
    mean_value     REAL NOT NULL,
    sample_count   INTEGER NOT NULL,
    UNIQUE (channel_id, tier, bucket_start)
);

CREATE INDEX idx_rollup_channel_tier_bucket ON reading_rollup (channel_id, tier, bucket_start);

CREATE TABLE decision (
    id                 INTEGER PRIMARY KEY,
    ts                 TEXT NOT NULL,
    zone_id            INTEGER NOT NULL REFERENCES zone(id),
    kind               TEXT NOT NULL,
    action             TEXT,
    duration_seconds   REAL,
    reason             TEXT NOT NULL DEFAULT '',
    inputs             TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_decision_zone_ts ON decision (zone_id, ts);

-- Manual instructions queued by the UI and drained by the control loop
-- (ARCH-3). A "water now" button writes a row here; it does not touch a
-- device directly.
CREATE TABLE command (
    id                 INTEGER PRIMARY KEY,
    ts                 TEXT NOT NULL,
    kind               TEXT NOT NULL,
    zone_id            INTEGER REFERENCES zone(id),
    duration_seconds   REAL,
    issued_by          TEXT NOT NULL DEFAULT 'ui',
    consumed_at        TEXT
);

-- pre_value/post_value are the labelled training example for Phase 2 (ML-3);
-- forced_off distinguishes a watchdog or panic-off stop from a clean finish.
CREATE TABLE actuation (
    id                   INTEGER PRIMARY KEY,
    ts                   TEXT NOT NULL,
    zone_id              INTEGER NOT NULL REFERENCES zone(id),
    device_id            INTEGER NOT NULL REFERENCES device(id),
    action               TEXT NOT NULL,
    state                TEXT NOT NULL,
    commanded_seconds    REAL,
    actual_seconds       REAL,
    pre_value            REAL,
    post_value           REAL,
    post_at              TEXT,
    reason               TEXT NOT NULL DEFAULT '',
    forced_off           INTEGER NOT NULL DEFAULT 0,
    metadata             TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_actuation_zone_ts ON actuation (zone_id, ts);
