-- Applied on every startup; every statement must be idempotent.

CREATE TABLE IF NOT EXISTS projects (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    active_version_id TEXT,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    source_url    TEXT,
    mime          TEXT NOT NULL,
    raw_path      TEXT NOT NULL,
    content_sha   TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'uploaded',   -- uploaded | indexed | failed
    error         TEXT,
    parse_quality TEXT,                               -- JSON, from the active build's parser
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_documents_project ON documents(project_id);

-- Immutable. An edit inserts a new row.
CREATE TABLE IF NOT EXISTS pipeline_versions (
    id                TEXT PRIMARY KEY,
    project_id        TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version           INTEGER NOT NULL,
    config            TEXT NOT NULL,                  -- JSON pipeline document
    index_config_hash TEXT NOT NULL,                  -- hash of rebuild-effect fields only
    parent_id         TEXT,
    note              TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL,
    UNIQUE (project_id, version)
);

-- One build per (project, index config). Versions differing only in
-- instant-effect params share a build. A build is synced to the current corpus.
CREATE TABLE IF NOT EXISTS index_builds (
    id                TEXT PRIMARY KEY,
    project_id        TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    index_config_hash TEXT NOT NULL,
    config            TEXT NOT NULL,                  -- JSON of the rebuild-effect slots
    store_type        TEXT NOT NULL,
    store_path        TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending', -- pending | building | ready | failed
    dim               INTEGER,
    chunk_count       INTEGER NOT NULL DEFAULT 0,
    error             TEXT,
    stats             TEXT,                           -- JSON: cache hits, timings
    started_at        TEXT,
    finished_at       TEXT,
    UNIQUE (project_id, index_config_hash)
);

CREATE TABLE IF NOT EXISTS build_documents (
    build_id    TEXT NOT NULL REFERENCES index_builds(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error       TEXT,                                 -- set if this build couldn't index the doc
    PRIMARY KEY (build_id, document_id)
);

CREATE TABLE IF NOT EXISTS chunks (
    id           TEXT PRIMARY KEY,
    build_id     TEXT NOT NULL REFERENCES index_builds(id) ON DELETE CASCADE,
    document_id  TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal      INTEGER NOT NULL,
    text         TEXT NOT NULL,
    text_sha     TEXT NOT NULL,
    token_count  INTEGER NOT NULL,
    is_table     INTEGER NOT NULL DEFAULT 0,
    page_start   INTEGER,
    page_end     INTEGER,
    heading_path TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_chunks_build_doc ON chunks(build_id, document_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    chunk_id UNINDEXED,
    build_id UNINDEXED,
    document_id UNINDEXED
);

-- Exact-match lookup for error messages and code symbols.
CREATE TABLE IF NOT EXISTS lookup_index (
    build_id    TEXT NOT NULL,
    chunk_id    TEXT NOT NULL,
    document_id TEXT NOT NULL,
    kind        TEXT NOT NULL,                        -- signature | symbol
    key         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_lookup_key ON lookup_index(build_id, key);
CREATE INDEX IF NOT EXISTS ix_lookup_doc ON lookup_index(build_id, document_id);

-- Content-addressed: switching vector store or rebuilding never re-embeds.
CREATE TABLE IF NOT EXISTS vector_cache (
    text_sha  TEXT NOT NULL,
    embed_key TEXT NOT NULL,
    dim       INTEGER NOT NULL,
    vector    BLOB NOT NULL,
    PRIMARY KEY (text_sha, embed_key)
);

CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id  TEXT,
    build_id    TEXT,
    kind        TEXT NOT NULL DEFAULT 'chat',
    question    TEXT NOT NULL DEFAULT '',
    answer      TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'running',       -- running | ok | error | aborted
    error       TEXT,
    latency_ms  REAL NOT NULL DEFAULT 0,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    cost_usd    REAL NOT NULL DEFAULT 0,
    result      TEXT,                                 -- JSON: retrieved, citations
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_runs_project ON runs(project_id, created_at);

CREATE TABLE IF NOT EXISTS trace_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq        INTEGER NOT NULL,
    step       TEXT NOT NULL,
    ms         REAL NOT NULL DEFAULT 0,
    tokens_in  INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    cost_usd   REAL NOT NULL DEFAULT 0,
    payload    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_trace_run ON trace_events(run_id, seq);
