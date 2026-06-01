-- ============================================================
-- Nawy Scraper — PostgreSQL Schema
-- Run this once before the first scrape:
--   psql -U youruser -d nawy_db -f schema.sql
-- ============================================================

CREATE TABLE IF NOT EXISTS developers (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    slug            TEXT UNIQUE NOT NULL,
    url             TEXT NOT NULL,
    scraped_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Compounds (both parent projects and phases) ───────────────────────────────
-- is_phase = FALSE  →  this is a standalone project or a parent compound
-- is_phase = TRUE   →  this is a phase; parent_compound_id points to the parent
CREATE TABLE IF NOT EXISTS compounds (
    id                      INTEGER PRIMARY KEY,
    name                    TEXT NOT NULL,
    slug                    TEXT UNIQUE NOT NULL,
    url                     TEXT NOT NULL,
    developer_id            INTEGER REFERENCES developers(id),
    developer_name          TEXT,
    area                    TEXT,
    is_phase                BOOLEAN DEFAULT FALSE,
    parent_compound_id      INTEGER,          -- FK to compounds(id), NULL if not a phase
    parent_compound_name    TEXT,
    scraped_at              TIMESTAMPTZ DEFAULT NOW()
);

-- Self-referencing FK added after table creation (avoids circular dependency)
ALTER TABLE compounds
    ADD CONSTRAINT fk_parent_compound
    FOREIGN KEY (parent_compound_id) REFERENCES compounds(id)
    NOT VALID;   -- NOT VALID skips checking existing rows (safe for inserts)

-- ── Units ─────────────────────────────────────────────────────────────────────
-- has_phases = TRUE means the parent project has phases and this unit belongs
-- to one of them. phase_compound_id / phase_name will be populated.
-- has_phases = FALSE means the project has no phases; phase_* columns are NULL.
-- This makes it unambiguous to filter: WHERE NOT has_phases

CREATE TABLE IF NOT EXISTS units (
    id                      SERIAL PRIMARY KEY,

    -- Parent project
    compound_id             INTEGER NOT NULL REFERENCES compounds(id),
    compound_name           TEXT NOT NULL,

    -- Developer
    developer_id            INTEGER REFERENCES developers(id),
    developer_name          TEXT,

    -- Phase (NULL when project has no phases)
    phase_compound_id       INTEGER,
    phase_name              TEXT,
    has_phases              BOOLEAN NOT NULL DEFAULT FALSE,

    -- Unit specs
    unit_type               TEXT,            -- Apartment, Villa, Townhouse, …
    bedrooms                INTEGER,
    bathrooms               INTEGER,
    area_sqm                NUMERIC(10,2),   -- built-up area in square metres

    -- Pricing
    price                   NUMERIC(18,2),
    currency                VARCHAR(10),     -- EGP, USD, EUR, AED, SAR …

    -- Payment plan
    down_payment_pct        NUMERIC(6,2),    -- e.g. 1.5 means 1.5%
    installment_years       INTEGER,
    installment_plan_desc   TEXT,            -- full description if structured parse fails

    -- Source
    unit_url                TEXT,
    nawy_unit_id            TEXT UNIQUE,     -- Nawy's own numeric ID from URL

    scraped_at              TIMESTAMPTZ DEFAULT NOW()
);

-- ── Useful indexes ────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_units_developer   ON units(developer_id);
CREATE INDEX IF NOT EXISTS idx_units_compound    ON units(compound_id);
CREATE INDEX IF NOT EXISTS idx_units_currency    ON units(currency);
CREATE INDEX IF NOT EXISTS idx_units_has_phases  ON units(has_phases);
CREATE INDEX IF NOT EXISTS idx_units_price       ON units(price, currency);
CREATE INDEX IF NOT EXISTS idx_compounds_dev     ON compounds(developer_id);
CREATE INDEX IF NOT EXISTS idx_compounds_phase   ON compounds(is_phase, parent_compound_id);

-- ── Handy views ───────────────────────────────────────────────────────────────

-- Full flat view: developer → project → phase → unit
CREATE OR REPLACE VIEW v_full_listing AS
SELECT
    d.name                          AS developer,
    c.name                          AS project,
    CASE WHEN u.has_phases THEN u.phase_name ELSE '(no phases)' END
                                    AS phase,
    u.has_phases,
    u.unit_type,
    u.bedrooms,
    u.bathrooms,
    u.area_sqm,
    u.price,
    u.currency,
    u.down_payment_pct,
    u.installment_years,
    u.unit_url,
    u.scraped_at
FROM units u
JOIN compounds c  ON u.compound_id  = c.id
JOIN developers d ON u.developer_id = d.id;

-- Projects without phases
CREATE OR REPLACE VIEW v_projects_no_phases AS
SELECT DISTINCT c.name AS project, d.name AS developer, c.url
FROM compounds c
JOIN developers d ON c.developer_id = d.id
WHERE c.is_phase = FALSE
  AND c.id NOT IN (
      SELECT DISTINCT parent_compound_id
      FROM compounds
      WHERE parent_compound_id IS NOT NULL
  )
ORDER BY d.name, c.name;
