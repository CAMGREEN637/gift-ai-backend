# Admin Product Management System - User Guide

## 🎯 Overview

The Admin Product Management System allows you to easily add products to your Gift-AI database by:
1. **Fetching product details from Amazon** (automatic scraping)
2. **AI-powered smart categorization** (using GPT-4)
3. **Manual review and editing** (full control over all attributes)
4. **One-click save** (to Supabase database)

---

## 🚀 Quick Start

### 1. Setup Database

First, run the products database schema:

```bash
# In Supabase SQL Editor, run:
cat supabase_products_schema.sql

# Or manually in Supabase dashboard:
# 1. Go to SQL Editor
# 2. Create new query
# 3. Paste contents of supabase_products_schema.sql
# 4. Run
```

This creates the `gifts` table with:
- Product information
- Categorization fields
- Quality metrics
- Full-text search indexes

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

New dependencies added:
- `beautifulsoup4` - HTML parsing for Amazon scraping
- `lxml` - Fast XML/HTML parser

### 3. Set Admin API Key

Add to your `.env` file:

```env
ADMIN_API_KEY=your-secure-admin-key-here
```

Or it will use `BACKEND_API_KEY` as fallback.

### 4. Start the Server

```bash
uvicorn app.main:app --reload --port 8000
```

### 5. Access Admin Dashboard

Open in your browser:
```
http://localhost:8000/admin/products
```

You'll be prompted for the API key on first load.

---

## 📝 How to Add Products

### Step 1: Fetch Amazon Product

1. Copy any Amazon product URL (e.g., `https://www.amazon.com/dp/B08N5WRWNW`)
2. Paste into the "Amazon Product URL" field
3. Click "Fetch Product Details"

**What happens:**
- ASIN is extracted from URL
- Product page is scraped for:
  - Product name
  - Price
  - Brand
  - Description
  - Image URL
  - Rating & review count
  - Stock status
- Product preview is displayed with quality indicators

### Step 2: AI Categorization

1. Click "Suggest Categories with AI"
2. Wait 5-10 seconds for OpenAI to analyze

**What the AI suggests:**
- **Categories** (max 2): Primary product categories
- **Interests** (max 5): User interests this gift matches
- **Occasions** (max 4): Suitable gift-giving occasions
- **Gender**: Male, Female, or Unisex
- **Relationship**: Partner, Friend, Family, etc.
- **Vibe** (max 3): Gift mood (romantic, practical, luxury, etc.)
- **Personality Traits** (max 3): Matching personality types
- **Experience Level**: Beginner, Enthusiast, or Expert

### Step 3: Review & Edit

The form is pre-filled with fetched data and AI suggestions. Review and edit:

**Basic Information:**
- Product Name *(required)*
- Description
- Brand
- Price *(required)*
- Currency (USD, EUR, GBP)
- Product Link
- Image URL
- Source (Amazon, Etsy, Walmart, Other)

**Categorization:**
All multi-select fields show:
- Current selection count (e.g., "2/5 selected")
- Warning when limit reached
- Auto-disable when max reached

**Validation:**
- Cannot exceed max limits on multi-select fields
- Price must be non-negative
- Required fields must be filled

### Step 4: Save

1. Review all fields
2. Click "Save Product"
3. Product is saved with auto-generated ID (`gift_0001`, `gift_0002`, etc.)
4. Success message shows the product ID

**Product is now:**
- ✅ Saved in Supabase `gifts` table
- ✅ Indexed for search
- ✅ Available for recommendations

---

## 🎨 Quality Indicators

Products show visual quality indicators:

### Rating Status
- ✅ **Green (Excellent)**: Rating ≥ 4.0 stars
- ⚠️ **Yellow (Warning)**: Rating 3.0-3.9 stars
- ❌ **Red (Poor)**: Rating < 3.0 stars

### Review Count Status
- ✅ **Green (Excellent)**: ≥ 50 reviews
- ⚠️ **Yellow (Warning)**: 10-49 reviews
- ❌ **Red (Poor)**: < 10 reviews

### Stock Status
- ✅ **Green**: In Stock
- ❌ **Red**: Out of Stock

**Use quality indicators to:**
- Filter high-quality products
- Identify products needing more reviews
- Skip out-of-stock items

---

## 📊 API Endpoints

### Product Management

**Fetch Amazon Product**
```http
POST /admin/api/fetch-amazon
Headers: X-API-Key: your-key
Body: {"url": "https://amazon.com/dp/B08N5WRWNW"}
```

**AI Categorization**
```http
POST /admin/api/categorize
Headers: X-API-Key: your-key
Body: {
  "name": "Product Name",
  "description": "Description",
  "brand": "Brand"
}
```

**Save Product**
```http
POST /admin/api/products
Headers: X-API-Key: your-key
Body: {
  "product": { /* GiftProduct object */ },
  "created_by": "admin"
}
```

**List Products**
```http
GET /admin/api/products?page=1&page_size=20
Headers: X-API-Key: your-key
```

**Get Product**
```http
GET /admin/api/products/{product_id}
Headers: X-API-Key: your-key
```

**Update Product**
```http
PUT /admin/api/products/{product_id}
Headers: X-API-Key: your-key
Body: { /* Updated fields */ }
```

**Delete Product**
```http
DELETE /admin/api/products/{product_id}
Headers: X-API-Key: your-key
```

**Get Statistics**
```http
GET /admin/api/stats
Headers: X-API-Key: your-key
```

---

## 🔍 Field Reference

### Categories (Max 2)
Choose from:
- `tech` - Technology products
- `home` - Home decor & furniture
- `kitchen` - Kitchen gadgets & cookware
- `fashion` - Clothing & accessories
- `beauty` - Beauty & skincare
- `fitness` - Fitness equipment
- `outdoors` - Outdoor & camping gear
- `hobby` - Hobby & craft supplies
- `book` - Books & reading
- `experiences` - Experience gifts

### Interests (Max 5)
Choose from:
- `coffee`, `cooking`, `baking`
- `fitness`, `running`, `yoga`
- `gaming`, `photography`, `music`
- `travel`, `reading`, `art`
- `gardening`, `cycling`, `hiking`, `camping`
- `movies`, `wine`, `cocktails`, `tea`
- `fashion`, `skincare`, `makeup`

### Occasions (Max 4)
- `birthday`, `anniversary`, `valentines`
- `holiday`, `christmas`
- `wedding`, `engagement`, `graduation`
- `just_because`

### Gender
- `male`, `female`, `unisex`

### Relationship
- `partner`, `spouse`, `boyfriend`, `girlfriend`
- `friend`, `family`

### Vibe (Max 3)
- `romantic`, `practical`, `luxury`
- `fun`, `sentimental`, `creative`
- `cozy`, `adventurous`, `minimalist`

### Personality Traits (Max 3)
- `introverted`, `extroverted`
- `analytical`, `creative`
- `sentimental`, `adventurous`
- `organized`, `relaxed`, `curious`

### Experience Level
- `beginner` - For newcomers
- `enthusiast` - For hobbyists
- `expert` - For professionals

---

## 🛠️ Troubleshooting

### "Could not extract ASIN from URL"
**Problem:** Invalid Amazon URL format

**Solution:**
- Use full Amazon product URL
- Must contain `/dp/` or `/gp/product/` with ASIN
- Example: `https://www.amazon.com/dp/B08N5WRWNW`

### "Failed to fetch product page"
**Problem:** Amazon blocked the request or product unavailable

**Solution:**
- Check if product is still available on Amazon
- Try again in a few seconds (rate limiting)
- If persists, manually enter product details

### "Categorization failed"
**Problem:** OpenAI API error or invalid response

**Solution:**
- Check `OPENAI_API_KEY` is set correctly
- AI suggestions will default to safe values
- You can still manually categorize

### "Rate limit exceeded"
**Problem:** Too many products added too quickly

**Solution:**
- Wait a few minutes between batches
- Increase `HOURLY_TOKEN_LIMIT` in `.env` if needed

### "Unauthorized - Invalid API key"
**Problem:** Wrong or missing admin API key

**Solution:**
- Check `ADMIN_API_KEY` in `.env`
- Re-enter API key when prompted
- Refresh the page

---

## 🎯 Best Practices

### Product Selection
✅ **Do:**
- Choose well-reviewed products (rating ≥ 4.0)
- Select products with ≥ 50 reviews
- Verify products are in stock
- Pick diverse price ranges
- Cover multiple interests

❌ **Don't:**
- Add out-of-stock items
- Include poorly reviewed products (< 3.0 stars)
- Duplicate existing products
- Select very niche/specialized items (unless targeting specific users)

### Categorization
✅ **Do:**
- Be selective - fewer is better
- Choose only the MOST relevant categories
- Think about who would actually use this
- Consider typical gift-giving scenarios
- Match experience level to product complexity

❌ **Don't:**
- Max out all fields "just in case"
- Add irrelevant interests
- Over-categorize simple products
- Ignore AI suggestions without reason

### Quality Control
- **Review AI suggestions** - AI is usually good but not perfect
- **Check descriptions** - Ensure they're accurate and helpful
- **Verify pricing** - Prices change, update if needed
- **Test images** - Ensure image URLs work
- **Validate links** - Product links should be clean and working

---

## 📈 Performance Tips

### Batch Processing
- Add products in batches of 10-20
- Wait ~10 seconds between batches (rate limiting)
- Use quality indicators to prioritize

### Search Optimization
Products are automatically indexed for:
- Full-text search on name, description, brand
- JSONB array searches on categories, interests, etc.
- Fast filtering by price, rating, stock status

### Database Management
- Products are immutable once saved (update via API)
- IDs are auto-generated sequentially
- Created/updated timestamps are automatic
- No cleanup needed - indexes handle performance

---

## 🔐 Security

### API Key Protection
- **Never commit** `.env` to git
- **Use strong keys** (random, 32+ characters)
- **Rotate periodically** (every 3-6 months)
- **Separate keys** for dev/staging/prod

### Admin Access
- Admin dashboard requires API key
- No user registration needed
- Single admin key for entire team
- Logs all product additions

### Data Validation
- All inputs are validated server-side
- Array limits enforced at database level
- SQL injection protected (parameterized queries)
- XSS protected (no HTML in stored data)

---

## 📚 Examples

### Example 1: Adding a Coffee Maker

1. **Fetch**: `https://www.amazon.com/dp/B08N5WRWNW`
2. **AI Suggests**:
   - Categories: `["kitchen", "home"]`
   - Interests: `["coffee", "cooking"]`
   - Occasions: `["birthday", "holiday", "just_because"]`
   - Gender: `["unisex"]`
   - Relationship: `["partner", "friend", "family"]`
   - Vibe: `["practical", "luxury"]`
   - Traits: `["organized"]`
   - Experience: `"enthusiast"`
3. **Review**: Looks good!
4. **Save**: `gift_0042` created

### Example 2: Adding a Yoga Mat

1. **Fetch**: `https://www.amazon.com/dp/B01L8KVC4I`
2. **AI Suggests**:
   - Categories: `["fitness", "outdoors"]`
   - Interests: `["yoga", "fitness"]`
   - Occasions: `["birthday", "just_because"]`
   - Gender: `["unisex"]`
   - Relationship: `["friend", "family"]`
   - Vibe: `["practical", "minimalist"]`
   - Traits: `["organized", "relaxed"]`
   - Experience: `"beginner"`
3. **Edit**: Add "holiday" to occasions
4. **Save**: `gift_0043` created

---

## 🆘 Support

### Getting Help
1. Check this guide first
2. Review error messages in browser console
3. Check server logs for API errors
4. Verify environment variables are set

### Common Issues
- **Database errors**: Check Supabase connection
- **Scraping fails**: Amazon may be blocking, try different product
- **AI errors**: Verify OpenAI API key and credits
- **Save fails**: Check all required fields are filled

### Reporting Bugs
When reporting issues, include:
- Error message (full text)
- Product URL you were trying to add
- Browser console logs
- Server logs (if available)

---

## ✅ Checklist

Before adding products to production:

- [ ] Database schema created in Supabase
- [ ] Admin API key set in `.env`
- [ ] OpenAI API key configured
- [ ] Server running without errors
- [ ] Can access `/admin/products` page
- [ ] Successfully fetched test product
- [ ] AI categorization working
- [ ] Can save products
- [ ] Products visible in Supabase table editor

---

**Happy product adding! 🎁**

*For technical details, see the source code in `app/admin_*.py` files*
