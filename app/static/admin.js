// Admin Dashboard JavaScript

// Configuration
const API_BASE = '/admin/api';
const API_KEY = prompt('Enter Admin API Key:') || ''; // Simple auth prompt

// Global state
let currentProduct = null;
let isManualEntry = false; // Track whether we're in manual mode

// ============================================
// Constants for multi-select options
// All values here are locked to the quiz vocabulary in quizRules.ts
// and retrieval.py. Do not add values that don't exist in both places —
// unrecognized tags silently do nothing at retrieval time.
// ============================================

const OPTIONS = {
    // gift_type — matches GIFT_TYPE_META keys in quizRules.ts
    // NOTE: 'fashion' kept for legacy re-tagging only; avoid using on new products
    categories: [
        "tech",
        "kitchen",
        "home",
        "fitness",
        "beauty",
        "outdoors",
        "book",
        "hobby",
        "jewelry",       // ← added (was missing, causes scoring gaps on Valentine's/anniversary)
        "loungewear",    // ← added (was missing, causes scoring gaps on Valentine's/anniversary)
        "fashion",       // ← legacy only; 6 existing products use this; avoid on new products
    ],

    // interests — matches InterestKey in quizRules.ts
    interests: [
        "coffee",
        "cooking",
        "baking",
        "wine",
        "cocktails",
        "fitness",
        "running",
        "cycling",
        "yoga",
        "reading",
        "music",
        "gaming",
        "photography",
        "art",
        "travel",
        "hiking",
        "camping",
        "gardening",
        "movies",
        "fashion",
        "skincare",
        "makeup",
        "wellness",      // ← added (was missing)
        "home_decor",    // ← added (was missing)
        "pets",          // ← added (was missing)
        // REMOVED: "tea" — not in quiz vocabulary, never matches
    ],

    // occasions — matches OccasionKey in quizRules.ts + retrieval.py
    occasions: [
        "birthday",
        "valentines",
        "anniversary",
        "christmas",
        "mothers_day",
        "just_because",
        "apology",       // ← added (was missing — one of 7 core occasions)
        // REMOVED: "holiday", "wedding", "engagement", "graduation"
        // These are not in the quiz vocabulary and never match retrieval queries
    ],

    gender: ["male", "female", "unisex"],

    // vibe — matches VibeKey in quizRules.ts
    vibe: [
        "romantic",
        "sentimental",
        "pampering",     // ← added (was missing)
        "luxe",          // ← renamed from "luxury" (correct key is "luxe")
        "cozy",
        "fun",
        "thoughtful",    // ← added (was missing)
        // REMOVED: "practical", "luxury", "creative", "adventurous", "minimalist"
        // None of these exist in the quiz vocabulary
    ],
};

const LIMITS = {
    categories: 3,   // bumped from 2 — existing gifts use up to 3 gift_types
    interests:  5,
    occasions:  6,   // bumped from 4 — DB constraint allows 6 (validate_gift_arrays)
    vibe:       3,
};

// ============================================
// Utility Functions
// ============================================

function showAlert(message, type = 'info') {
    const alert = document.getElementById('alert');
    alert.className = `alert alert-${type} show`;
    alert.textContent = message;

    setTimeout(() => {
        alert.className = 'alert';
    }, 5000);
}

function showLoading(elementId, show = true) {
    const loading = document.getElementById(elementId);
    if (loading) {
        loading.classList.toggle('active', show);
    }
}

async function apiRequest(endpoint, method = 'GET', body = null) {
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json',
            'X-API-Key': API_KEY
        }
    };

    if (body) {
        options.body = JSON.stringify(body);
    }

    const response = await fetch(`${API_BASE}${endpoint}`, options);

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Request failed');
    }

    return response.json();
}

// ============================================
// Step 1a: Fetch Amazon Product
// ============================================

async function fetchAmazonProduct() {
    const url = document.getElementById('amazonUrl').value;

    if (!url) {
        showAlert('Please enter an Amazon URL', 'error');
        return;
    }

    showLoading('fetchLoading', true);
    document.getElementById('fetchBtn').disabled = true;

    try {
        const product = await apiRequest('/fetch-amazon', 'POST', { url });

        currentProduct = product;
        isManualEntry = false;

        displayProductPreview(product);

        document.getElementById('categorizationSection').style.display = 'block';

        showAlert('Product fetched successfully!', 'success');
    } catch (error) {
        showAlert(`Error: ${error.message}`, 'error');
    } finally {
        showLoading('fetchLoading', false);
        document.getElementById('fetchBtn').disabled = false;
    }
}

function displayProductPreview(product) {
    const preview = document.getElementById('productPreview');

    const qualityHTML = getQualityIndicators(product);

    preview.innerHTML = `
        <div class="product-preview">
            <div>
                ${product.image_url ? `<img src="${product.image_url}" alt="${product.name}" />` : '<div style="background:#ddd; width:150px; height:150px; display:flex; align-items:center; justify-content:center;">No Image</div>'}
            </div>
            <div class="preview-details">
                <h3>${product.name}</h3>
                <p><strong>Brand:</strong> ${product.brand || 'N/A'}</p>
                <p><strong>Price:</strong> $${product.price || 'N/A'}</p>
                <p><strong>ASIN:</strong> ${product.asin || 'N/A'}</p>
                <p><strong>Description:</strong> ${product.description ? product.description.substring(0, 200) + '...' : 'N/A'}</p>
                <div style="margin-top: 10px;">
                    ${qualityHTML}
                </div>
            </div>
        </div>
    `;

    preview.style.display = 'block';
}

function getQualityIndicators(product) {
    let html = '';

    if (product.rating) {
        const ratingClass = product.rating >= 4.0 ? 'excellent' : product.rating >= 3.0 ? 'warning' : 'poor';
        html += `<span class="quality-indicator quality-${ratingClass}">⭐ ${product.rating}/5</span>`;
    }

    if (product.review_count !== undefined) {
        const reviewClass = product.review_count >= 50 ? 'excellent' : product.review_count >= 10 ? 'warning' : 'poor';
        html += `<span class="quality-indicator quality-${reviewClass}">💬 ${product.review_count} reviews</span>`;
    }

    const stockClass = product.in_stock ? 'excellent' : 'poor';
    const stockText = product.in_stock ? '✓ In Stock' : '✗ Out of Stock';
    html += `<span class="quality-indicator quality-${stockClass}">${stockText}</span>`;

    return html;
}

// ============================================
// Step 1b: Manual Entry
// ============================================

function addManually() {
    isManualEntry = true;
    currentProduct = null;

    document.getElementById('productPreview').style.display = 'none';

    populateProductForm(null, null);

    document.getElementById('productForm').style.display = 'block';
    document.getElementById('categorizationSection').style.display = 'block';

    document.getElementById('formTitle').textContent = 'Add Product Details';
    const badge = document.getElementById('modeBadge');
    badge.textContent = '✏️ Manual Entry';
    badge.className = 'mode-badge mode-badge-manual';
    badge.style.display = 'inline-block';

    showAlert("Fill in the product details below. You can still use AI to suggest categories once you've entered a name and description.", 'info');

    document.getElementById('productForm').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ============================================
// Step 2: AI Categorization
// ============================================

async function categorizeProduct() {
    const name = isManualEntry
        ? document.getElementById('productName').value
        : currentProduct?.name;

    const description = isManualEntry
        ? document.getElementById('description').value
        : currentProduct?.description || '';

    const brand = isManualEntry
        ? document.getElementById('brand').value
        : currentProduct?.brand || '';

    if (!name) {
        showAlert('Please enter a product name before requesting AI categorization', 'error');
        return;
    }

    showLoading('categorizeLoading', true);
    document.getElementById('categorizeBtn').disabled = true;

    try {
        const categorization = await apiRequest('/categorize', 'POST', {
            name,
            description,
            brand
        });

        applyCategorizationToForm(categorization);

        showAlert('AI categorization applied! Review and adjust as needed.', 'success');
    } catch (error) {
        showAlert(`Categorization error: ${error.message}`, 'error');
    } finally {
        showLoading('categorizeLoading', false);
        document.getElementById('categorizeBtn').disabled = false;
    }
}

// ============================================
// Step 3: Product Form
// ============================================

function populateProductForm(product, categorization) {
    document.getElementById('productName').value = product?.name || '';
    document.getElementById('displayName').value = product?.display_name || '';
    document.getElementById('description').value = product?.description || '';
    document.getElementById('brand').value = product?.brand || '';
    document.getElementById('price').value = product?.price || '';
    document.getElementById('currency').value = product?.currency || 'USD';
    document.getElementById('link').value = product?.link || product?.product_url || '';
    document.getElementById('imageUrl').value = product?.image_url || '';
    document.getElementById('source').value = product?.source || 'amazon';
    document.getElementById('rating').value = product?.rating || '';
    document.getElementById('reviewCount').value = product?.review_count || '';
    document.getElementById('inStock').checked = product?.in_stock !== false;

    if (!isManualEntry && product) {
        document.getElementById('formTitle').textContent = 'Step 3: Review & Edit Product Details';
        const badge = document.getElementById('modeBadge');
        badge.textContent = '✅ Amazon Scraped';
        badge.className = 'mode-badge mode-badge-scraped';
        badge.style.display = 'inline-block';
    }

    initMultiSelect('categories', OPTIONS.categories, LIMITS.categories);
    initMultiSelect('interests', OPTIONS.interests, LIMITS.interests);
    initMultiSelect('occasions', OPTIONS.occasions, LIMITS.occasions);
    initMultiSelect('gender', OPTIONS.gender);
    initMultiSelect('vibe', OPTIONS.vibe, LIMITS.vibe);

    if (categorization) {
        applyCategorizationToForm(categorization);
    }

    document.getElementById('editForm').onsubmit = saveProduct;
}

function applyCategorizationToForm(categorization) {
    setMultiSelectValues('categories', categorization.categories || []);
    setMultiSelectValues('interests', categorization.interests || []);
    setMultiSelectValues('occasions', categorization.occasions || []);
    setMultiSelectValues('gender', categorization.recipient?.gender || []);
    setMultiSelectValues('vibe', categorization.vibe || []);
    if (categorization.experience_level) {
        const el = document.getElementById('experienceLevel');
        if (el) el.value = categorization.experience_level;
    }
}

function initMultiSelect(fieldName, options, maxLimit = null) {
    const container = document.getElementById(`${fieldName}Container`);
    if (!container) return;
    container.innerHTML = '';

    options.forEach(option => {
        const div = document.createElement('div');
        div.className = 'checkbox-item';

        // Flag legacy-only options visually
        const isLegacy = fieldName === 'categories' && option === 'fashion';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.id = `${fieldName}_${option}`;
        checkbox.value = option;
        checkbox.onchange = () => {
            if (maxLimit) {
                updateLimitIndicator(fieldName, maxLimit);
            }
        };

        const label = document.createElement('label');
        label.htmlFor = `${fieldName}_${option}`;

        // Human-friendly labels for underscore keys
        const labelMap = {
            mothers_day: "Mother's Day",
            just_because: "Just Because",
            home_decor: "Candles & Home",
            home: "Home & Décor",
            loungewear: "Loungewear & Cozy",
            luxe: "Luxe",
            pampering: "Pampering",
            thoughtful: "Thoughtful",
        };
        label.textContent = labelMap[option] || option;

        if (isLegacy) {
            label.textContent += ' (legacy)';
            label.style.color = '#999';
            label.style.fontStyle = 'italic';
        }

        div.appendChild(checkbox);
        div.appendChild(label);
        container.appendChild(div);
    });

    if (maxLimit) {
        updateLimitIndicator(fieldName, maxLimit);
    }
}

function setMultiSelectValues(fieldName, values) {
    if (!values) return;
    values.forEach(value => {
        const checkbox = document.getElementById(`${fieldName}_${value}`);
        if (checkbox) {
            checkbox.checked = true;
        }
    });

    if (LIMITS[fieldName]) {
        updateLimitIndicator(fieldName, LIMITS[fieldName]);
    }
}

function getMultiSelectValues(fieldName) {
    const container = document.getElementById(`${fieldName}Container`);
    if (!container) return [];
    const checkboxes = container.querySelectorAll('input[type="checkbox"]:checked');
    return Array.from(checkboxes).map(cb => cb.value);
}

function updateLimitIndicator(fieldName, maxLimit) {
    const values = getMultiSelectValues(fieldName);
    const indicator = document.getElementById(`${fieldName}Limit`);

    if (!indicator) return;

    const count = values.length;
    indicator.textContent = `${count}/${maxLimit} selected`;

    indicator.classList.remove('warning', 'error');
    if (count === maxLimit) {
        indicator.classList.add('warning');
        const container = document.getElementById(`${fieldName}Container`);
        const checkboxes = container.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(cb => {
            if (!cb.checked) cb.disabled = true;
        });
    } else if (count > maxLimit) {
        indicator.classList.add('error');
    } else {
        const container = document.getElementById(`${fieldName}Container`);
        const checkboxes = container.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(cb => {
            cb.disabled = false;
        });
    }
}

// ============================================
// Save Product
// ============================================

async function saveProduct(event) {
    event.preventDefault();

    // Validate limits
    for (const [field, limit] of Object.entries(LIMITS)) {
        const values = getMultiSelectValues(field);
        if (values.length > limit) {
            showAlert(`${field} cannot have more than ${limit} items selected`, 'error');
            return;
        }
    }

    showLoading('saveLoading', true);
    document.getElementById('saveBtn').disabled = true;

    try {
        const ratingVal = document.getElementById('rating').value;
        const reviewCountVal = document.getElementById('reviewCount').value;

        const product = {
            name:            document.getElementById('productName').value,
            display_name:    document.getElementById('displayName').value || null,
            description:     document.getElementById('description').value,
            brand:           document.getElementById('brand').value,
            price:           parseFloat(document.getElementById('price').value),
            currency:        document.getElementById('currency').value,
            link:            document.getElementById('link').value,
            image_url:       document.getElementById('imageUrl').value,
            source:          document.getElementById('source').value,
            // 'categories' in the form maps to 'gift_type' in the DB schema
            gift_type:       getMultiSelectValues('categories'),
            interests:       getMultiSelectValues('interests'),
            occasions:       getMultiSelectValues('occasions'),
            vibe:            getMultiSelectValues('vibe'),
            gender_skew:     getMultiSelectValues('gender')[0] || 'unisex',
            rating:          ratingVal ? parseFloat(ratingVal) : (currentProduct?.rating || null),
            review_count:    reviewCountVal ? parseInt(reviewCountVal) : (currentProduct?.review_count || 0),
            in_stock:        document.getElementById('inStock').checked,
        };

        const saved = await apiRequest('/products', 'POST', {
            product: product,
            created_by: 'admin'
        });

        showAlert(`Product saved successfully! ID: ${saved.id}`, 'success');

        setTimeout(() => {
            resetForm();
        }, 2000);

    } catch (error) {
        showAlert(`Save error: ${error.message}`, 'error');
    } finally {
        showLoading('saveLoading', false);
        document.getElementById('saveBtn').disabled = false;
    }
}

function resetForm() {
    currentProduct = null;
    isManualEntry = false;
    document.getElementById('amazonUrl').value = '';
    document.getElementById('productPreview').style.display = 'none';
    document.getElementById('categorizationSection').style.display = 'none';
    document.getElementById('productForm').style.display = 'none';
    document.getElementById('modeBadge').style.display = 'none';
    document.getElementById('formTitle').textContent = 'Step 3: Review & Edit Product Details';
}

// ============================================
// Initialize on Page Load
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    console.log('Admin dashboard loaded');

    if (!API_KEY) {
        showAlert('No API key provided - some features may not work', 'warning');
    }
});