-- AITravelMate (Nón AI) — MVP schema
-- Structured data only. Vector data (item embeddings, scam pattern embeddings) lives in Qdrant;
-- rows here are looked up by id from Qdrant payloads. Do not duplicate vectors here.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Onboarding session: language + nationality kept separate (see doc section 4/8)
CREATE TABLE IF NOT EXISTS sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    native_language TEXT NOT NULL,
    nationality     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Simple zone lookup: city + zone_name + center point + radius (no PostGIS, see section 2)
CREATE TABLE IF NOT EXISTS geo_regions (
    id          SERIAL PRIMARY KEY,
    city        TEXT NOT NULL,
    zone_name   TEXT NOT NULL,
    center_lat  DOUBLE PRECISION NOT NULL,
    center_lon  DOUBLE PRECISION NOT NULL,
    radius_km   DOUBLE PRECISION NOT NULL DEFAULT 3.0,
    UNIQUE (city, zone_name)
);

-- Price references for Bayesian fusion (doc section 6.1).
-- One row per (item_name, region, category). Qdrant collection `item_names` holds the
-- embedding + payload {region, category, postgres_id} pointing back to this table's id.
CREATE TABLE IF NOT EXISTS price_references (
    id           SERIAL PRIMARY KEY,
    item_name    TEXT NOT NULL,
    region       TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT 'general', -- e.g. food, retail, xich_lo, boat
    mu_post      DOUBLE PRECISION,                -- posterior mean in log-space
    tau_post     DOUBLE PRECISION,                -- posterior variance in log-space
    sigma_data   DOUBLE PRECISION NOT NULL DEFAULT 0.3, -- assumed observation noise in log-space
    n            INTEGER NOT NULL DEFAULT 0,      -- number of real observed data points folded in
    sum_y        DOUBLE PRECISION NOT NULL DEFAULT 0,   -- running sum of ln(price), for online mean update
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_price_references_region ON price_references (region);

CREATE TABLE IF NOT EXISTS emergency_hotlines (
    id           SERIAL PRIMARY KEY,
    region       TEXT NOT NULL,
    service_type TEXT NOT NULL, -- police, medical, tourist_police, fire
    phone_number TEXT NOT NULL,
    notes        TEXT
);
CREATE INDEX IF NOT EXISTS idx_emergency_hotlines_region ON emergency_hotlines (region);

CREATE TABLE IF NOT EXISTS embassies (
    id           SERIAL PRIMARY KEY,
    nationality  TEXT NOT NULL, -- keyed by nationality, not language (see doc section 4/8)
    country_name TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    address      TEXT,
    region_hint  TEXT -- nearest city, for display only
);
CREATE INDEX IF NOT EXISTS idx_embassies_nationality ON embassies (nationality);

-- Seed data: adjust for Hanoi / Sapa / Hoi An MVP locations.
INSERT INTO geo_regions (city, zone_name, center_lat, center_lon, radius_km) VALUES
    ('Hanoi', 'Old Quarter', 21.0333, 105.8500, 2.0),
    ('Sapa', 'Town Center', 22.3364, 103.8438, 3.0),
    ('Hoi An', 'Ancient Town', 15.8801, 108.3380, 2.0)
ON CONFLICT DO NOTHING;
