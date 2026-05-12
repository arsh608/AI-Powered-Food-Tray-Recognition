// Minimalist Food Billing Web App (Frontend Only)
// Backend API endpoints - all real calls, no mock data

const API_BASE = ''; // Replace with actual backend base URL if needed, e.g., 'https://your-api.com'

// Helper: show toast messages
function showToast(message, isError = false) {
  const toast = document.getElementById('toastMsg');
  toast.textContent = message;
  toast.style.backgroundColor = isError ? '#c0392b' : '#2c3e50';
  toast.classList.remove('hidden');
  setTimeout(() => toast.classList.add('hidden'), 3000);
}

// Helper: API request wrapper
async function apiRequest(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    let errorMsg = `Request failed: ${response.status}`;
    try { const err = await response.json(); errorMsg = err.message || err.error || errorMsg; } catch(e) {}
    throw new Error(errorMsg);
  }
  return response.json();
}

// Global state
let currentUser = null;       // stores customer data { id, first_name, last_name, google_id, phone? }
let currentAdminToken = null;
let menuItems = [];           // food items from backend (list of { id, name, price })
let currentBillData = null;   // store detected items from /detect before bill display
let selectedImageFile = null; // current image for detection

// Screens
const screens = {
  roleSelection: document.getElementById('roleSelection'),
  userLogin: document.getElementById('userLoginScreen'),
  userDashboard: document.getElementById('userDashboardScreen'),
  adminLogin: document.getElementById('adminLoginScreen'),
  adminDashboard: document.getElementById('adminDashboardScreen'),
};

function showScreen(screenId) {
  Object.keys(screens).forEach(id => {
    screens[id].classList.remove('active');
  });
  screens[screenId].classList.add('active');
}

// ----- ROLE SELECTION -----
document.getElementById('userRoleBtn').addEventListener('click', () => {
  showScreen('userLogin');
});
document.getElementById('adminRoleBtn').addEventListener('click', () => {
  showScreen('adminLogin');
});

// Back buttons
document.querySelectorAll('.back-btn').forEach(btn => {
  btn.addEventListener('click', (e) => {
    const targetScreen = btn.getAttribute('data-screen');
    if (targetScreen) showScreen(targetScreen);
  });
});

// ----- USER CHECK-IN (POST /customer/checkin) -----
document.getElementById('userLoginForm').addEventListener('submit', async (e) => {
  e.preventDefault();

  const fullName = document.getElementById('fullName').value.trim();
  const email = document.getElementById('emailUser').value.trim();
  const phone = document.getElementById('phone').value.trim();

  const emailError = document.getElementById('emailError');
  const phoneError = document.getElementById('phoneError');

  emailError.textContent = '';
  phoneError.textContent = '';

  if (!email.endsWith('@gmail.com')) {
    emailError.textContent = 'Email must be a valid @gmail.com address';
    return;
  }

  if (!/^03\d{9}$/.test(phone)) {
    phoneError.textContent = 'Phone must start with 03 and be exactly 11 digits';
    return;
  }

  const nameParts = fullName.trim().split(/\s+/);
  const first_name = nameParts[0] || '';
  const last_name = nameParts.slice(1).join(' ') || '';

  const google_id = email.split('@')[0];

  try {
    const response = await apiRequest('/customer/checkin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        first_name,
        last_name,
        google_id,
        phone
      })
    });

    currentUser = {
      id: response.customer_id,
      first_name: response.customer.first_name,
      last_name: response.customer.last_name,
      email,
      phone: response.customer.phone
    };

    showToast(response.returning
      ? 'Welcome back!'
      : 'Check-in successful! Welcome.');

    resetBillFlow();
    showScreen('userDashboard');

  } catch (err) {
    showToast(`Check-in failed: ${err.message}`, true);
  }
});

// Reset image preview and bill
function resetBillFlow() {
  selectedImageFile = null;
  document.getElementById('imagePreview').classList.add('hidden');
  document.getElementById('previewImg').src = '';
  document.getElementById('billContainer').classList.add('hidden');
  currentBillData = null;
  const genBtn = document.getElementById('generateBillBtn');
  genBtn.disabled = true;
}

// Upload / Camera handlers
const fileInput = document.getElementById('imageUploadFile');
const cameraInput = document.getElementById('cameraInput');

fileInput.addEventListener('change', (e) => {
  if (e.target.files.length) handleImageFile(e.target.files[0]);
});

cameraInput.addEventListener('change', (e) => {
  if (e.target.files.length) handleImageFile(e.target.files[0]);
});

document.getElementById('cameraBtn').addEventListener('click', () => {
  cameraInput.click();
});

document.getElementById('clearImageBtn').addEventListener('click', () => {
  selectedImageFile = null;
  document.getElementById('imagePreview').classList.add('hidden');
  document.getElementById('generateBillBtn').disabled = true;
  fileInput.value = '';
  cameraInput.value = '';
});

function handleImageFile(file) {
  if (!file.type.startsWith('image/')) {
    showToast('Please select an image file', true);
    return;
  }

  selectedImageFile = file;

  const reader = new FileReader();

  reader.onload = (ev) => {
    const previewImg = document.getElementById('previewImg');
    previewImg.src = ev.target.result;

    document.getElementById('imagePreview').classList.remove('hidden');
    document.getElementById('generateBillBtn').disabled = false;
  };

  reader.readAsDataURL(file);
}

// Generate Bill: POST /detect (FormData)
document.getElementById('generateBillBtn').addEventListener('click', async () => {
  if (!selectedImageFile) {
    showToast('Please select an image first', true);
    return;
  }

  const btn = document.getElementById('generateBillBtn');

  const originalText = btn.innerText;
  btn.innerText = 'Generating...';
  btn.disabled = true;

  const formData = new FormData();
  formData.append('file', selectedImageFile);

  try {
    const detectionResult = await apiRequest('/detect', {
      method: 'POST',
      body: formData
    });

    if (!detectionResult || !Array.isArray(detectionResult.items)) {
      throw new Error('Invalid detection response');
    }

    // ✅ NO formatting / NO recalculation
    const items = detectionResult.items.map(item => ({
      item_name: item.label
        .toLowerCase()
        .split(' ')
        .filter(word => word.length > 0)
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' '),
      qty: item.quantity,
      price: item.unit_price,
      subtotal: item.subtotal,
      confidence: item.confidence
    }));

    currentBillData = items;
    renderBill(items, detectionResult.total_price);

    document.getElementById('billContainer').classList.remove('hidden');

  } catch (err) {
    showToast(`Detection error: ${err.message}`, true);

  } finally {
    btn.innerText = originalText;
    btn.disabled = false;
  }
});


function renderBill(items, totalPrice) {
  const container = document.getElementById('billItemsList');

  if (!items.length) {
    container.innerHTML = '<div class="bill-item-row">No items detected</div>';
    document.getElementById('totalAmount').innerText = '0.00';
    return;
  }

  container.innerHTML = '';

  // 1. Add header ONCE
  const header = document.createElement('div');
  header.className = 'bill-header';

  header.innerHTML = `
    <span class="bill-item-name">Item</span>
    <span class="bill-item-qty">Qty</span>
    <span class="bill-item-unit">Unit Price</span>
    <span class="bill-item-subtotal">Total</span>
  `;

  container.appendChild(header);

  // 2. Add rows
  items.forEach(item => {
    const row = document.createElement('div');
    row.className = 'bill-item-row';

    row.innerHTML = `
      <span class="bill-item-name">${escapeHtml(item.item_name)}</span>
      <span class="bill-item-qty">x${item.qty}</span>
      <span class="bill-item-unit">Rs. ${parseFloat(item.price).toFixed(2)}</span>
      <span class="bill-item-subtotal">Rs. ${parseFloat(item.subtotal).toFixed(2)}</span>
    `;

    container.appendChild(row);
  });

  // ✅ backend total used directly
  document.getElementById('totalAmount').innerText = parseFloat(totalPrice).toFixed(2);
}

function escapeHtml(str) { return String(str).replace(/[&<>]/g, function(m){if(m==='&') return '&amp;'; if(m==='<') return '&lt;'; if(m==='>') return '&gt;'; return m;}); }

// PAY Button: Download bill + POST /orders
document.getElementById('payBtn').addEventListener('click', async () => {
  if (!currentBillData || !currentBillData.length) {
    showToast('No bill generated to pay', true);
    return;
  }
  if (!currentUser || !currentUser.id) {
    showToast('User session missing, please login again', true);
    return;
  }
  const itemsForOrder = currentBillData.map(it => {
    const qty = it.qty || 1;
    const price = parseFloat(it.price) || 0;

    return {
      item_name: it.item_name,
      qty,
      price,
      subtotal: qty * price
    };
  });

  // use subtotal already stored in each item (no recalculation)
  const subtotal = itemsForOrder.reduce((sum, i) => sum + i.subtotal, 0);

  const total = subtotal; // no tax for simplicity
  const order_code = `ORD-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
  const payload = {
    order_code,
    customer_id: String(currentUser.id),
    items: JSON.stringify(itemsForOrder), // FIXED
    subtotal,
    total,
    payment_method: 'cash'
  };
  
  try {
    await apiRequest('/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    // Download Bill as text file
    const billText = generateBillText(currentBillData, total, order_code);
    const blob = new Blob([billText], { type: 'text/plain' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `bill_${order_code}.txt`;
    link.click();
    URL.revokeObjectURL(link.href);
    showToast('Order saved! Bill downloaded.');
    // Reset after payment
    resetBillFlow();
    selectedImageFile = null;
    if(fileInput) fileInput.value = '';
    document.getElementById('imagePreview').classList.add('hidden');
  } catch (err) {
    showToast(`Payment/Order failed: ${err.message}`, true);
  }
});

function generateBillText(items, total, orderCode) {
  let lines = ['----- MINIMAL BILL -----', `Order: ${orderCode}`, ''];
  items.forEach(it => {
    lines.push(
      `${it.item_name} x${it.qty || 1} @ Rs.${it.price.toFixed(2)} = Rs.${it.subtotal.toFixed(2)}`
    );
  });
  lines.push('', `TOTAL: Rs. ${total.toFixed(2)}`, 'Thank you!');
  return lines.join('\n');
}

// ---------- ADMIN LOGIN (/admin/login) ----------
document.getElementById('adminLoginForm').addEventListener('submit', async (e) => {
  e.preventDefault();

  const username = document.getElementById('adminUsername').value.trim();
  const password = document.getElementById('adminPassword').value.trim();

  try {
    const res = await apiRequest('/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });

    if (!res.success) {
      throw new Error('Invalid credentials');
    }

    // Backend does not return token, so use admin_id as session identifier
    currentAdminToken = res.admin_id;

    showToast('Admin login successful');
    await loadMenuItems();
    showScreen('adminDashboard');

  } catch (err) {
    showToast(`Admin login failed: ${err.message}`, true);
  }
});

// Analystics
document.getElementById("fetchAnalyticsBtn").addEventListener("click", async () => {
  const days = document.getElementById("analyticsDays").value;

  try {
    const res = await fetch(`/analytics/sales?days=${days}`);
    const data = await res.json();

    document.getElementById("totalSales").innerText =
      `Rs. ${data.total_sales.toFixed(2)}`;

    document.getElementById("orderCount").innerText =
      data.order_count;

    document.getElementById("avgOrder").innerText =
      `Rs. ${data.average_order.toFixed(2)}`;

    document.getElementById("analyticsResult").classList.remove("hidden");

  } catch (err) {
    console.error("Analytics fetch error:", err);
    alert("Failed to load analytics");
  }
});

// Load menu items from backend (via GET, but the spec expects backend to handle; we assume GET /items)
async function loadMenuItems() {
  try {
    const response = await apiRequest('/menu', {
      method: 'GET'
    });

    menuItems = response.items || [];

    renderFoodItems();
  } catch (err) {
    console.warn('Could not fetch items, fallback empty', err);
    menuItems = [];
    renderFoodItems();
  }
}

function renderFoodItems() {
  const container = document.getElementById('foodItemsList');
  if (!menuItems.length) {
    container.innerHTML = '<div class="loading-placeholder">No food items. Add some!</div>';
    return;
  }
  container.innerHTML = '';
  menuItems.forEach(item => {
    const card = document.createElement('div');
    card.className = 'menu-item-card';
    card.innerHTML = `
      <div class="item-info">
        <div class="item-name">${escapeHtml(item.name)}</div>
        <div class="item-price">Rs. ${parseFloat(item.price).toFixed(2)}</div>
      </div>
      <div class="item-actions">
        <button class="edit-btn" data-id="${item.id}">Edit</button>
        <button class="delete-btn" data-id="${item.id}">Delete</button>
      </div>
    `;
    container.appendChild(card);
  });
  // attach events after render
  document.querySelectorAll('.edit-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
    const id = btn.getAttribute('data-id');
    let newName = prompt('Enter new item name:');
    if (!newName) return;
    newName = newName.trim();
    // Reject numeric-only names like "200"
    if (/^\d+$/.test(newName)) {
      showToast('Food name cannot be only numbers', true);
      return;
    }
    // (Optional stronger rule: must contain letters)
    if (!/[a-zA-Z]/.test(newName)) {
      showToast('Food name must contain letters', true);
      return;
    }
    // Convert to Title Case (Zinger Burger)
    newName = newName
      .toLowerCase()
      .split(' ')
      .filter(word => word.length > 0)
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
    const newPrice = parseFloat(prompt('Enter new price:'));
    if (isNaN(newPrice) || newPrice <= 0) {
      showToast('Invalid price', true);
      return;
    }
    try {
      await apiRequest(`/menu/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newName,
          price: newPrice
        })
      });
      await loadMenuItems();
      showToast('Item updated');
    } catch (err) {
      showToast(`Update failed: ${err.message}`, true);
    }
  });
  });
  document.querySelectorAll('.delete-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const id = btn.getAttribute('data-id');
      if (confirm('Delete this item?')) {
        try {
          await apiRequest(`/menu/${id}`, { method: 'DELETE' });
          await loadMenuItems();
          showToast('Item deleted');
        } catch(err) { showToast(`Delete failed: ${err.message}`, true); }
      }
    });
  });
}

// Add Food Item
document.getElementById('addItemBtn').addEventListener('click', async () => {
  let name = document.getElementById('itemName').value.trim();
  const price = parseFloat(document.getElementById('itemPrice').value);
  const category = document.getElementById('itemCategory')?.value;
  // Required fields check
  if (!name || isNaN(price) || !category) {
    showToast('Name, price, and category are required', true);
    return;
  }
  // Reject numeric-only names like "200"
  if (/^\d+$/.test(name)) {
    showToast('Food name cannot be only numbers', true);
    return;
  }
  // Must contain at least one letter
  if (!/[a-zA-Z]/.test(name)) {
    showToast('Food name must contain letters', true);
    return;
  }
  // Convert to Title Case (Zinger Burger)
  name = name
    .toLowerCase()
    .split(' ')
    .filter(word => word.length > 0)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
  // Price validation (same as update constraints)
  if (isNaN(price) || price <= 0) {
      showToast('Invalid price', true);
      return;
  }
  try {
    await apiRequest('/menu', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        price,
        category
      })
    });
    // Reset form
    document.getElementById('itemName').value = '';
    document.getElementById('itemPrice').value = '';
    if (document.getElementById('itemCategory')) {
      document.getElementById('itemCategory').value = '';
    }
    await loadMenuItems();
    showToast('Item added');
  } catch (err) {
    showToast(`Add failed: ${err.message}`, true);
  }
});

// EDIT Food Item
document.querySelectorAll('.edit-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const id = btn.getAttribute('data-id');

    let newName = prompt('Enter new item name:')?.trim();
    if (!newName) return;

    const newPrice = parseFloat(prompt('Enter new price:'));
    const category = prompt('Enter category:')?.trim();

    // Required fields check
    if (!newName || isNaN(newPrice) || !category) {
      showToast('Name, price, and category are required', true);
      return;
    }

    // Reject numeric-only names
    if (/^\d+$/.test(newName)) {
      showToast('Food name cannot be only numbers', true);
      return;
    }

    // Must contain at least one letter
    if (!/[a-zA-Z]/.test(newName)) {
      showToast('Food name must contain letters', true);
      return;
    }

    // Price validation
    if (isNaN(newPrice) || newPrice <= 0) {
      showToast('Invalid price', true);
      return;
    }

    // Convert to Title Case
    newName = newName
      .toLowerCase()
      .split(' ')
      .filter(word => word.length > 0)
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');

    try {
      await apiRequest(`/menu/${id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          name: newName,
          price: newPrice,
          category
        })
      });

      await loadMenuItems();
      showToast('Item updated');

    } catch (err) {
      showToast(`Update failed: ${err.message}`, true);
    }
  });
});

// DELETE Food Item
document.querySelectorAll('.delete-btn').forEach(btn => {
  btn.addEventListener('click', async () => {

    const id = btn.getAttribute('data-id');

    if (!confirm('Delete this item?')) return;

    try {
      await apiRequest(`/menu/${id}`, {
        method: 'DELETE'
      });

      await loadMenuItems();

      showToast('Item deleted');

    } catch (err) {
      showToast(`Delete failed: ${err.message}`, true);
    }
  });
});

// Logout handlers
document.getElementById('userLogoutBtn').addEventListener('click', () => {
  currentUser = null;
  resetBillFlow();
  showScreen('roleSelection');
});
document.getElementById('adminLogoutBtn').addEventListener('click', () => {
  currentAdminToken = null;
  showScreen('roleSelection');
});