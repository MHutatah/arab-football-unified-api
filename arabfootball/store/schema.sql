-- Arab Football Unified API — canonical schema.
--
-- Portable across Postgres (producer) and SQLite (published snapshot): no
-- vendor-specific types, TEXT ids, ISO-8601 date strings.
--
-- Identity is a LANGUAGE-NEUTRAL id. Names are labels, never keys: `name_ar`
-- and `name_en` are both carried and either may be absent. Every provider's own
-- id/spelling lives in `aliases`, so resolution never depends on a name match.

-- ── identity ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,           -- language-neutral, e.g. "team:0001"
    type        TEXT NOT NULL,              -- team|player|competition|manager|venue
    name_ar     TEXT,
    name_en     TEXT,
    country     TEXT,                       -- ISO-3166 alpha-2 (SA, QA, AE, EG…)
    meta        TEXT,                       -- JSON: team{founded,stadium} player{dob,position,foot,number}
    provisional INTEGER NOT NULL DEFAULT 0, -- 1 = auto-created, awaiting review
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entities_type_country ON entities(type, country);

-- Every provider id and every spelling we've ever seen for an entity.
CREATE TABLE IF NOT EXISTS aliases (
    entity_id    TEXT NOT NULL REFERENCES entities(id),
    provider     TEXT NOT NULL,             -- 365scores|api_football|espn|wikipedia|manual
    provider_id  TEXT,                      -- the provider's own id (NULL for name-only aliases)
    name_variant TEXT NOT NULL,
    script       TEXT,                      -- ar|en
    UNIQUE (provider, provider_id, name_variant)
);
CREATE INDEX IF NOT EXISTS idx_aliases_entity ON aliases(entity_id);
CREATE INDEX IF NOT EXISTS idx_aliases_lookup ON aliases(provider, provider_id);

-- ── the archive ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS matches (
    id             TEXT PRIMARY KEY,
    competition_id TEXT REFERENCES entities(id),
    season         TEXT,
    round          TEXT,
    home_entity    TEXT NOT NULL REFERENCES entities(id),
    away_entity    TEXT NOT NULL REFERENCES entities(id),
    kickoff_utc    TEXT NOT NULL,           -- ISO-8601
    venue_id       TEXT REFERENCES entities(id),
    status         TEXT NOT NULL,           -- scheduled|live|finished
    home_score     INTEGER,
    away_score     INTEGER,
    provider_ids   TEXT,                    -- JSON {provider: id}
    last_synced    TEXT
);
CREATE INDEX IF NOT EXISTS idx_matches_comp_season ON matches(competition_id, season);
CREATE INDEX IF NOT EXISTS idx_matches_kickoff ON matches(kickoff_utc);
CREATE INDEX IF NOT EXISTS idx_matches_home ON matches(home_entity);
CREATE INDEX IF NOT EXISTS idx_matches_away ON matches(away_entity);

-- The spine: "player X played for team Y in match Z". Careers, squads and
-- per-season stats are DERIVED from this — never fetched from a gated endpoint.
CREATE TABLE IF NOT EXISTS appearances (
    player_entity TEXT NOT NULL REFERENCES entities(id),
    match_id      TEXT NOT NULL REFERENCES matches(id),
    team_entity   TEXT NOT NULL REFERENCES entities(id),
    started       INTEGER,
    minutes       INTEGER,
    goals         INTEGER DEFAULT 0,
    assists       INTEGER DEFAULT 0,
    yellow        INTEGER DEFAULT 0,
    red           INTEGER DEFAULT 0,
    PRIMARY KEY (player_entity, match_id)
);
CREATE INDEX IF NOT EXISTS idx_appearances_player ON appearances(player_entity);
CREATE INDEX IF NOT EXISTS idx_appearances_team ON appearances(team_entity);

CREATE TABLE IF NOT EXISTS team_seasons (
    team_entity    TEXT NOT NULL REFERENCES entities(id),
    competition_id TEXT NOT NULL REFERENCES entities(id),
    season         TEXT NOT NULL,
    played INTEGER, wins INTEGER, draws INTEGER, losses INTEGER,
    goals_for INTEGER, goals_against INTEGER, points INTEGER, position INTEGER,
    PRIMARY KEY (team_entity, competition_id, season)
);

CREATE TABLE IF NOT EXISTS transfers (
    id            TEXT PRIMARY KEY,
    player_entity TEXT NOT NULL REFERENCES entities(id),
    from_entity   TEXT REFERENCES entities(id),
    to_entity     TEXT REFERENCES entities(id),
    date          TEXT,
    fee_eur       INTEGER,
    type          TEXT,                     -- permanent|loan|free|end_of_loan
    source        TEXT,
    -- Licensing tier of the SOURCE this row came from (see docs/sources.md):
    --   'publishable' = Tier A, exported in the snapshot
    --   'reference'   = Tier B, unstated-licence source; kept for discovery and
    --                   cross-checking, EXCLUDED from every export until an
    --                   independent Tier-A/live source corroborates it
    tier          TEXT NOT NULL DEFAULT 'publishable',
    corroborated_by TEXT,                   -- the source that promoted a reference row
    confidence    REAL
);
CREATE INDEX IF NOT EXISTS idx_transfers_player ON transfers(player_entity);
CREATE INDEX IF NOT EXISTS idx_transfers_tier ON transfers(tier);

CREATE TABLE IF NOT EXISTS honours (
    entity_id      TEXT NOT NULL REFERENCES entities(id),
    competition_id TEXT NOT NULL REFERENCES entities(id),
    season         TEXT NOT NULL,
    result         TEXT NOT NULL,           -- winner|runner_up
    PRIMARY KEY (entity_id, competition_id, season, result)
);

-- ── enrichment ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS facts (
    id                TEXT PRIMARY KEY,
    kind              TEXT NOT NULL,        -- transfer|injury|suspension|form|news
    subject_entity    TEXT REFERENCES entities(id),
    related_entities  TEXT,                 -- JSON [entity_id]
    text_ar           TEXT,
    text_en           TEXT,
    value             TEXT,                 -- JSON, kind-specific
    source            TEXT,
    source_url        TEXT,
    published_at      TEXT,
    confidence        REAL,
    extracted_by      TEXT                  -- model/pipeline id
);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject_entity, kind);

-- ── observability ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS source_runs (
    id          TEXT PRIMARY KEY,
    collector   TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT,                       -- ok|partial|failed
    inserted    INTEGER DEFAULT 0,
    updated     INTEGER DEFAULT 0,
    errors      TEXT
);

-- Snapshot provenance: stamped into every published DB so a consumer knows
-- exactly what they hold.
CREATE TABLE IF NOT EXISTS snapshot_meta (
    key   TEXT PRIMARY KEY,                 -- version|generated_at|license|coverage|counts
    value TEXT
);
