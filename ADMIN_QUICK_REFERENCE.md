# Admin System - Quick Reference Card

## 🚀 Setup (One Time)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run database schema in Supabase SQL Editor
# Copy & paste contents of supabase_products_schema.sql

# 3. Add to .env
ADMIN_API_KEY=your-admin-key
OPENAI_API_KEY=your-openai-key

# 4. Start server
uvicorn app.main:app --reload --port 8000

# 5. Open browser
http://localhost:8000/admin/products
```

---

## 💻 Daily Usage

### Adding a Product

1. **Paste Amazon URL** → Click "Fetch"
2. **Review scraped data** → Click "Suggest Categories"
3. **Review AI suggestions** → Edit as needed
4. **Click "Save Product"** → Done!

### Quality Checks

- ✅ Green = Good (rating ≥4.0, reviews ≥50)
- ⚠️ Yellow = Warning (rating 3-4, reviews 10-50)
- ❌ Red = Poor (rating <3, reviews <10, out of stock)

---

## 📝 Field Limits

| Field | Max | Examples |
|-------|-----|----------|
| Categories | 2 | tech, home |
| Interests | 5 | coffee, cooking, gaming |
| Occasions | 4 | birthday, holiday |
| Vibe | 3 | practical, luxury |
| Traits | 3 | creative, organized |

---

## 🔧 API Quick Reference

```bash
# Fetch Amazon product
curl -X POST http://localhost:8000/admin/api/fetch-amazon \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://amazon.com/dp/B123456789"}'

# AI Categorization
curl -X POST http://localhost:8000/admin/api/categorize \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"name": "Product", "description": "...", "brand": "..."}'

# Save Product
curl -X POST http://localhost:8000/admin/api/products \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"product": {...}, "created_by": "admin"}'

# List Products
curl http://localhost:8000/admin/api/products?page=1 \
  -H "X-API-Key: your-key"

# Get Product
curl http://localhost:8000/admin/api/products/gift_0001 \
  -H "X-API-Key: your-key"

# Stats
curl http://localhost:8000/admin/api/stats \
  -H "X-API-Key: your-key"
```

---

## 🐛 Common Issues

| Issue | Solution |
|-------|----------|
| "Could not extract ASIN" | Use full Amazon URL with /dp/ |
| "Failed to fetch" | Product unavailable or Amazon blocked |
| "Categorization failed" | Check OPENAI_API_KEY |
| "Unauthorized" | Check ADMIN_API_KEY in .env |
| Limit warning | Uncheck some items before selecting more |

---

## 📁 Important Files

| File | Purpose |
|------|---------|
| `ADMIN_SYSTEM_GUIDE.md` | Full user manual |
| `ADMIN_SYSTEM_SUMMARY.md` | Technical documentation |
| `ADMIN_QUICK_REFERENCE.md` | This cheat sheet |
| `supabase_products_schema.sql` | Database schema |
| `app/static/admin.html` | Dashboard interface |

---

## ✅ Best Practices

### Do ✅
- Choose products with rating ≥ 4.0
- Ensure ≥ 50 reviews
- Verify in stock
- Be selective with categories
- Review AI suggestions

### Don't ❌
- Add out-of-stock items
- Max out all category fields
- Ignore quality indicators
- Skip manual review
- Add duplicate products

---

## 🎯 Recommended Workflow

1. **Batch Products**: Prepare 10-20 URLs
2. **Fetch & Review**: One at a time
3. **Quality Check**: Use indicators
4. **AI Categorize**: Let AI suggest
5. **Manual Refine**: Edit as needed
6. **Save**: Submit to database
7. **Verify**: Check Supabase table

---

## 🔐 Security Reminders

- Never commit `.env` to git
- Rotate API keys every 3-6 months
- Use different keys for dev/prod
- Keep ADMIN_API_KEY private
- Only share with trusted team members

---

## 📊 Database Access

### Supabase Dashboard
```
https://app.supabase.com
→ Select Project
→ Table Editor
→ gifts table
```

### SQL Queries
```sql
-- Count products
SELECT COUNT(*) FROM gifts;

-- In stock products
SELECT COUNT(*) FROM gifts WHERE in_stock = true;

-- By category
SELECT categories, COUNT(*)
FROM gifts
GROUP BY categories;

-- Recent additions
SELECT id, name, created_at
FROM gifts
ORDER BY created_at DESC
LIMIT 10;

-- High quality products
SELECT id, name, rating, review_count
FROM gifts
WHERE rating >= 4.0 AND review_count >= 50
ORDER BY rating DESC, review_count DESC;
```

---

## 🎉 Quick Stats

After setup, you can:
- ✅ Add ~6-10 products per hour
- ✅ Build 100-product catalog in 1-2 days
- ✅ Scale to 1000+ products easily
- ✅ Power accurate gift recommendations

---

**Need more details?** → See `ADMIN_SYSTEM_GUIDE.md`

**Having issues?** → Check troubleshooting section in guide

**Ready to start?** → Open http://localhost:8000/admin/products
