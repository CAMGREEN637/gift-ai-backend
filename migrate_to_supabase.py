#!/usr/bin/env python3
"""
Migration script to move data from SQLite to Supabase

Usage:
    python migrate_to_supabase.py

Prerequisites:
    - SQLite database file (giftai.db) exists
    - Supabase credentials configured in .env
    - All Supabase tables created
"""

import sqlite3
import sys
from datetime import datetime
from app.database import get_supabase
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SQLITE_DB_PATH = "giftai.db"


def migrate_user_preferences(sqlite_conn, supabase):
    """Migrate user_preferences table"""
    logger.info("Migrating user_preferences...")

    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM user_preferences")

    migrated = 0
    errors = 0

    for row in cursor.fetchall():
        try:
            data = {
                "user_id": row[0],
                "interests": row[1],  # Already JSON in SQLite
                "vibe": row[2]  # Already JSON in SQLite
            }

            result = supabase.table("user_preferences").insert(data).execute()
            migrated += 1
            logger.info(f"  ✓ Migrated user: {data['user_id']}")

        except Exception as e:
            errors += 1
            logger.error(f"  ✗ Error migrating user {row[0]}: {str(e)}")

    logger.info(f"User preferences: {migrated} migrated, {errors} errors")
    return migrated, errors


def migrate_feedback(sqlite_conn, supabase):
    """Migrate feedback table"""
    logger.info("Migrating feedback...")

    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM feedback")

    migrated = 0
    errors = 0

    for row in cursor.fetchall():
        try:
            data = {
                "user_id": row[1],
                "gift_name": row[2],
                "liked": bool(row[3])
            }

            result = supabase.table("feedback").insert(data).execute()
            migrated += 1

            if migrated % 10 == 0:
                logger.info(f"  Migrated {migrated} feedback entries...")

        except Exception as e:
            errors += 1
            logger.error(f"  ✗ Error migrating feedback {row[0]}: {str(e)}")

    logger.info(f"Feedback: {migrated} migrated, {errors} errors")
    return migrated, errors


def migrate_inferred_preferences(sqlite_conn, supabase):
    """Migrate inferred_preferences table"""
    logger.info("Migrating inferred_preferences...")

    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM inferred_preferences")

    migrated = 0
    errors = 0

    for row in cursor.fetchall():
        try:
            data = {
                "user_id": row[1],
                "category": row[2],
                "value": row[3],
                "weight": row[4]
            }

            result = supabase.table("inferred_preferences").insert(data).execute()
            migrated += 1

            if migrated % 10 == 0:
                logger.info(f"  Migrated {migrated} inferred preferences...")

        except Exception as e:
            errors += 1
            logger.error(f"  ✗ Error migrating inferred preference {row[0]}: {str(e)}")

    logger.info(f"Inferred preferences: {migrated} migrated, {errors} errors")
    return migrated, errors


def migrate_token_usage(sqlite_conn, supabase):
    """Migrate token_usage table"""
    logger.info("Migrating token_usage...")

    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM token_usage")

    migrated = 0
    errors = 0

    for row in cursor.fetchall():
        try:
            # Convert SQLite datetime to ISO format for PostgreSQL
            timestamp = row[5]  # Assuming timestamp is at index 5
            if isinstance(timestamp, str):
                # Already a string, use as-is
                timestamp_iso = timestamp
            else:
                # Convert to ISO format
                timestamp_iso = timestamp.isoformat()

            data = {
                "ip_address": row[1],
                "tokens_used": row[2],
                "model_name": row[3],
                "endpoint": row[4],
                "timestamp": timestamp_iso
            }

            result = supabase.table("token_usage").insert(data).execute()
            migrated += 1

            if migrated % 50 == 0:
                logger.info(f"  Migrated {migrated} token usage records...")

        except Exception as e:
            errors += 1
            logger.error(f"  ✗ Error migrating token usage {row[0]}: {str(e)}")

    logger.info(f"Token usage: {migrated} migrated, {errors} errors")
    return migrated, errors


def main():
    """Main migration function"""
    print("=" * 60)
    print("SQLite to Supabase Migration Tool")
    print("=" * 60)

    # Check if SQLite database exists
    try:
        sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
        logger.info(f"✓ Connected to SQLite database: {SQLITE_DB_PATH}")
    except Exception as e:
        logger.error(f"✗ Failed to connect to SQLite: {str(e)}")
        sys.exit(1)

    # Get Supabase client
    try:
        supabase = get_supabase()
        logger.info("✓ Connected to Supabase")
    except Exception as e:
        logger.error(f"✗ Failed to connect to Supabase: {str(e)}")
        logger.error("  Make sure SUPABASE_URL and SUPABASE_SERVICE_KEY are set in .env")
        sys.exit(1)

    # Confirm before proceeding
    print("\n⚠️  WARNING: This will copy all data from SQLite to Supabase")
    print("⚠️  Existing data in Supabase may cause conflicts")
    print()
    response = input("Continue? (yes/no): ")

    if response.lower() != "yes":
        logger.info("Migration cancelled")
        sys.exit(0)

    print("\nStarting migration...\n")

    # Track totals
    total_migrated = 0
    total_errors = 0

    # Migrate each table
    try:
        migrated, errors = migrate_user_preferences(sqlite_conn, supabase)
        total_migrated += migrated
        total_errors += errors
    except Exception as e:
        logger.error(f"User preferences migration failed: {str(e)}")

    try:
        migrated, errors = migrate_feedback(sqlite_conn, supabase)
        total_migrated += migrated
        total_errors += errors
    except Exception as e:
        logger.error(f"Feedback migration failed: {str(e)}")

    try:
        migrated, errors = migrate_inferred_preferences(sqlite_conn, supabase)
        total_migrated += migrated
        total_errors += errors
    except Exception as e:
        logger.error(f"Inferred preferences migration failed: {str(e)}")

    try:
        migrated, errors = migrate_token_usage(sqlite_conn, supabase)
        total_migrated += migrated
        total_errors += errors
    except Exception as e:
        logger.error(f"Token usage migration failed: {str(e)}")

    # Close SQLite connection
    sqlite_conn.close()

    # Summary
    print("\n" + "=" * 60)
    print("Migration Summary")
    print("=" * 60)
    print(f"Total records migrated: {total_migrated}")
    print(f"Total errors: {total_errors}")

    if total_errors == 0:
        print("\n✅ Migration completed successfully!")
    else:
        print(f"\n⚠️  Migration completed with {total_errors} errors")
        print("   Check logs above for details")

    print("\n📊 Verify your data in Supabase Table Editor:")
    print("   https://app.supabase.com")
    print("=" * 60)


if __name__ == "__main__":
    main()
