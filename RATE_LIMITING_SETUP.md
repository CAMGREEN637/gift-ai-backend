# Rate Limiting Implementation - Setup & Testing Guide

## Overview
This guide covers the setup and testing of the IP-based rate limiting system for the `/recommend` endpoint.

## What Was Implemented

### New Files Created
1. **`app/rate_limiter.py`** - Core rate limiting logic
   - IP extraction from request headers (handles proxy headers)
   - Token usage recording
   - Hourly usage calculation
   - Rate limit checking

2. **`app/dependencies.py`** - FastAPI dependency for rate limiting
   - Pre-request rate limit validation
   - Returns HTTP 429 when limit exceeded
   - Provides clear error messages with reset time

### Modified Files
1. **`app/database.py`**
   - Added `TokenUsage` model for tracking token consumption
   - Added `get_db()` dependency function
   - Added composite index for efficient queries

2. **`app/llm.py`**
   - Modified `generate_gift_response()` to return tuple: `(response_data, tokens_used)`
   - Extracts actual token usage from OpenAI API response

3. **`app/main.py`**
   - Integrated rate limiting dependency into `/recommend` endpoint
   - Records token usage after each successful request
   - Added proper logging for monitoring

## Setup Instructions

### 1. Install Dependencies (if needed)
All required dependencies are already in `requirements.txt`. If you need to reinstall:

```bash
pip install -r requirements.txt
```

### 2. Initialize Database
The database will automatically create the new `token_usage` table when the server starts.

Start the server to trigger database initialization:

```bash
uvicorn app.main:app --reload --port 8000
```

Or manually initialize:

```python
from app.database import init_db
init_db()
```

### 3. Environment Variables (Optional)
You can customize rate limiting parameters by setting these environment variables in your `.env` file:

```env
# Rate limiting configuration
HOURLY_TOKEN_LIMIT=10000  # Default: 10,000 tokens per hour
RATE_LIMIT_WINDOW=3600    # Default: 3600 seconds (1 hour)
```

## Testing the Implementation

### Test 1: Normal Usage
Make a few requests to verify the endpoint works normally:

```bash
curl "http://localhost:8000/recommend?query=gift%20for%20tech%20lover"
```

**Expected:**
- HTTP 200 OK
- Normal gift recommendations response
- Token usage recorded in database

### Test 2: Check Database
Verify token usage is being tracked:

```bash
sqlite3 giftai.db "SELECT * FROM token_usage ORDER BY timestamp DESC LIMIT 10;"
```

**Expected output:**
```
id|ip_address|tokens_used|model_name|endpoint|timestamp
1|127.0.0.1|450|gpt-4o-mini|/recommend|2026-02-06 15:30:22
```

### Test 3: Check Hourly Usage
See total tokens used by an IP in the last hour:

```bash
sqlite3 giftai.db "SELECT ip_address, SUM(tokens_used) as total
FROM token_usage
WHERE timestamp > datetime('now', '-1 hour')
GROUP BY ip_address;"
```

### Test 4: Trigger Rate Limit
Make multiple requests until you exceed 10,000 tokens (approximately 20-30 requests depending on response size):

```bash
# Run this in a loop
for i in {1..30}; do
  echo "Request $i"
  curl -s "http://localhost:8000/recommend?query=tech%20gift%20for%20developer" | head -c 100
  echo ""
  sleep 1
done
```

**Expected when limit is reached:**
- HTTP 429 Too Many Requests
- Response body:
```json
{
  "detail": {
    "error": "Rate limit exceeded",
    "message": "You have used 10234 tokens in the last hour. Limit is 10000 tokens per hour.",
    "tokens_used": 10234,
    "limit": 10000,
    "reset_time": "2026-02-06T16:30:22.123456",
    "retry_after_seconds": 3456
  }
}
```

### Test 5: Verify Rate Limit Reset
Wait for the time window to pass (or modify an old database record for testing):

```bash
# Option A: Wait 1 hour and test again

# Option B: Manually reset for testing (delete old records)
sqlite3 giftai.db "DELETE FROM token_usage WHERE ip_address='127.0.0.1';"

# Then make a new request
curl "http://localhost:8000/recommend?query=birthday%20gift"
```

**Expected:**
- HTTP 200 OK
- New request succeeds

### Test 6: Multiple IP Addresses
Test that different IPs have independent rate limits:

```bash
# Simulate different IPs using X-Forwarded-For header
curl -H "X-Forwarded-For: 192.168.1.100" "http://localhost:8000/recommend?query=gift1"
curl -H "X-Forwarded-For: 192.168.1.101" "http://localhost:8000/recommend?query=gift2"

# Check that each IP is tracked separately
sqlite3 giftai.db "SELECT ip_address, COUNT(*) as requests, SUM(tokens_used) as total_tokens
FROM token_usage
GROUP BY ip_address;"
```

## Monitoring & Maintenance

### View Recent Activity
```bash
sqlite3 giftai.db "SELECT ip_address, tokens_used, model_name, endpoint, timestamp
FROM token_usage
ORDER BY timestamp DESC
LIMIT 20;"
```

### View Top Users (by token usage)
```bash
sqlite3 giftai.db "SELECT ip_address,
       COUNT(*) as requests,
       SUM(tokens_used) as total_tokens,
       AVG(tokens_used) as avg_tokens
FROM token_usage
WHERE timestamp > datetime('now', '-1 day')
GROUP BY ip_address
ORDER BY total_tokens DESC
LIMIT 10;"
```

### Clean Up Old Records (Optional)
To prevent database bloat, you can periodically clean up old token usage records:

```bash
# Delete records older than 7 days
sqlite3 giftai.db "DELETE FROM token_usage WHERE timestamp < datetime('now', '-7 days');"
```

Consider setting up a cron job or scheduled task for this.

## Logging

The implementation includes logging at key points:

- Request received: `"Recommendation request from IP: {ip_address}, query: {query}"`
- Token usage recorded: `"Recorded {tokens_used} tokens for IP: {ip_address}"`
- Token recording failure: `"Failed to record token usage: {error}"`

Check application logs when debugging:

```bash
# If running with uvicorn
tail -f logs/app.log  # or wherever your logs are configured

# Check stdout if running in terminal
```

## Troubleshooting

### Problem: Rate limit not working
**Solution:**
1. Check database was initialized: `sqlite3 giftai.db ".tables"` should show `token_usage`
2. Verify dependency is being called - check logs for "Recommendation request from IP"
3. Check if token recording is failing - look for error logs

### Problem: Wrong IP address being recorded
**Solution:**
- If behind a reverse proxy (nginx, Apache, etc.), ensure `X-Forwarded-For` header is set
- Check logs to see what IP is being captured
- Modify `get_client_ip()` in `app/rate_limiter.py` if needed

### Problem: Token count is 0
**Solution:**
- Verify OpenAI API is returning usage data
- Check `response.usage.total_tokens` in the OpenAI response
- Add debug logging in `app/llm.py` to inspect the response object

### Problem: Rate limit resets too quickly/slowly
**Solution:**
- Check `RATE_LIMIT_WINDOW` environment variable
- Verify server timezone is correct (should use UTC)
- Check database timestamps: `sqlite3 giftai.db "SELECT datetime('now');"`

## Performance Considerations

- Each request adds ~5ms for database lookups (2 queries: check limit + record usage)
- Database indexes on `ip_address` and `timestamp` ensure fast queries
- Consider adding database connection pooling for high-traffic scenarios
- For very high traffic (>1000 req/s), consider Redis-based rate limiting instead

## Future Enhancements

The current implementation is simple and effective. Possible improvements:

1. **Redis Integration**: For better performance at scale
2. **Per-User Limits**: Track by user_id when authentication is added
3. **Tiered Limits**: Different limits for different user tiers
4. **Rate Limit Headers**: Add `X-RateLimit-Remaining` headers to responses
5. **Admin Dashboard**: Web UI to view usage statistics
6. **Alerts**: Notify admins when users hit rate limits frequently

## Architecture Notes

### Why IP-based?
- No authentication system currently exists
- Simple and effective for preventing abuse
- Works immediately without user accounts

### Why sliding window?
- More fair than fixed windows
- Prevents burst abuse at window boundaries
- Users get tokens back gradually

### Why record every request?
- Accurate tracking of actual token consumption
- Enables usage analytics
- Audit trail for debugging

### Token estimation
- Currently only tracks LLM completion tokens (main cost driver)
- Embedding API calls (~50 tokens) are not tracked (negligible cost)
- Future: Could add embedding token tracking if needed

## API Reference

### Rate Limit Error Response (HTTP 429)

```json
{
  "detail": {
    "error": "Rate limit exceeded",
    "message": "You have used 10234 tokens in the last hour. Limit is 10000 tokens per hour.",
    "tokens_used": 10234,
    "limit": 10000,
    "reset_time": "2026-02-06T16:30:22.123456",
    "retry_after_seconds": 3456
  }
}
```

**Fields:**
- `error`: Short error identifier
- `message`: Human-readable explanation
- `tokens_used`: Current token count in the window
- `limit`: Maximum allowed tokens
- `reset_time`: ISO 8601 timestamp when limit resets
- `retry_after_seconds`: Seconds until limit resets

## Contact

For issues or questions about the rate limiting implementation:
1. Check application logs first
2. Verify database state
3. Review this guide's troubleshooting section
