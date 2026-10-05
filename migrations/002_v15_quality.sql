-- V1.5 Premanand Ji Mastery: quality cases, feedback traceability and regression data.
-- Idempotent so existing Neon deployments can self-upgrade at startup.

ALTER TABLE feedback
    ADD COLUMN IF NOT EXISTS request_id VARCHAR(128);

ALTER TABLE feedback
    ADD COLUMN IF NOT EXISTS client_feedback_id UUID;

ALTER TABLE feedback
    ADD COLUMN IF NOT EXISTS voice_transcript TEXT;

ALTER TABLE feedback
    ADD COLUMN IF NOT EXISTS client_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_feedback_request_id
    ON feedback(request_id)
    WHERE request_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_client_id
    ON feedback(client_feedback_id)
    WHERE client_feedback_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS quality_cases (
    id UUID PRIMARY KEY,
    request_id VARCHAR(128) NOT NULL UNIQUE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    guest_id VARCHAR(128),
    conversation_id UUID,
    message_id UUID,
    feedback_id UUID,

    question TEXT NOT NULL,
    standalone_query TEXT,
    response_language VARCHAR(16),

    answer TEXT NOT NULL DEFAULT '',
    evidence_level VARCHAR(32),
    evidence_reason TEXT,
    answer_status VARCHAR(64),
    extraction_status VARCHAR(64),
    interpretation_status VARCHAR(64),

    search_queries JSONB NOT NULL DEFAULT '[]'::jsonb,
    retrieval_trace JSONB NOT NULL DEFAULT '{}'::jsonb,
    sources_shown JSONB NOT NULL DEFAULT '[]'::jsonb,
    answer_trace JSONB NOT NULL DEFAULT '{}'::jsonb,
    versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    timing JSONB NOT NULL DEFAULT '{}'::jsonb,

    feedback_rating SMALLINT CHECK (feedback_rating IN (-1, 1)),
    feedback_reason VARCHAR(80),
    feedback_comment TEXT,
    voice_transcript TEXT,

    review_status VARCHAR(32) NOT NULL DEFAULT 'unreviewed'
        CHECK (review_status IN ('unreviewed','needs_review','reviewed','resolved')),
    failure_category VARCHAR(64),
    review_notes TEXT,
    expected_sources JSONB NOT NULL DEFAULT '[]'::jsonb,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quality_cases_created
    ON quality_cases(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quality_cases_status
    ON quality_cases(review_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quality_cases_feedback
    ON quality_cases(feedback_rating, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quality_cases_language
    ON quality_cases(response_language, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quality_cases_failure
    ON quality_cases(failure_category, created_at DESC)
    WHERE failure_category IS NOT NULL;

CREATE TABLE IF NOT EXISTS golden_cases (
    id UUID PRIMARY KEY,
    quality_case_id UUID REFERENCES quality_cases(id) ON DELETE SET NULL,
    question TEXT NOT NULL,
    language VARCHAR(16),
    expected_topic TEXT,
    expected_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    acceptable_answer JSONB NOT NULL DEFAULT '[]'::jsonb,
    unacceptable_behavior JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_golden_cases_active
    ON golden_cases(active, created_at DESC);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    id UUID PRIMARY KEY,
    label VARCHAR(160) NOT NULL,
    versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evaluation_results (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,
    golden_case_id UUID NOT NULL REFERENCES golden_cases(id) ON DELETE CASCADE,
    retrieval_score SMALLINT CHECK (retrieval_score BETWEEN 0 AND 2),
    answer_score SMALLINT CHECK (answer_score BETWEEN 0 AND 2),
    citation_score SMALLINT CHECK (citation_score BETWEEN 0 AND 2),
    out_of_corpus_ok BOOLEAN,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eval_results_run
    ON evaluation_results(run_id, created_at ASC);
