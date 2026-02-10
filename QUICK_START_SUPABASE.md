# Supabase Quick Start - 5 Minutes

Get your Gift-AI backend running with Supabase in 5 minutes.

## Prerequisites

- Supabase account (free): https://supabase.com
- Python 3.8+

## Step 1: Create Supabase Project (2 min)

1. Go to https://app.supabase.com
2. Click "New Project"
3. Name: `gift-ai` (or whatever you like)
4. Set a database password (save it!)
5. Choose a region
6. Click "Create new project"
7. Wait ~2 minutes for setup

## Step 2: Run Schema (1 min)

1. In Supabase dashboard → **SQL Editor**
2. Click "New query"
3. Copy all contents from `supabase_schema.sql`
4. Paste and click "Run"
5. Should see "Success. No rows returned"

**Verify:**
- Go to **Table Editor**
- See 4 tables: `user_preferences`, `feedback`, `inferred_preferences`, `token_usage`

## Step 3: Get Credentials (30 sec)

1. Go to **Settings** → **API**
2. Copy two values:

   **Project URL:**
   ```
   https://xxxxx.supabase.co
   ```

   **Service Role Key:** (click "Reveal")
   ```
   eyJhbGc...
   ```

## Step 4: Configure .env (30 sec)

```bash
# Copy template
cp .env.example .env

# Edit .env and add:
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGc...
OPENAI_API_KEY=sk-...
```

## Step 5: Install & Test (1 min)

```bash
# Install dependencies
pip install -r requirements.txt

# Test connection
python test_supabase.py
```

**Expected output:**
```
✓ PASS    Connection
✓ PASS    Tables
✓ PASS    Preferences
✓ PASS    Feedback
✓ PASS    Inferred Preferences
✓ PASS    Rate Limiting
✓ PASS    Health Check

✅ All tests passed!
```

## Step 6: Run Server

```bash
uvicorn app.main:app --reload --port 8000
```

**Check logs for:**
```
INFO:app.database:Supabase client initialized successfully
INFO:app.database:✓ Table 'user_preferences' is accessible
...
```

## Step 7: Test API

```bash
# Health check
curl http://localhost:8000/
# → {"status": "ok"}

# Save preferences
curl -X POST http://localhost:8000/preferences \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","interests":["tech"],"vibe":["modern"]}'
# → {"status": "saved"}
```

## ✅ You're Done!

**Verify in Supabase:**
- Go to **Table Editor** → `user_preferences`
- See your test data

## 🔄 Migrate Existing Data (Optional)

If you have SQLite data:

```bash
python migrate_to_supabase.py
```

Follows prompts to migrate all data.

## 📚 Full Documentation

- **Detailed Setup**: `SUPABASE_SETUP.md`
- **Migration Summary**: `SUPABASE_MIGRATION_SUMMARY.md`
- **Database Schema**: `supabase_schema.sql`

## ⚠️ Troubleshooting

**"Supabase credentials not found"**
- Check `.env` file exists in project root
- Verify variable names exactly match

**"Failed to initialize"**
- Double-check `SUPABASE_URL` (ends in `.supabase.co`)
- Ensure using `service_role` key (not `anon`)

**Tests failing**
- Make sure schema was created (check Table Editor)
- Verify credentials are correct
- Check specific error message

## 🎉 Success!

Your backend is now:
- ✅ Using production PostgreSQL
- ✅ Automatically backed up
- ✅ Scaling ready
- ✅ Faster and more reliable

**Next Steps:**
- Test all endpoints
- Deploy to production
- Set up monitoring

---

**Need help?** See `SUPABASE_SETUP.md` for detailed guide.
