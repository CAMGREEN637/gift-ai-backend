# Supabase Setup Guide

This guide walks you through setting up Supabase for the Gift-AI backend.

## 📋 Prerequisites

- Supabase account (sign up at https://supabase.com)
- Python 3.8+
- Git (for version control)

## 🚀 Step-by-Step Setup

### 1. Create Supabase Project

1. Go to https://app.supabase.com
2. Click "New Project"
3. Fill in project details:
   - **Name**: `gift-ai-backend` (or your preferred name)
   - **Database Password**: Create a strong password (save this!)
   - **Region**: Choose closest to your users
   - **Pricing Plan**: Start with Free tier
4. Click "Create new project"
5. Wait 2-3 minutes for setup to complete

### 2. Run Database Schema

1. In your Supabase dashboard, go to **SQL Editor** (left sidebar)
2. Click "New query"
3. Copy the entire contents of `supabase_schema.sql` from this project
4. Paste into the SQL editor
5. Click "Run" or press `Ctrl/Cmd + Enter`
6. You should see: "Success. No rows returned"

**Verify tables were created:**
- Go to **Table Editor** (left sidebar)
- You should see 4 tables:
  - `user_preferences`
  - `feedback`
  - `inferred_preferences`
  - `token_usage`

### 3. Get API Credentials

1. Go to **Project Settings** → **API** (gear icon in sidebar)
2. Find two important values:

   **A. Project URL**
   ```
   URL: https://xxxxxxxxxxx.supabase.co
   ```
   Copy this - you'll need it for `SUPABASE_URL`

   **B. Service Role Key** (Secret)
   - Scroll down to "Project API keys"
   - Find the `service_role` key (NOT the `anon` key)
   - Click "Reveal" and copy
   - ⚠️ **KEEP THIS SECRET** - it bypasses Row Level Security

### 4. Configure Environment Variables

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your credentials:
   ```env
   SUPABASE_URL=https://your-project-id.supabase.co
   SUPABASE_SERVICE_KEY=your-service-role-key-here
   OPENAI_API_KEY=your-openai-api-key
   ```

3. **IMPORTANT**: Make sure `.env` is in your `.gitignore`:
   ```bash
   echo ".env" >> .gitignore
   ```

### 5. Install Dependencies

```bash
pip install -r requirements.txt
```

This will install:
- `supabase` - Supabase Python client
- `python-dotenv` - Environment variable management
- Other existing dependencies

### 6. Test Database Connection

Create a test script `test_supabase.py`:

```python
from app.database import get_supabase, init_db

try:
    init_db()
    print("✅ Database connection successful!")

    # Test a simple query
    supabase = get_supabase()
    result = supabase.table("user_preferences").select("*").limit(1).execute()
    print("✅ Tables are accessible!")

except Exception as e:
    print(f"❌ Error: {str(e)}")
```

Run it:
```bash
python test_supabase.py
```

Expected output:
```
✅ Database connection successful!
✅ Table 'user_preferences' is accessible
✅ Table 'feedback' is accessible
✅ Table 'inferred_preferences' is accessible
✅ Table 'token_usage' is accessible
✅ Tables are accessible!
```

### 7. Start the Server

```bash
uvicorn app.main:app --reload --port 8000
```

Check the logs for:
```
INFO:app.database:Supabase client initialized successfully
INFO:app.database:Database connection verified
INFO:app.database:✓ Table 'user_preferences' is accessible
...
```

### 8. Test API Endpoints

**Test health check:**
```bash
curl http://localhost:8000/
```

Expected: `{"status": "ok"}`

**Test recommendation (will fail without gift data):**
```bash
curl "http://localhost:8000/recommend?query=tech%20gift"
```

**Test preferences:**
```bash
curl -X POST http://localhost:8000/preferences \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test-user-123",
    "interests": ["technology", "gaming"],
    "vibe": ["modern", "innovative"]
  }'
```

Expected: `{"status": "saved"}`

**Verify in Supabase:**
- Go to **Table Editor** → `user_preferences`
- You should see the test user's data

## 🔍 Troubleshooting

### Error: "Supabase credentials not found"

**Problem:** Environment variables not loaded

**Solution:**
1. Verify `.env` file exists in project root
2. Check variable names match exactly: `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`
3. Restart the server after changing `.env`

### Error: "Failed to initialize Supabase client"

**Problem:** Invalid credentials or URL

**Solution:**
1. Double-check `SUPABASE_URL` is correct (should end in `.supabase.co`)
2. Verify you're using the `service_role` key, not `anon` key
3. Check for extra spaces or quotes in `.env` file

### Error: "Table does not exist"

**Problem:** Schema not created properly

**Solution:**
1. Go to Supabase **SQL Editor**
2. Re-run `supabase_schema.sql`
3. Check **Table Editor** to verify tables exist
4. Ensure Row Level Security policies were created

### Error: "Permission denied"

**Problem:** Using `anon` key instead of `service_role` key

**Solution:**
1. Go to **Project Settings** → **API**
2. Find the `service_role` key (scroll down)
3. Update `SUPABASE_SERVICE_KEY` in `.env`

### Server starts but queries fail

**Problem:** Possibly RLS (Row Level Security) blocking queries

**Solution:**
1. Verify you're using the `service_role` key
2. Check RLS policies in Supabase **Authentication** → **Policies**
3. The schema includes policies that allow all operations with service role

## 📊 Verifying Data

### View data in Supabase Dashboard

1. **Table Editor**: Browse data in GUI
   - Go to **Table Editor**
   - Select a table
   - View/edit rows directly

2. **SQL Editor**: Run queries
   ```sql
   -- View all users
   SELECT * FROM user_preferences;

   -- View recent feedback
   SELECT * FROM feedback ORDER BY created_at DESC LIMIT 10;

   -- Check rate limiting
   SELECT ip_address, SUM(tokens_used) as total
   FROM token_usage
   WHERE timestamp > NOW() - INTERVAL '1 hour'
   GROUP BY ip_address;
   ```

## 🔐 Security Best Practices

### ✅ Do's

- ✅ Use `service_role` key only in backend (server-side)
- ✅ Keep `.env` in `.gitignore`
- ✅ Use different projects for dev/staging/production
- ✅ Rotate keys periodically
- ✅ Enable RLS on all tables
- ✅ Use environment variables, never hardcode keys

### ❌ Don'ts

- ❌ Never commit `.env` to Git
- ❌ Never use `service_role` key in frontend/client
- ❌ Never share service role key publicly
- ❌ Don't disable RLS without good reason
- ❌ Don't use same credentials across environments

## 🚢 Production Deployment

### Environment Variables

Set these on your production platform (Railway, Heroku, etc.):

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-production-service-role-key
OPENAI_API_KEY=your-openai-key
HOURLY_TOKEN_LIMIT=10000
RATE_LIMIT_WINDOW=3600
```

### Separate Environments

**Recommended**: Create separate Supabase projects for:
- **Development** (dev-gift-ai)
- **Staging** (staging-gift-ai)
- **Production** (gift-ai)

### Database Backups

Supabase automatically backs up your database daily on Pro plan.

Free tier:
- Manual backups via **Database** → **Backups**
- Export tables to CSV periodically

## 📈 Monitoring

### Supabase Dashboard

- **Database**: Monitor query performance
- **API**: Track API usage and errors
- **Logs**: View real-time logs
- **Reports**: See usage statistics (Pro plan)

### Application Logs

Check your application logs for:
```
INFO:app.database:Supabase client initialized successfully
INFO:app.persistence:Saved feedback for user ...
WARNING:app.dependencies:Rate limit exceeded for IP: ...
```

## 🔄 Migration from SQLite

If you have existing SQLite data to migrate:

### Option 1: Manual Migration (Small datasets)

1. Export from SQLite:
```bash
sqlite3 giftai.db .dump > data_dump.sql
```

2. Convert to PostgreSQL format (manual editing needed)
3. Import via Supabase SQL Editor

### Option 2: Python Script (Recommended)

Create `migrate_to_supabase.py`:

```python
import sqlite3
from app.database import get_supabase

# Connect to old SQLite DB
sqlite_conn = sqlite3.connect('giftai.db')
sqlite_conn.row_factory = sqlite3.Row
cursor = sqlite_conn.cursor()

# Get Supabase client
supabase = get_supabase()

# Migrate user preferences
cursor.execute("SELECT * FROM user_preferences")
for row in cursor.fetchall():
    data = dict(row)
    supabase.table("user_preferences").insert(data).execute()
    print(f"Migrated user: {data['user_id']}")

# Migrate feedback
cursor.execute("SELECT * FROM feedback")
for row in cursor.fetchall():
    data = dict(row)
    supabase.table("feedback").insert(data).execute()

# ... repeat for other tables

print("Migration complete!")
```

Run:
```bash
python migrate_to_supabase.py
```

## 🆘 Support

- **Supabase Docs**: https://supabase.com/docs
- **Supabase Discord**: https://discord.supabase.com
- **Python Client**: https://github.com/supabase/supabase-py

## ✅ Checklist

Before going live, verify:

- [ ] Supabase project created
- [ ] All tables created via `supabase_schema.sql`
- [ ] RLS policies configured
- [ ] Environment variables set in `.env`
- [ ] `.env` added to `.gitignore`
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Database connection tested (`python test_supabase.py`)
- [ ] Server starts without errors
- [ ] API endpoints working
- [ ] Data being saved to Supabase (check Table Editor)
- [ ] Rate limiting functional
- [ ] Production environment variables configured
- [ ] Separate project for production (recommended)

## 🎉 You're Done!

Your Gift-AI backend is now powered by Supabase!

**Next steps:**
- Add more gift data to your vector store
- Test rate limiting thoroughly
- Set up monitoring and alerts
- Configure production deployment
- Enable database backups

For questions or issues, check the troubleshooting section or Supabase documentation.
