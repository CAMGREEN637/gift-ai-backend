-- Supabase Database Schema for Gift-AI Backend
-- Run this in your Supabase SQL Editor

-- Enable UUID extension (if not already enabled)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- Table: user_preferences
-- ============================================
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id TEXT PRIMARY KEY,
    interests JSONB DEFAULT '[]'::jsonb,
    vibe JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id ON user_preferences(user_id);

-- ============================================
-- Table: feedback
-- ============================================
CREATE TABLE IF NOT EXISTS feedback (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    gift_name TEXT NOT NULL,
    liked BOOLEAN NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at);

-- ============================================
-- Table: inferred_preferences
-- ============================================
CREATE TABLE IF NOT EXISTS inferred_preferences (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('interest', 'vibe')),
    value TEXT NOT NULL,
    weight INTEGER DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Ensure unique combination of user_id, category, and value
    UNIQUE(user_id, category, value)
);

-- Indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_inferred_preferences_user_id ON inferred_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_inferred_preferences_category ON inferred_preferences(category);
CREATE INDEX IF NOT EXISTS idx_inferred_preferences_composite ON inferred_preferences(user_id, category, value);

-- ============================================
-- Table: token_usage
-- ============================================
CREATE TABLE IF NOT EXISTS token_usage (
    id SERIAL PRIMARY KEY,
    ip_address TEXT NOT NULL,
    tokens_used INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for rate limiting queries
CREATE INDEX IF NOT EXISTS idx_token_usage_ip_address ON token_usage(ip_address);
CREATE INDEX IF NOT EXISTS idx_token_usage_timestamp ON token_usage(timestamp);
CREATE INDEX IF NOT EXISTS idx_token_usage_ip_timestamp ON token_usage(ip_address, timestamp);

-- ============================================
-- Row Level Security (RLS) Policies
-- ============================================
-- Note: Adjust these policies based on your authentication requirements
-- For now, we'll disable RLS since the backend handles authorization

ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE inferred_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE token_usage ENABLE ROW LEVEL SECURITY;

-- Policy: Allow all operations with service role key (backend)
-- This allows your backend to perform all operations
CREATE POLICY "Allow backend service role" ON user_preferences
    FOR ALL
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Allow backend service role" ON feedback
    FOR ALL
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Allow backend service role" ON inferred_preferences
    FOR ALL
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Allow backend service role" ON token_usage
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- ============================================
-- Triggers for updated_at timestamps
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply trigger to user_preferences
CREATE TRIGGER update_user_preferences_updated_at
    BEFORE UPDATE ON user_preferences
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Apply trigger to inferred_preferences
CREATE TRIGGER update_inferred_preferences_updated_at
    BEFORE UPDATE ON inferred_preferences
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- Optional: Cleanup function for old token_usage records
-- ============================================
CREATE OR REPLACE FUNCTION cleanup_old_token_usage()
RETURNS void AS $$
BEGIN
    DELETE FROM token_usage
    WHERE timestamp < NOW() - INTERVAL '7 days';
END;
$$ LANGUAGE plpgsql;

-- To manually cleanup: SELECT cleanup_old_token_usage();
-- Or set up a scheduled job in Supabase Dashboard

COMMENT ON TABLE user_preferences IS 'Stores user-provided explicit preferences for gift recommendations';
COMMENT ON TABLE feedback IS 'Stores user feedback on gift recommendations';
COMMENT ON TABLE inferred_preferences IS 'Stores inferred preferences based on user behavior';
COMMENT ON TABLE token_usage IS 'Tracks OpenAI API token usage for rate limiting';
