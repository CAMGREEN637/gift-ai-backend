-- Products/Gifts Table Schema for Supabase
-- Add this to your existing Supabase database

-- ============================================
-- Table: gifts (products)
-- ============================================
CREATE TABLE IF NOT EXISTS gifts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL,
    currency TEXT DEFAULT 'USD',

    -- Categorical arrays (JSONB for flexibility)
    categories JSONB DEFAULT '[]'::jsonb,
    interests JSONB DEFAULT '[]'::jsonb,
    occasions JSONB DEFAULT '[]'::jsonb,
    vibe JSONB DEFAULT '[]'::jsonb,
    personality_traits JSONB DEFAULT '[]'::jsonb,

    -- Recipient info (nested JSON)
    recipient JSONB DEFAULT '{}'::jsonb,

    -- Additional attributes
    experience_level TEXT CHECK (experience_level IN ('beginner', 'enthusiast', 'expert')),
    brand TEXT,
    link TEXT,
    image_url TEXT,
    source TEXT DEFAULT 'amazon',

    -- Quality metrics
    rating DECIMAL(3, 2),
    review_count INTEGER DEFAULT 0,
    in_stock BOOLEAN DEFAULT true,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by TEXT,
    updated_by TEXT,

    -- Constraints
    CONSTRAINT valid_price CHECK (price >= 0),
    CONSTRAINT valid_rating CHECK (rating IS NULL OR (rating >= 0 AND rating <= 5))
);

-- ============================================
-- Indexes for Performance
-- ============================================
CREATE INDEX IF NOT EXISTS idx_gifts_price ON gifts(price);
CREATE INDEX IF NOT EXISTS idx_gifts_rating ON gifts(rating);
CREATE INDEX IF NOT EXISTS idx_gifts_created_at ON gifts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gifts_source ON gifts(source);
CREATE INDEX IF NOT EXISTS idx_gifts_in_stock ON gifts(in_stock);

-- GIN indexes for JSONB array searches
CREATE INDEX IF NOT EXISTS idx_gifts_categories ON gifts USING GIN (categories);
CREATE INDEX IF NOT EXISTS idx_gifts_interests ON gifts USING GIN (interests);
CREATE INDEX IF NOT EXISTS idx_gifts_occasions ON gifts USING GIN (occasions);
CREATE INDEX IF NOT EXISTS idx_gifts_vibe ON gifts USING GIN (vibe);
CREATE INDEX IF NOT EXISTS idx_gifts_personality_traits ON gifts USING GIN (personality_traits);
CREATE INDEX IF NOT EXISTS idx_gifts_recipient ON gifts USING GIN (recipient);

-- Full-text search index
CREATE INDEX IF NOT EXISTS idx_gifts_search ON gifts USING GIN (
    to_tsvector('english', COALESCE(name, '') || ' ' || COALESCE(description, '') || ' ' || COALESCE(brand, ''))
);

-- ============================================
-- Trigger for updated_at
-- ============================================
CREATE OR REPLACE FUNCTION update_gifts_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_gifts_updated_at
    BEFORE UPDATE ON gifts
    FOR EACH ROW
    EXECUTE FUNCTION update_gifts_updated_at();

-- ============================================
-- Row Level Security (RLS)
-- ============================================
ALTER TABLE gifts ENABLE ROW LEVEL SECURITY;

-- Allow all operations with service role (backend)
CREATE POLICY "Allow backend service role" ON gifts
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- ============================================
-- Helper Functions
-- ============================================

-- Function to get next gift ID
CREATE OR REPLACE FUNCTION get_next_gift_id()
RETURNS TEXT AS $$
DECLARE
    last_id TEXT;
    last_num INTEGER;
    next_num INTEGER;
BEGIN
    -- Get the last gift ID
    SELECT id INTO last_id
    FROM gifts
    WHERE id LIKE 'gift_%'
    ORDER BY id DESC
    LIMIT 1;

    IF last_id IS NULL THEN
        -- First product
        RETURN 'gift_0001';
    ELSE
        -- Extract number and increment
        last_num := CAST(SUBSTRING(last_id FROM 6) AS INTEGER);
        next_num := last_num + 1;
        RETURN 'gift_' || LPAD(next_num::TEXT, 4, '0');
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function to search gifts by text
CREATE OR REPLACE FUNCTION search_gifts(search_query TEXT)
RETURNS SETOF gifts AS $$
BEGIN
    RETURN QUERY
    SELECT *
    FROM gifts
    WHERE to_tsvector('english', COALESCE(name, '') || ' ' || COALESCE(description, '') || ' ' || COALESCE(brand, ''))
          @@ plainto_tsquery('english', search_query)
    ORDER BY rating DESC NULLS LAST, review_count DESC;
END;
$$ LANGUAGE plpgsql;

-- Function to validate array limits
CREATE OR REPLACE FUNCTION validate_gift_arrays()
RETURNS TRIGGER AS $$
BEGIN
    -- Validate categories (max 2)
    IF jsonb_array_length(NEW.categories) > 2 THEN
        RAISE EXCEPTION 'categories array cannot have more than 2 elements';
    END IF;

    -- Validate interests (max 5)
    IF jsonb_array_length(NEW.interests) > 5 THEN
        RAISE EXCEPTION 'interests array cannot have more than 5 elements';
    END IF;

    -- Validate occasions (max 4)
    IF jsonb_array_length(NEW.occasions) > 4 THEN
        RAISE EXCEPTION 'occasions array cannot have more than 4 elements';
    END IF;

    -- Validate vibe (max 3)
    IF jsonb_array_length(NEW.vibe) > 3 THEN
        RAISE EXCEPTION 'vibe array cannot have more than 3 elements';
    END IF;

    -- Validate personality_traits (max 3)
    IF jsonb_array_length(NEW.personality_traits) > 3 THEN
        RAISE EXCEPTION 'personality_traits array cannot have more than 3 elements';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER validate_gift_arrays_trigger
    BEFORE INSERT OR UPDATE ON gifts
    FOR EACH ROW
    EXECUTE FUNCTION validate_gift_arrays();

-- ============================================
-- Sample Data (for testing)
-- ============================================
-- Uncomment to insert sample data
/*
INSERT INTO gifts (
    id, name, description, price, currency,
    categories, interests, occasions,
    recipient, vibe, personality_traits,
    experience_level, brand, link, image_url, source,
    rating, review_count, in_stock
) VALUES (
    'gift_0001',
    'Premium Coffee Maker',
    'High-quality automatic espresso machine',
    299.99,
    'USD',
    '["kitchen", "home"]'::jsonb,
    '["coffee", "cooking"]'::jsonb,
    '["birthday", "holiday", "just_because"]'::jsonb,
    '{"gender": ["unisex"], "relationship": ["partner", "friend"]}'::jsonb,
    '["practical", "luxury"]'::jsonb,
    '["organized", "analytical"]'::jsonb,
    'enthusiast',
    'Breville',
    'https://amazon.com/dp/B00Example',
    'https://m.media-amazon.com/images/example.jpg',
    'amazon',
    4.5,
    1250,
    true
);
*/

COMMENT ON TABLE gifts IS 'Product catalog for gift recommendations';
COMMENT ON COLUMN gifts.categories IS 'Product categories (max 2)';
COMMENT ON COLUMN gifts.interests IS 'User interests this gift matches (max 5)';
COMMENT ON COLUMN gifts.occasions IS 'Suitable occasions (max 4)';
COMMENT ON COLUMN gifts.vibe IS 'Gift vibe/mood (max 3)';
COMMENT ON COLUMN gifts.personality_traits IS 'Matching personality traits (max 3)';
COMMENT ON COLUMN gifts.recipient IS 'Recipient details (gender, relationship)';
