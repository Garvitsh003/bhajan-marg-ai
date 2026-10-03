-- Bhajan Marg AI V1 product database schema.
-- Designed for ordinary PostgreSQL / Neon with no provider-specific extensions or RLS.

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    email VARCHAR(320) NOT NULL UNIQUE,
    password_hash TEXT,
    google_sub VARCHAR(255) UNIQUE,
    avatar_url TEXT,
    preferred_language VARCHAR(16) NOT NULL DEFAULT 'auto'
        CHECK (preferred_language IN ('auto', 'hi', 'hinglish', 'en')),
    theme VARCHAR(16) NOT NULL DEFAULT 'system'
        CHECK (theme IN ('system', 'light', 'dark')),
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active DESC);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    user_agent TEXT,
    ip_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id, expires_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_active ON auth_sessions(expires_at) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_password_reset_user ON password_reset_tokens(user_id, expires_at DESC);

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(160) NOT NULL DEFAULT 'New chat',
    preferred_language VARCHAR(16) NOT NULL DEFAULT 'auto'
        CHECK (preferred_language IN ('auto', 'hi', 'hinglish', 'en')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_message_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_recent
    ON conversations(user_id, last_message_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    standalone_query TEXT,
    evidence_level VARCHAR(32),
    evidence_reason TEXT,
    answer_status VARCHAR(64),
    extraction_status VARCHAR(64),
    interpretation_status VARCHAR(64),
    response_language VARCHAR(16),
    request_id VARCHAR(128),
    elapsed_ms INTEGER,
    quotes JSONB NOT NULL DEFAULT '[]'::jsonb,
    claims JSONB NOT NULL DEFAULT '[]'::jsonb,
    question_snapshot TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_messages_request_id ON messages(request_id) WHERE request_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS message_sources (
    id UUID PRIMARY KEY,
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    source_index INTEGER NOT NULL DEFAULT 0,
    video_id VARCHAR(64),
    video_title TEXT,
    url TEXT,
    answer_url TEXT,
    timestamp_start_ms BIGINT,
    timestamp_end_ms BIGINT,
    timestamp_start VARCHAR(32),
    timestamp_end VARCHAR(32),
    transcript_chunk_id TEXT,
    transcript_excerpt TEXT,
    relevance DOUBLE PRECISION,
    source_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_message_sources_message
    ON message_sources(message_id, source_index ASC);
CREATE INDEX IF NOT EXISTS idx_message_sources_video ON message_sources(video_id);

CREATE TABLE IF NOT EXISTS feedback (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    guest_id VARCHAR(128),
    conversation_id UUID,
    message_id UUID,
    question TEXT NOT NULL DEFAULT '',
    answer TEXT NOT NULL DEFAULT '',
    retrieved_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    rating SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
    reason VARCHAR(80),
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating, created_at DESC);

CREATE TABLE IF NOT EXISTS analytics_events (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    guest_id VARCHAR(128),
    conversation_id UUID,
    event_name VARCHAR(100) NOT NULL,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_name_time
    ON analytics_events(event_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_user_time
    ON analytics_events(user_id, created_at DESC) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_analytics_guest_time
    ON analytics_events(guest_id, created_at DESC) WHERE guest_id IS NOT NULL;
