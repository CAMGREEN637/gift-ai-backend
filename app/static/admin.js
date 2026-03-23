// Admin Dashboard JavaScript

// Configuration
const API_BASE = '/admin/api';
const API_KEY = prompt('Enter Admin API Key:') || ''; // Simple auth prompt

// Global state
let currentProduct = null;
let isManualEntry = false; // Track whether we're in manual mode

// ============================================
// Constants for multi-select options
// ============================================

const OPTIONS = {
    categories: ["tech", "home", "kitchen", "fashion", "beauty", "fitness", "outdoors", "hobby", "book", "experiences"],
    interests: ["coffee", "cooking", "baking", "fitness", "running", "yoga", "gaming", "photography", "music", "travel", "reading", "art", "gardening", "cycling", "hiking", "camping", "movies", "wine", "cocktails", "tea", "fashion", "skincare", "makeup"],
    occasions: ["birthday", "anniversary", "valentines", "mothers_day", "holiday", "christmas", "wedding", "engagement", "graduation", "just_because"],
    gender: ["male", "female", "unisex"],
    relationship: ["partner", "spouse", "boyfriend", "girlfriend", "friend", "family"],
    vibe: ["romantic", "practical", "luxury", "fun", "sentimental", "creative", "cozy", "adventurous", "minimalist"],
    traits: ["introverted", "extroverted", "analytical", "creative", "sentimental", "adventurous", "organized", "relaxed", "curious"]
};

const LIMITS = {
    categories: 2,
    interests: 5,
    occasions: 4,
    vibe: 3,
    traits: 3
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

    // Rating indicator
    if (product.rating) {
        const ratingClass = product.rating >= 4.0 ? 'excellent' : product.rating >= 3.0 ? 'warning' : 'poor';
        html += `<span class="quality-indicator quality-${ratingClass}">⭐ ${product.rating}/5</span>`;
    }

    // Reviews indicator
    if (product.review_count !== undefined) {
        const reviewClass = product.review_count >= 50 ? 'excellent' : product.review_count >= 10 ? 'warning' : 'poor';
        html += `<span class="quality-indicator quality-${reviewClass}">💬 ${product.review_count} reviews</span>`;
    }

    // Stock indicator
    const stockClass = product.in_stock ? 'excellent' : 'poor';
    const stockText = product.in_stock ? '✓ In Stock' : '✗ Out of Stock';
    html += `<span class="quality-indicator quality-${stockClass}">${stockText}</span>`;

    return html;
}

// ============================================
// Step 1b: Manual Entry (NEW)
// ============================================

function addManually() {
    isManualEntry = true;
    currentProduct = null;

    // Hide the preview panel if it was showing from a previous attempt
    document.getElementById('productPreview').style.display = 'none';

    // Skip straight to the form — bypass the AI categorization step
    // since there's no scraped name/description to pass to the AI
    populateProductForm(null, null);

    document.getElementById('productForm').style.display = 'block';

    // Optionally show categorization section so admin can still request AI
    // suggestions once they've typed in a name + description
    document.getElementById('categorizationSection').style.display = 'block';

    // Update the form title to signal manual mode
    document.getElementById('formTitle').textContent = 'Add Product Details';
    const badge = document.getElementById('modeBadge');
    badge.textContent = '✏️ Manual Entry';
    badge.className = 'mode-badge mode-badge-manual';
    badge.style.display = 'inline-block';

    showAlert('Fill in the product details below. You can still use AI to suggest categories once you\'ve entered a name and description.', 'info');

    // Scroll down to the form
    document.getElementById('productForm').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ============================================
// Step 2: AI Categorization
// ============================================

async function categorizeProduct() {
    // In manual mode, pull the name/description from the form itself
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

        // Apply AI suggestions to the checkboxes
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
    // Basic fields — fill from product data if available, otherwise leave empty
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

    // Update the form title badge for scraped mode
    if (!isManualEntry && product) {
        document.getElementById('formTitle').textContent = 'Step 3: Review & Edit Product Details';
        const badge = document.getElementById('modeBadge');
        badge.textContent = '✅ Amazon Scraped';
        badge.className = 'mode-badge mode-badge-scraped';
        badge.style.display = 'inline-block';
    }

    // Initialize all multi-select fields
    initMultiSelect('categories', OPTIONS.categories, LIMITS.categories);
    initMultiSelect('interests', OPTIONS.interests, LIMITS.interests);
    initMultiSelect('occasions', OPTIONS.occasions, LIMITS.occasions);
    initMultiSelect('gender', OPTIONS.gender);
    initMultiSelect('relationship', OPTIONS.relationship);
    initMultiSelect('vibe', OPTIONS.vibe, LIMITS.vibe);
    initMultiSelect('traits', OPTIONS.traits, LIMITS.traits);

    // Apply AI categorization suggestions if provided
    if (categorization) {
        applyCategorizationToForm(categorization);
    }

    // Setup form submission
    document.getElementById('editForm').onsubmit = saveProduct;
}

function applyCategorizationToForm(categorization) {
    setMultiSelectValues('categories', categorization.categories || []);
    setMultiSelectValues('interests', categorization.interests || []);
    setMultiSelectValues('occasions', categorization.occasions || []);
    setMultiSelectValues('gender', categorization.recipient?.gender || []);
    setMultiSelectValues('relationship', categorization.recipient?.relationship || []);
    setMultiSelectValues('vibe', categorization.vibe || []);
    setMultiSelectValues('traits', categorization.personality_traits || []);
    if (categorization.experience_level) {
        document.getElementById('experienceLevel').value = categorization.experience_level;
    }
}

function initMultiSelect(fieldName, options, maxLimit = null) {
    const container = document.getElementById(`${fieldName}Container`);
    container.innerHTML = '';

    options.forEach(option => {
        const div = document.createElement('div');
        div.className = 'checkbox-item';

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
        // Make Mother's Day label human-friendly
        label.textContent = option === 'mothers_day' ? "Mother's Day" : option;

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
            if (!cb.checked) {
                cb.disabled = true;
            }
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
            showAlert(`${field} cannot have more than ${limit} items`, 'error');
            return;
        }
    }

    showLoading('saveLoading', true);
    document.getElementById('saveBtn').disabled = true;

    try {
        const ratingVal = document.getElementById('rating').value;
        const reviewCountVal = document.getElementById('reviewCount').value;

        const product = {
            name: document.getElementById('productName').value,
            display_name: document.getElementById('displayName').value || null,
            description: document.getElementById('description').value,
            brand: document.getElementById('brand').value,
            price: parseFloat(document.getElementById('price').value),
            currency: document.getElementById('currency').value,
            link: document.getElementById('link').value,
            image_url: document.getElementById('imageUrl').value,
            source: document.getElementById('source').value,
            categories: getMultiSelectValues('categories'),
            interests: getMultiSelectValues('interests'),
            occasions: getMultiSelectValues('occasions'),
            vibe: getMultiSelectValues('vibe'),
            personality_traits: getMultiSelectValues('traits'),
            recipient: {
                gender: getMultiSelectValues('gender'),
                relationship: getMultiSelectValues('relationship')
            },
            experience_level: document.getElementById('experienceLevel').value,
            rating: ratingVal ? parseFloat(ratingVal) : (currentProduct?.rating || null),
            review_count: reviewCountVal ? parseInt(reviewCountVal) : (currentProduct?.review_count || 0),
            in_stock: document.getElementById('inStock').checked
        };

        const saved = await apiRequest('/products', 'POST', {
            product: product,
            created_by: 'admin'
        });

        showAlert(`Product saved successfully! ID: ${saved.id}`, 'success');

        // Reset form after 2 seconds
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