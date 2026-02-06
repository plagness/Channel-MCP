CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS channels (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    title TEXT,
    description TEXT,
    category TEXT,
    is_private BOOLEAN DEFAULT FALSE,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    last_fetched_at TIMESTAMPTZ,
    last_message_id BIGINT,
    tags_json JSONB,
    code_json JSONB,
    ad_score REAL,
    usefulness_avg REAL,
    is_ad_channel BOOLEAN DEFAULT FALSE,
    last_profiled_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    message_id BIGINT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    date DATE NOT NULL,
    permalink TEXT,
    content TEXT NOT NULL,
    content_hash VARCHAR(64),
    word_count INTEGER,
    views INTEGER,
    forwards INTEGER,
    emoji_line TEXT,
    emoji_json JSONB,
    code_json JSONB,
    raw_json JSONB,
    tags_processed BOOLEAN DEFAULT FALSE,
    embedding_processed BOOLEAN DEFAULT FALSE,
    tag_attempts INTEGER DEFAULT 0,
    embedding_attempts INTEGER DEFAULT 0,
    last_tag_error TEXT,
    last_embedding_error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(channel_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel_id, date);
CREATE INDEX IF NOT EXISTS idx_messages_tags_pending ON messages(tags_processed) WHERE NOT tags_processed;
CREATE INDEX IF NOT EXISTS idx_messages_embedding_pending ON messages(embedding_processed) WHERE NOT embedding_processed;

CREATE TABLE IF NOT EXISTS tags (
    id SERIAL PRIMARY KEY,
    canonical TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tag_aliases (
    id SERIAL PRIMARY KEY,
    alias TEXT UNIQUE NOT NULL,
    canonical TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tag_aliases_canonical ON tag_aliases(canonical);

CREATE TABLE IF NOT EXISTS message_tags (
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    source VARCHAR(20) DEFAULT 'ollama',
    confidence REAL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (message_id, tag_id)
);

CREATE TABLE IF NOT EXISTS embeddings (
    message_id INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    embedding vector(768) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Optional index for larger datasets (enable when needed)
-- CREATE INDEX embeddings_idx ON embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

INSERT INTO tag_aliases (alias, canonical) VALUES
    ('Центральный банк', 'ЦБ'),
    ('Центральный Банк', 'ЦБ'),
    ('Central Bank', 'ЦБ'),
    ('Central Bank of Russia', 'ЦБ'),
    ('T-Technologies', 'Т-Технологии'),
    ('T‑Technologies', 'Т-Технологии')
ON CONFLICT DO NOTHING;
