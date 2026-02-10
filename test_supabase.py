#!/usr/bin/env python3
"""
Test script for Supabase integration

Usage:
    python test_supabase.py

This script tests:
1. Database connection
2. Table accessibility
3. Basic CRUD operations
4. Persistence functions
5. Rate limiting functions
"""

import sys
from datetime import datetime
from app.database import get_supabase, init_db, check_db_connection
from app.persistence import (
    save_preferences, get_preferences,
    save_feedback, get_feedback,
    update_inferred, get_inferred
)
from app.rate_limiter import record_token_usage, get_hourly_token_usage


def test_connection():
    """Test database connection"""
    print("\n1. Testing database connection...")
    try:
        init_db()
        print("   ✓ Database initialized successfully")
        return True
    except Exception as e:
        print(f"   ✗ Database initialization failed: {str(e)}")
        return False


def test_tables():
    """Test table accessibility"""
    print("\n2. Testing table accessibility...")
    try:
        supabase = get_supabase()
        tables = ["user_preferences", "feedback", "inferred_preferences", "token_usage"]

        all_ok = True
        for table in tables:
            try:
                result = supabase.table(table).select("*").limit(1).execute()
                print(f"   ✓ Table '{table}' is accessible")
            except Exception as e:
                print(f"   ✗ Table '{table}' failed: {str(e)}")
                all_ok = False

        return all_ok
    except Exception as e:
        print(f"   ✗ Error: {str(e)}")
        return False


def test_preferences():
    """Test user preferences operations"""
    print("\n3. Testing user preferences...")
    test_user_id = f"test-user-{datetime.now().timestamp()}"

    try:
        # Test save
        success = save_preferences(
            user_id=test_user_id,
            interests=["technology", "gaming"],
            vibe=["modern", "innovative"]
        )
        if not success:
            print("   ✗ Failed to save preferences")
            return False
        print(f"   ✓ Saved preferences for user: {test_user_id}")

        # Test get
        prefs = get_preferences(test_user_id)
        if not prefs:
            print("   ✗ Failed to retrieve preferences")
            return False

        if prefs["interests"] == ["technology", "gaming"] and prefs["vibe"] == ["modern", "innovative"]:
            print(f"   ✓ Retrieved preferences correctly")
        else:
            print(f"   ✗ Retrieved preferences don't match")
            return False

        # Test update
        success = save_preferences(
            user_id=test_user_id,
            interests=["technology", "gaming", "music"],
            vibe=["modern"]
        )
        if not success:
            print("   ✗ Failed to update preferences")
            return False

        prefs = get_preferences(test_user_id)
        if len(prefs["interests"]) == 3:
            print(f"   ✓ Updated preferences correctly")
        else:
            print(f"   ✗ Update didn't work as expected")
            return False

        # Cleanup
        supabase = get_supabase()
        supabase.table("user_preferences").delete().eq("user_id", test_user_id).execute()
        print(f"   ✓ Cleaned up test data")

        return True

    except Exception as e:
        print(f"   ✗ Error: {str(e)}")
        return False


def test_feedback():
    """Test feedback operations"""
    print("\n4. Testing feedback...")
    test_user_id = f"test-user-{datetime.now().timestamp()}"

    try:
        # Test save feedback
        success = save_feedback(test_user_id, "Test Gift 1", True)
        if not success:
            print("   ✗ Failed to save feedback")
            return False
        print(f"   ✓ Saved feedback")

        success = save_feedback(test_user_id, "Test Gift 2", False)
        if not success:
            print("   ✗ Failed to save second feedback")
            return False

        # Test get feedback
        feedback_list = get_feedback(test_user_id)
        if len(feedback_list) != 2:
            print(f"   ✗ Expected 2 feedback entries, got {len(feedback_list)}")
            return False

        print(f"   ✓ Retrieved {len(feedback_list)} feedback entries")

        # Cleanup
        supabase = get_supabase()
        supabase.table("feedback").delete().eq("user_id", test_user_id).execute()
        print(f"   ✓ Cleaned up test data")

        return True

    except Exception as e:
        print(f"   ✗ Error: {str(e)}")
        return False


def test_inferred():
    """Test inferred preferences"""
    print("\n5. Testing inferred preferences...")
    test_user_id = f"test-user-{datetime.now().timestamp()}"

    try:
        # Test create
        success = update_inferred(test_user_id, "interest", "technology")
        if not success:
            print("   ✗ Failed to create inferred preference")
            return False
        print(f"   ✓ Created inferred preference")

        # Test increment
        success = update_inferred(test_user_id, "interest", "technology")
        if not success:
            print("   ✗ Failed to increment weight")
            return False

        # Test get
        inferred = get_inferred(test_user_id)
        if inferred["interests"].get("technology") != 2:
            print(f"   ✗ Expected weight 2, got {inferred['interests'].get('technology')}")
            return False

        print(f"   ✓ Weight incremented correctly")

        # Test multiple categories
        update_inferred(test_user_id, "vibe", "modern")
        inferred = get_inferred(test_user_id)

        if "technology" in inferred["interests"] and "modern" in inferred["vibe"]:
            print(f"   ✓ Multiple categories working")
        else:
            print(f"   ✗ Multiple categories failed")
            return False

        # Cleanup
        supabase = get_supabase()
        supabase.table("inferred_preferences").delete().eq("user_id", test_user_id).execute()
        print(f"   ✓ Cleaned up test data")

        return True

    except Exception as e:
        print(f"   ✗ Error: {str(e)}")
        return False


def test_rate_limiting():
    """Test rate limiting functions"""
    print("\n6. Testing rate limiting...")
    test_ip = f"192.168.1.{int(datetime.now().timestamp()) % 255}"

    try:
        supabase = get_supabase()

        # Test record usage
        success = record_token_usage(
            client=supabase,
            ip_address=test_ip,
            tokens=500,
            model="gpt-4o-mini",
            endpoint="/recommend"
        )
        if not success:
            print("   ✗ Failed to record token usage")
            return False
        print(f"   ✓ Recorded token usage")

        # Test get usage
        total = get_hourly_token_usage(supabase, test_ip)
        if total != 500:
            print(f"   ✗ Expected 500 tokens, got {total}")
            return False
        print(f"   ✓ Retrieved token usage correctly")

        # Test multiple records
        record_token_usage(supabase, test_ip, 300, "gpt-4o-mini", "/recommend")
        total = get_hourly_token_usage(supabase, test_ip)

        if total != 800:
            print(f"   ✗ Expected 800 tokens, got {total}")
            return False
        print(f"   ✓ Multiple records summed correctly")

        # Cleanup
        supabase.table("token_usage").delete().eq("ip_address", test_ip).execute()
        print(f"   ✓ Cleaned up test data")

        return True

    except Exception as e:
        print(f"   ✗ Error: {str(e)}")
        return False


def test_health_check():
    """Test health check function"""
    print("\n7. Testing health check...")
    try:
        is_healthy = check_db_connection()
        if is_healthy:
            print("   ✓ Database health check passed")
            return True
        else:
            print("   ✗ Database health check failed")
            return False
    except Exception as e:
        print(f"   ✗ Error: {str(e)}")
        return False


def main():
    """Run all tests"""
    print("=" * 60)
    print("Supabase Integration Tests")
    print("=" * 60)

    results = []

    # Run tests
    results.append(("Connection", test_connection()))
    results.append(("Tables", test_tables()))
    results.append(("Preferences", test_preferences()))
    results.append(("Feedback", test_feedback()))
    results.append(("Inferred Preferences", test_inferred()))
    results.append(("Rate Limiting", test_rate_limiting()))
    results.append(("Health Check", test_health_check()))

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:8} {name}")

    print("=" * 60)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("\n✅ All tests passed! Supabase is working correctly.")
        sys.exit(0)
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
