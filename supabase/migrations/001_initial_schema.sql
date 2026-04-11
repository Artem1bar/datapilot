-- ============================================================================
-- Data Tiger — Initial Schema for Supabase
-- Run this in the Supabase SQL Editor to create all tables.
-- ============================================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Users ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clerk_id VARCHAR(255) UNIQUE,
    email VARCHAR(320) UNIQUE NOT NULL,
    plan VARCHAR(50) NOT NULL DEFAULT 'free',
    credits_remaining INTEGER NOT NULL DEFAULT 50,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_clerk_id ON users(clerk_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- ── Datasets ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS datasets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename VARCHAR(500) NOT NULL,
    r2_key TEXT NOT NULL,
    file_size_bytes BIGINT,
    sheet_names TEXT[],
    row_count INTEGER,
    col_count INTEGER,
    status VARCHAR(50) NOT NULL DEFAULT 'uploaded',
    profile_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_datasets_user_id ON datasets(user_id);
CREATE INDEX IF NOT EXISTS idx_datasets_status ON datasets(status);

-- ── Jobs ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dataset_id UUID NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    progress INTEGER NOT NULL DEFAULT 0,
    input_json JSONB,
    result_json JSONB,
    error_text TEXT,
    celery_task_id VARCHAR(255),
    input_tokens INTEGER,
    output_tokens INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_jobs_dataset_id ON jobs(dataset_id);
CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

-- ── Cleaning Recipes ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cleaning_recipes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    steps_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cleaning_recipes_user_id ON cleaning_recipes(user_id);

-- ── Chat Sessions ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dataset_id UUID NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    messages_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_dataset_id ON chat_sessions(dataset_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id);

-- ── Row-Level Security (RLS) ────────────────────────────────────────────────
-- Enable RLS so each user can only see their own data via Supabase Auth.

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE cleaning_recipes ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY;

-- Allow authenticated users to access only their own rows
CREATE POLICY "Users own data" ON users
    FOR ALL USING (id = auth.uid());

CREATE POLICY "Users own datasets" ON datasets
    FOR ALL USING (user_id = auth.uid());

CREATE POLICY "Users own jobs" ON jobs
    FOR ALL USING (user_id = auth.uid());

CREATE POLICY "Users own recipes" ON cleaning_recipes
    FOR ALL USING (user_id = auth.uid());

CREATE POLICY "Users own chat sessions" ON chat_sessions
    FOR ALL USING (user_id = auth.uid());

-- Service role (backend) bypasses RLS automatically

-- ── Storage Bucket ──────────────────────────────────────────────────────────
-- Create the datapilot bucket for file uploads (if using Supabase Storage)

INSERT INTO storage.buckets (id, name, public)
VALUES ('datapilot', 'datapilot', false)
ON CONFLICT (id) DO NOTHING;

-- Allow authenticated users to upload/download their own files
CREATE POLICY "Users upload own files" ON storage.objects
    FOR INSERT WITH CHECK (
        bucket_id = 'datapilot'
        AND auth.uid()::text = (storage.foldername(name))[2]
    );

CREATE POLICY "Users download own files" ON storage.objects
    FOR SELECT USING (
        bucket_id = 'datapilot'
        AND auth.uid()::text = (storage.foldername(name))[2]
    );
