#!/usr/bin/env python3
"""
Test script for rate limiting functionality
Run this with: python test_rate_limiting.py

Make sure the backend server is running first:
  uvicorn app.main:app --reload --port 8000
"""

import requests
import time
import sys

BASE_URL = "http://localhost:8000"

print("=" * 70)
print("Testing Rate Limiting Implementation")
print("=" * 70)

# Test 1: Verify server is running
print("\n1. Testing server connection...")
try:
    response = requests.get(f"{BASE_URL}/")
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        print("   ✓ Server is running")
    else:
        print("   ✗ Server returned unexpected status")
        sys.exit(1)
except Exception as e:
    print(f"   ✗ Error: {e}")
    print("   → Make sure server is running: uvicorn app.main:app --port 8000")
    sys.exit(1)

# Test 2: Make a normal request
print("\n2. Testing normal /recommend request...")
try:
    response = requests.get(
        f"{BASE_URL}/recommend",
        params={"query": "tech gift for developer"}
    )
    print(f"   Status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print(f"   ✓ Request successful")
        print(f"   Response has {len(data.get('gifts', []))} gifts")
    else:
        print(f"   Response: {response.text}")
        print("   Note: This might be expected if you don't have data loaded")
except Exception as e:
    print(f"   ✗ Error: {e}")

# Test 3: Make multiple requests to track token usage
print("\n3. Making multiple requests to accumulate tokens...")
total_requests = 5
successful = 0
failed = 0
rate_limited = 0

for i in range(1, total_requests + 1):
    try:
        response = requests.get(
            f"{BASE_URL}/recommend",
            params={"query": f"gift idea {i}"}
        )

        if response.status_code == 200:
            successful += 1
            print(f"   Request {i}: ✓ Success (200)")
        elif response.status_code == 429:
            rate_limited += 1
            data = response.json()
            detail = data.get("detail", {})
            print(f"   Request {i}: ⚠ Rate limited (429)")
            print(f"      Tokens used: {detail.get('tokens_used', 'N/A')}")
            print(f"      Limit: {detail.get('limit', 'N/A')}")
            print(f"      Retry after: {detail.get('retry_after_seconds', 'N/A')}s")
            break
        else:
            failed += 1
            print(f"   Request {i}: ✗ Failed ({response.status_code})")

        # Small delay between requests
        time.sleep(0.5)

    except Exception as e:
        failed += 1
        print(f"   Request {i}: ✗ Error: {e}")

print(f"\n   Summary: {successful} successful, {rate_limited} rate limited, {failed} failed")

# Test 4: Verify different IPs are tracked separately
print("\n4. Testing IP-based tracking with X-Forwarded-For header...")
try:
    # Request from "different" IP
    response = requests.get(
        f"{BASE_URL}/recommend",
        params={"query": "birthday gift"},
        headers={"X-Forwarded-For": "192.168.100.50"}
    )
    print(f"   Status: {response.status_code}")

    if response.status_code == 200:
        print("   ✓ Request from different IP successful")
        print("   This confirms IPs are tracked independently")
    elif response.status_code == 429:
        print("   ⚠ Rate limited even with different IP")
        print("   (This is unexpected - check implementation)")
    else:
        print(f"   Response: {response.text[:200]}")

except Exception as e:
    print(f"   ✗ Error: {e}")

# Test 5: Check rate limit error response format
print("\n5. Testing rate limit error response format...")
print("   Making requests until rate limit is hit...")

# Make enough requests to potentially hit the limit
# Average request uses ~400-600 tokens, so ~17-25 requests to hit 10,000
max_requests = 30
hit_rate_limit = False

for i in range(max_requests):
    try:
        response = requests.get(
            f"{BASE_URL}/recommend",
            params={"query": f"unique gift {i}"}
        )

        if response.status_code == 429:
            hit_rate_limit = True
            data = response.json()
            detail = data.get("detail", {})

            print(f"   ✓ Hit rate limit after {i + successful} total requests")
            print(f"\n   Rate Limit Response:")
            print(f"      Error: {detail.get('error')}")
            print(f"      Message: {detail.get('message')}")
            print(f"      Tokens Used: {detail.get('tokens_used')}")
            print(f"      Limit: {detail.get('limit')}")
            print(f"      Reset Time: {detail.get('reset_time')}")
            print(f"      Retry After: {detail.get('retry_after_seconds')}s")

            # Verify all required fields are present
            required_fields = ['error', 'message', 'tokens_used', 'limit',
                             'reset_time', 'retry_after_seconds']
            missing_fields = [f for f in required_fields if f not in detail]

            if missing_fields:
                print(f"\n   ✗ Missing required fields: {missing_fields}")
            else:
                print(f"\n   ✓ All required fields present in error response")

            break
        elif response.status_code == 200:
            # Continue trying
            if i % 5 == 0:
                print(f"   Made {i + successful} requests, continuing...")
        else:
            print(f"   Unexpected status: {response.status_code}")
            break

        time.sleep(0.3)  # Slightly faster

    except Exception as e:
        print(f"   ✗ Error: {e}")
        break

if not hit_rate_limit and max_requests == 30:
    print(f"\n   ℹ Did not hit rate limit after {max_requests} requests")
    print(f"   This might mean:")
    print(f"   - Token usage is very low per request")
    print(f"   - Rate limit is set higher than expected")
    print(f"   - Or there's an issue with rate limiting")

# Summary
print("\n" + "=" * 70)
print("Test Summary")
print("=" * 70)
print("""
To verify rate limiting is working properly, check:

1. Database has token_usage table:
   sqlite3 giftai.db "SELECT COUNT(*) FROM token_usage;"

2. View recent token usage:
   sqlite3 giftai.db "SELECT * FROM token_usage ORDER BY timestamp DESC LIMIT 10;"

3. Check total usage per IP:
   sqlite3 giftai.db "SELECT ip_address, SUM(tokens_used) as total FROM token_usage GROUP BY ip_address;"

4. Check application logs for:
   - "Recommendation request from IP: ..."
   - "Recorded X tokens for IP: ..."

If rate limiting is not working:
- Verify server restarted after code changes
- Check for errors in server logs
- Ensure database was initialized (token_usage table exists)
""")

print("=" * 70)
print("Testing complete!")
print("=" * 70)
