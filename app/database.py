# app/database.py
# Supabase database client and utilities

import os
from typing import Optional
from supabase import create_client, Client
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)

# ============================================
# Supabase Client Initialization
# ============================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # Use service role key for backend

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.warning("Supabase credentials not found. Database operations will fail.")
    logger.warning("Please set SUPABASE_URL and SUPABASE_SERVICE_KEY in your .env file")

# Initialize Supabase client
supabase: Optional[Client] = None

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("Supabase client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Supabase client: {str(e)}")
    supabase = None


def get_supabase() -> Client:
    """
    Get the Supabase client instance.

    Returns:
        Client: Supabase client instance

    Raises:
        RuntimeError: If Supabase client is not initialized
    """
    if supabase is None:
        raise RuntimeError(
            "Supabase client not initialized. "
            "Please check SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables."
        )
    return supabase


def get_db():
    """
    FastAPI dependency for database access.
    Returns the Supabase client for use in route handlers.

    Yields:
        Client: Supabase client instance
    """
    try:
        client = get_supabase()
        yield client
    except Exception as e:
        logger.error(f"Error getting database client: {str(e)}")
        raise


# ============================================
# Database Health Check
# ============================================

def check_db_connection() -> bool:
    """
    Check if database connection is healthy.

    Returns:
        bool: True if connection is healthy, False otherwise
    """
    try:
        client = get_supabase()
        # Try a simple query to verify connection
        result = client.table("user_preferences").select("user_id").limit(1).execute()
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        return False


# ============================================
# Initialization Function
# ============================================

def init_db():
    """
    Initialize database connection and verify setup.

    Note: With Supabase, tables are created via SQL in the Supabase dashboard.
    This function just verifies the connection.
    """
    try:
        client = get_supabase()
        logger.info("Database connection verified")

        # Optionally verify that required tables exist
        tables = ["user_preferences", "feedback", "inferred_preferences", "token_usage"]
        for table in tables:
            try:
                client.table(table).select("*").limit(1).execute()
                logger.info(f"✓ Table '{table}' is accessible")
            except Exception as e:
                logger.warning(f"✗ Table '{table}' might not exist or is not accessible: {str(e)}")

    except Exception as e:
        logger.error(f"Database initialization failed: {str(e)}")
        raise


# ============================================
# Legacy Compatibility (for migration)
# ============================================
# These are kept for backward compatibility during migration
# Remove after full migration is complete

SessionLocal = None  # No longer used with Supabase
Base = None  # No longer used with Supabase

# Table name constants for consistency
TABLE_USER_PREFERENCES = "user_preferences"
TABLE_FEEDBACK = "feedback"
TABLE_INFERRED_PREFERENCES = "inferred_preferences"
TABLE_TOKEN_USAGE = "token_usage"
