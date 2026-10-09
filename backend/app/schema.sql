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

-- Document metadata for smart auto-configuration recommendations
CREATE TABLE IF NOT EXISTS document_metadata (
    id                    TEXT PRIMARY KEY,
    document_id           TEXT NOT NULL UNIQUE REFERENCES documents(id) ON DELETE CASCADE,
    project_id            TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    metadata              TEXT NOT NULL,               -- JSON: DocumentMetadata fields
    created_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_document_metadata_project ON document_metadata(project_id);

-- User-facing document facts (PRD FR-2.30): OKF fields from Markdown front matter or the
-- Documents tab, and the source's last-modified date. Separate from document_metadata, which
-- the builder overwrites on every parse. Not part of any index config: edits never rebuild.
CREATE TABLE IF NOT EXISTS document_okf (
    document_id   TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    metadata      TEXT NOT NULL DEFAULT '{}',          -- JSON: status, stale_after, verified, sources
    last_modified TEXT                                 -- ISO datetime (upload File.lastModified / HTTP Last-Modified)
);

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

-- Append-only log of which version became active, and when.
CREATE TABLE IF NOT EXISTS version_activations (
    id                  TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id          TEXT NOT NULL REFERENCES pipeline_versions(id) ON DELETE CASCADE,
    previous_version_id TEXT,                         -- NULL for a project's first version
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_version_activations_version ON version_activations(version_id);

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
    source      TEXT,                                 -- chat: playground | api (FR-3.22)
    api_key_id  TEXT,                                 -- the key a remote caller used (FR-3.23)
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
    payload    TEXT NOT NULL DEFAULT '{}',
    start_ms   REAL                       -- offset from run start; NULL on runs recorded before it existed
);
CREATE INDEX IF NOT EXISTS ix_trace_run ON trace_events(run_id, seq);

-- Semantic answer cache (cache slot). One row per answered question; a hit must share the
-- scope (project + answer-relevant config + corpus contents), so edits never serve stale answers.
CREATE TABLE IF NOT EXISTS answer_cache (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    scope_key  TEXT NOT NULL,
    question   TEXT NOT NULL,
    guard      TEXT NOT NULL,   -- JSON: numbers/identifiers that must match exactly
    vector     BLOB NOT NULL,   -- float32 question embedding (the project's embedder)
    answer     TEXT NOT NULL,
    result     TEXT NOT NULL,   -- JSON: citations, retrieved
    run_id     TEXT,
    hits       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_answer_cache_scope ON answer_cache(project_id, scope_key, created_at);

-- Domain embedding adapters (FR-3.10): a query-side matrix per training, stored as
-- data/adapters/<project>/<id>.npy and bound to the embedder (embed_key) it was trained for.
CREATE TABLE IF NOT EXISTS adapters (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id  TEXT,
    eval_set_id TEXT,
    build_id    TEXT,
    embed_key   TEXT,
    dim         INTEGER,
    status      TEXT NOT NULL DEFAULT 'running',   -- running | ready | failed
    metrics     TEXT,                              -- JSON: holdout/full before-after, params
    error       TEXT,
    created_at  TEXT NOT NULL
);

-- Prompt optimisation runs (FR-3.11): candidates scored on val, before/after on test.
CREATE TABLE IF NOT EXISTS prompt_runs (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id  TEXT,
    eval_set_id TEXT,
    status      TEXT NOT NULL DEFAULT 'running',   -- running | ready | failed
    result      TEXT,                              -- JSON
    error       TEXT,
    created_at  TEXT NOT NULL
);

-- Attested computations (FR-3.21): sanctioned read-only queries over the project's data tables
-- (data/compute/<project>.db), each with declarative attestation checks.
CREATE TABLE IF NOT EXISTS computations (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    spec       TEXT NOT NULL,   -- JSON: engine.compute.Computation
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Production query loop (FR-3.22): automatic Corpus Health reports after N new real questions.
CREATE TABLE IF NOT EXISTS health_monitors (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    settings   TEXT NOT NULL,   -- JSON: engine.monitor.MonitorSettings
    updated_at TEXT NOT NULL
);

-- API keys (FR-3.23): only the SHA-256 is stored; `prefix` (first 9 chars) finds the row.
CREATE TABLE IF NOT EXISTS api_keys (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    scope        TEXT NOT NULL,          -- chat (one project's chat endpoint) | admin
    project_id   TEXT REFERENCES projects(id) ON DELETE CASCADE,
    prefix       TEXT NOT NULL,
    key_hash     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_api_keys_prefix ON api_keys(prefix);

-- Recipe gallery (FR-3.26): saved pipeline configurations (built-in recipes live in code).
CREATE TABLE IF NOT EXISTS recipes (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    tags           TEXT NOT NULL DEFAULT '[]',
    config         TEXT NOT NULL,
    source_project TEXT,          -- where it was saved from (none when imported from a link)
    created_at     TEXT NOT NULL
);

-- Injection-resistance tests (FR-3.7/3.8): canary payloads injected into retrieval, per defence variant.
CREATE TABLE IF NOT EXISTS injection_runs (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id  TEXT,
    eval_set_id TEXT,
    status      TEXT NOT NULL DEFAULT 'running',   -- running | ready | failed
    options     TEXT NOT NULL DEFAULT '{}',        -- JSON: {questions, compare}
    metrics     TEXT,                              -- JSON: per variant score + outcome counts
    results     TEXT,                              -- JSON: one row per trial
    error       TEXT,
    created_at  TEXT NOT NULL
);

-- Auto-generated eval sets. Gold labels are build-independent (document + evidence
-- quote), so one set scores any pipeline version.
CREATE TABLE IF NOT EXISTS eval_sets (
    id             TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id     TEXT,
    build_id       TEXT,
    status         TEXT NOT NULL DEFAULT 'running',   -- running | ready | failed
    size_requested INTEGER NOT NULL,
    stats          TEXT,                              -- JSON
    error          TEXT,
    created_at     TEXT NOT NULL,
    revision       INTEGER NOT NULL DEFAULT 0,        -- +1 on every hand edit / import (FR-2.5)
    corpus_sha     TEXT                               -- sha256 of sorted document content hashes at generation
);
CREATE INDEX IF NOT EXISTS ix_eval_sets_project ON eval_sets(project_id, created_at);

CREATE TABLE IF NOT EXISTS eval_items (
    id                 TEXT PRIMARY KEY,
    eval_set_id        TEXT NOT NULL REFERENCES eval_sets(id) ON DELETE CASCADE,
    ordinal            INTEGER NOT NULL,
    question           TEXT NOT NULL,
    gold_answer        TEXT NOT NULL,
    evidence           TEXT NOT NULL,
    document_id        TEXT NOT NULL,
    gold_chunk_id      TEXT NOT NULL,
    valid              INTEGER NOT NULL DEFAULT 1,
    reject_reason      TEXT,
    closed_book_answer TEXT,
    facets             TEXT,                          -- JSON list of required facts (FR-2.6)
    tests              TEXT                           -- Python asserts the answer's code must pass (FR-3.17)
);
CREATE INDEX IF NOT EXISTS ix_eval_items_set ON eval_items(eval_set_id, ordinal);

CREATE TABLE IF NOT EXISTS eval_runs (
    id          TEXT PRIMARY KEY,
    eval_set_id TEXT NOT NULL REFERENCES eval_sets(id) ON DELETE CASCADE,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id  TEXT NOT NULL,
    build_id    TEXT,
    status      TEXT NOT NULL DEFAULT 'running',      -- running | ready | failed
    metrics     TEXT,                                 -- JSON
    results     TEXT,                                 -- JSON: per-item rank/diagnosis
    error       TEXT,
    created_at  TEXT NOT NULL,
    set_revision INTEGER                              -- eval_sets.revision this run scored
);
CREATE INDEX IF NOT EXISTS ix_eval_runs_set ON eval_runs(eval_set_id, created_at);

-- Config sweeps: one eval set scored across a grid of variants of a base version.
-- Cells live as JSON (one writer: the sweep job); a cell becomes a real
-- pipeline version only when the user promotes it.
CREATE TABLE IF NOT EXISTS sweeps (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    eval_set_id     TEXT NOT NULL REFERENCES eval_sets(id) ON DELETE CASCADE,
    base_version_id TEXT NOT NULL,
    axes            TEXT NOT NULL,                     -- JSON [{path, values}]
    cells           TEXT NOT NULL,                     -- JSON [{overrides, config, status, metrics, error, pareto}]
    status          TEXT NOT NULL DEFAULT 'running',   -- running | ready | failed | cancelled
    error           TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sweeps_project ON sweeps(project_id, created_at);

-- Corpus Health reports: coverage gaps from real questions, duplicate/contradicting
-- passages, unused content. The whole report is one JSON result (one writer: the job).
CREATE TABLE IF NOT EXISTS corpus_reports (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id  TEXT NOT NULL,
    build_id    TEXT,
    questions   TEXT NOT NULL DEFAULT '[]',           -- JSON: pasted questions
    status      TEXT NOT NULL DEFAULT 'running',      -- running | ready | failed
    result      TEXT,                                 -- JSON: coverage, duplicates, contradictions, usage
    error       TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_corpus_reports_project ON corpus_reports(project_id, created_at);

-- Config-prior instrumentation (PRD FR-2.35): one anonymised row per finished sweep —
-- corpus fingerprint (aggregate numbers only, no names or text) -> winning settings -> score.
-- No project id / FK on purpose: rows outlive the project. Nothing reads them yet.
CREATE TABLE IF NOT EXISTS sweep_fingerprints (
    id          TEXT PRIMARY KEY,
    sweep_id    TEXT NOT NULL,
    fingerprint TEXT NOT NULL,                        -- JSON
    axes        TEXT NOT NULL,                        -- JSON: swept paths
    winner      TEXT NOT NULL,                        -- JSON: overrides + config summary
    score       TEXT NOT NULL,                        -- JSON: winner + runner-up metrics
    n_cells     INTEGER NOT NULL,
    n_questions INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);

-- Generate-slot LLM providers added or edited in Settings → Providers. A row named after a
-- built-in preset overrides that preset's fields; any other row is a custom
-- OpenAI-compatible endpoint. Empty/NULL columns mean "inherit".
-- api_key and headers are AES-256-GCM ciphertext ("enc:v1:…", see app/vault.py); the
-- master key lives outside the data directory.
CREATE TABLE IF NOT EXISTS llm_providers (
    name                TEXT PRIMARY KEY,
    title               TEXT NOT NULL DEFAULT '',
    base_url            TEXT NOT NULL DEFAULT '',
    api_key             TEXT NOT NULL DEFAULT '',     -- encrypted
    default_model       TEXT NOT NULL DEFAULT '',
    supports_reasoning  INTEGER,                      -- NULL = inherit
    key_required        INTEGER,                      -- NULL = inherit
    headers             TEXT NOT NULL DEFAULT '{}',   -- encrypted JSON of extra HTTP headers
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- A RAG system that runs elsewhere (PRD §8.7). Its id goes in eval_runs.version_id, so runs,
-- the leaderboard and regression history treat it like a version. Headers are vault-encrypted.
CREATE TABLE IF NOT EXISTS external_systems (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    config     TEXT NOT NULL,                         -- JSON ExternalConfig minus headers
    headers    TEXT NOT NULL DEFAULT '',              -- vault token of the JSON headers
    created_at TEXT NOT NULL
);

-- OpenTelemetry spans an external system exported to /api/otel/v1/traces (FR-4.7). Joined to eval results by the
-- trace id we sent in `traceparent`; pruned after 30 days (engine/otel.py).
CREATE TABLE IF NOT EXISTS external_spans (
    trace_id    TEXT NOT NULL,
    span_id     TEXT NOT NULL,
    parent_id   TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL,
    start_ns    INTEGER NOT NULL,
    end_ns      INTEGER NOT NULL,
    attrs       TEXT NOT NULL DEFAULT '{}',
    received_at TEXT NOT NULL,
    PRIMARY KEY (trace_id, span_id)
);
CREATE INDEX IF NOT EXISTS idx_external_spans_received ON external_spans(received_at);
