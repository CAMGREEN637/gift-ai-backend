#!/usr/bin/env python3
"""
Test script to verify your FastAPI backend endpoints
Run this with: python test_backend.py
"""

import requests
import sys

BASE_URL = "http://localhost:8000"

print("=" * 60)
print("Testing FastAPI Backend Endpoints")
print("=" * 60)

# Test 1: Health check
print("\n1. Testing health endpoint (/)...")
try:
    response = requests.get(f"{BASE_URL}/")
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.json()}")
    if response.status_code == 200:
        print("   ✓ Health check passed")
    else:
        print("   ✗ Health check failed")
except Exception as e:
    print(f"   ✗ Error: {e}")
    print("   → Is your backend running on port 8000?")
    sys.exit(1)

# Test 2: List all endpoints
print("\n2. Checking available endpoints...")
try:
    response = requests.get(f"{BASE_URL}/openapi.json")
    if response.status_code == 200:
        openapi = response.json()
        paths = list(openapi.get("paths", {}).keys())
        print(f"   Found {len(paths)} endpoints:")
        for path in paths:
            print(f"     - {path}")

        if "/test-proxy" in paths:
            print("   ✓ /test-proxy endpoint exists")
        else:
            print("   ✗ /test-proxy endpoint NOT FOUND")
            print("   → Your main.py might not have the proxy endpoints")

        if "/proxy-image" in paths:
            print("   ✓ /proxy-image endpoint exists")
        else:
            print("   ✗ /proxy-image endpoint NOT FOUND")
except Exception as e:
    print(f"   ✗ Error: {e}")

# Test 3: Test proxy endpoint
print("\n3. Testing /test-proxy endpoint...")
try:
    response = requests.get(f"{BASE_URL}/test-proxy")
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        print(f"   Content-Type: {response.headers.get('content-type')}")
        print(f"   Content-Length: {len(response.content)} bytes")
        print("   ✓ /test-proxy is working!")
    else:
        print(f"   Response: {response.text}")
        print("   ✗ /test-proxy failed")
except Exception as e:
    print(f"   ✗ Error: {e}")

# Test 4: Test proxy-image with a URL
print("\n4. Testing /proxy-image with a test URL...")
test_url = "https://m.media-amazon.com/images/I/71zK6H8F1TL._AC_SL1500_.jpg"
try:
    response = requests.get(f"{BASE_URL}/proxy-image?url={test_url}")
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        print(f"   Content-Type: {response.headers.get('content-type')}")
        print(f"   Content-Length: {len(response.content)} bytes")
        print("   ✓ /proxy-image is working!")
    else:
        print(f"   Response: {response.text}")
        print("   ✗ /proxy-image failed")
except Exception as e:
    print(f"   ✗ Error: {e}")

print("\n" + "=" * 60)
print("Testing complete!")
print("=" * 60)