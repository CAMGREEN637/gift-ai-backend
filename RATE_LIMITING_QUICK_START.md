# Rate Limiting - Quick Start Guide

## Quick Summary

✅ **What was implemented:**
- IP-based rate limiting for `/recommend` endpoint
- Limit: 10,000 tokens per hour per IP
- Tracks actual token usage from OpenAI API responses
- Returns HTTP 429 when limit exceeded with clear error message

## Files Changed

### New Files
- `app/rate_limiter.py` - Rate limiting logic
- `app/dependencies.py` - FastAPI dependency
- `test_rate_limiting.py` - Test script
- `RATE_LIMITING_SETUP.md` - Detailed guide

### Modified Files
- `app/database.py` - Added TokenUsage model
- `app/llm.py` - Now returns token count
- `app/main.py` - Integrated rate limiting

## Quick Start

### 1. Start the server
```bash
cd /c/Users/camry/PycharmProjects/PythonProject/gift-ai-backend
uvicorn app.main:app --reload --port 8000
```

The database will automatically create the `token_usage` table on startup.

### 2. Test it works
```bash
# Simple test
curl "http://localhost:8000/recommend?query=tech%20gift"

# Run comprehensive tests
python test_rate_limiting.py
```

### 3. Check database
```bash
sqlite3 giftai.db "SELECT * FROM token_usage ORDER BY timestamp DESC LIMIT 5;"
```

## How It Works

1. **Before Request**: Rate limit dependency checks if IP has exceeded limit
2. **If Over Limit**: Returns HTTP 429 with error details
3. **If Under Limit**: Request proceeds normally
4. **After Request**: Records actual token usage from OpenAI response

## Rate Limit Error Example

When limit is exceeded, clients receive:

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

## Configuration

Set in `.env` file (optional):

```env
HOURLY_TOKEN_LIMIT=10000  # Tokens per hour per IP
RATE_LIMIT_WINDOW=3600    # Window in seconds
```

## Monitoring

### View recent usage
```bash
sqlite3 giftai.db "SELECT ip_address, tokens_used, timestamp FROM token_usage ORDER BY timestamp DESC LIMIT 20;"
```

### View usage by IP
```bash
sqlite3 giftai.db "SELECT ip_address, COUNT(*) as requests, SUM(tokens_used) as total_tokens FROM token_usage WHERE timestamp > datetime('now', '-1 hour') GROUP BY ip_address;"
```

### Check if someone hit the limit
```bash
sqlite3 giftai.db "SELECT ip_address, SUM(tokens_used) as total FROM token_usage WHERE timestamp > datetime('now', '-1 hour') GROUP BY ip_address HAVING total > 10000;"
```

## Testing Scenarios

### Test 1: Normal usage
```bash
curl "http://localhost:8000/recommend?query=birthday%20gift"
# Should return 200 OK with gift recommendations
```

### Test 2: Different IPs
```bash
curl -H "X-Forwarded-For: 192.168.1.100" "http://localhost:8000/recommend?query=gift1"
curl -H "X-Forwarded-For: 192.168.1.101" "http://localhost:8000/recommend?query=gift2"
# Each IP should have independent limits
```

### Test 3: Hit the limit
```bash
# Make ~25 requests (each uses ~400-500 tokens)
for i in {1..25}; do
  curl "http://localhost:8000/recommend?query=gift$i"
  sleep 0.5
done
# Should eventually return 429 Too Many Requests
```

### Test 4: Check reset
```bash
# After hitting limit, wait 1 hour or clear database:
sqlite3 giftai.db "DELETE FROM token_usage WHERE ip_address='127.0.0.1';"

# Then try again:
curl "http://localhost:8000/recommend?query=test"
# Should work again
```

## Troubleshooting

**Problem: Rate limiting not working**
- Restart server to load new code
- Check logs for "Recommendation request from IP: ..."
- Verify database has token_usage table: `sqlite3 giftai.db ".tables"`

**Problem: Wrong IP being tracked**
- If behind proxy, ensure X-Forwarded-For header is set
- Check server logs to see what IP is captured

**Problem: Tokens not being recorded**
- Check server logs for "Recorded X tokens for IP: ..."
- Verify OpenAI API is returning usage data

## Architecture

```
Request → Rate Limit Check → Process Request → Record Usage
          ↓ (if over limit)
          Return 429 Error
```

**Key Components:**
- `check_rate_limit_dependency()` - Pre-request validation
- `generate_gift_response()` - Returns token count from OpenAI
- `record_token_usage()` - Saves usage to database
- `TokenUsage` table - Stores all token consumption

## Next Steps

After verifying it works:

1. **Production Deploy**: Just deploy the updated code - database will auto-initialize
2. **Monitor Usage**: Check logs and database regularly
3. **Adjust Limits**: Modify environment variables if needed
4. **Add Cleanup**: Optionally schedule cleanup of old records

## Full Documentation

See `RATE_LIMITING_SETUP.md` for complete documentation including:
- Detailed testing procedures
- Performance considerations
- Future enhancement ideas
- Complete API reference
