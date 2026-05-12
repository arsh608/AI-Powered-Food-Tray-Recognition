import logging
import sys
import time
import uuid
from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
import shutil, os, requests
from typing import Dict
from datetime import datetime, timedelta
from contextvars import ContextVar
from fastapi.templating import Jinja2Templates
import uvicorn
import re

MENU_CACHE = None 

# ========== LOGGING CONFIGURATION ==========
# Create request ID for tracking individual requests
request_id_var: ContextVar[str] = ContextVar("request_id", default="")

class RequestIdFilter(logging.Filter):
    """Add request ID to every log message"""
    def filter(self, record):
        # Default to empty string so loggers without a request context don't crash
        record.request_id = (request_id_var.get()[:12] if request_id_var.get() else "N/A")
        return True

request_filter = RequestIdFilter()

# Configure logging to stdout/stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | req_id=%(request_id)-12s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

# Create separate logger for errors to stderr
error_handler = logging.StreamHandler(sys.stderr)
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)-8s | req_id=%(request_id)-12s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))

# Get root logger and configure
logger = logging.getLogger("food-tray-api")
logger.addHandler(error_handler)
logger.addFilter(request_filter)  # Use the single instance

# Also add filter to root logger so uvicorn/starlette loggers get request_id too
root_logger = logging.getLogger()
root_logger.addFilter(request_filter)  # Use the same instance

# Create specific loggers for different components
api_logger = logging.getLogger("food-tray-api.api")
db_logger = logging.getLogger("food-tray-api.database")
ai_logger = logging.getLogger("food-tray-api.ai")
security_logger = logging.getLogger("food-tray-api.security")
business_logger = logging.getLogger("food-tray-api.business")

request_filter = RequestIdFilter()
api_logger.addFilter(request_filter)
db_logger.addFilter(request_filter)
ai_logger.addFilter(request_filter)
security_logger.addFilter(request_filter)
business_logger.addFilter(request_filter)
# ========== APP INITIALIZATION ==========
# NOTE: app MUST be created before any @app decorator is used
app = FastAPI(title="Food Tray Recognition API", version="1.0.0")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== MIDDLEWARE FOR REQUEST LOGGING ==========
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with timing"""
    request_id = str(uuid.uuid4())
    request_id_var.set(request_id)

    method = request.method
    url = str(request.url)
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")[:50]

    api_logger.info(f"→ REQUEST | {method} {url} | IP={client_ip} | UA={user_agent}")

    start_time = time.time()

    try:
        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000
        status_code = response.status_code
        status_emoji = "✅" if status_code < 400 else "⚠️" if status_code < 500 else "❌"
        api_logger.info(
            f"{status_emoji} RESPONSE | {method} {url} | Status={status_code} | Duration={duration_ms:.2f}ms"
        )
        response.headers["X-Request-ID"] = request_id[:12]
        response.headers["X-Response-Time-MS"] = str(int(duration_ms))
        return response

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        api_logger.error(f"❌ ERROR | {method} {url} | Error={str(e)} | Duration={duration_ms:.2f}ms", exc_info=True)
        raise

# ========== SUPABASE CONFIGURATION ==========
# Read secrets from environment variables (never hardcode keys)
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://bwgnfecyvfuburdiwbiv.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJ3Z25mZWN5dmZ1YnVyZGl3Yml2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzc3MTcxNTAsImV4cCI6MjA5MzI5MzE1MH0.qRQTYD2dW0PWUNhozwZHEAVSJlUSUiRqCYmjvU7eTTs")
HF_API_URL = os.getenv("HF_API_URL", "https://raoghulam-food-detection-api.hf.space/predict")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

logger.info("=" * 60)
logger.info("🚀 Food Tray Recognition API Starting...")
logger.info(f"📍 Supabase URL: {SUPABASE_URL[:30]}..." if SUPABASE_URL else "📍 Supabase URL: NOT SET")
logger.info(f"🤖 Hugging Face API: {HF_API_URL}")
logger.info(f"🔧 Environment: {'Production' if os.getenv('ENVIRONMENT') == 'production' else 'Development'}")
logger.info("=" * 60)

# ========== HELPER FUNCTIONS ==========

def db_get(table, params=None):
    """Get data from Supabase with logging"""
    db_logger.debug(f"DB QUERY | table={table} | params={params}")
    start_time = time.time()

    try:
        res = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=HEADERS, params=params)
        duration_ms = (time.time() - start_time) * 1000

        if res.status_code == 200:
            data = res.json()
            db_logger.info(f"✅ DB GET | table={table} | rows={len(data)} | duration={duration_ms:.2f}ms")
            return data
        else:
            db_logger.error(f"❌ DB GET FAILED | table={table} | status={res.status_code} | response={res.text[:200]}")
            return []

    except Exception as e:
        db_logger.error(f"❌ DB GET EXCEPTION | table={table} | error={str(e)}", exc_info=True)
        return []


def db_post(table, data):
    """Post data to Supabase with logging"""
    db_logger.debug(f"DB INSERT | table={table} | data={str(data)[:200]}")
    start_time = time.time()

    try:
        res = requests.post(f"{SUPABASE_URL}/rest/v1/{table}", headers=HEADERS, json=data)
        duration_ms = (time.time() - start_time) * 1000

        if res.status_code == 201:
            result = res.json()
            db_logger.info(f"✅ DB INSERT | table={table} | inserted={len(result)} | duration={duration_ms:.2f}ms")
            return result
        else:
            db_logger.error(f"❌ DB INSERT FAILED | table={table} | status={res.status_code} | response={res.text[:200]}")
            return []

    except Exception as e:
        db_logger.error(f"❌ DB INSERT EXCEPTION | table={table} | error={str(e)}", exc_info=True)
        return []


def detect_food_items(image_path: str) -> Dict[str, int]:
    ai_logger.info(f"🔍 Starting food detection | image={os.path.basename(image_path)}")
    
    try:
        with open(image_path, "rb") as f:
            response = requests.post(
                HF_API_URL,
                files={"file": f},
                timeout=30
            )

        if response.status_code == 200:
            result = response.json()
            ai_logger.debug(f"📊 Raw API response: {str(result)[:300]}")

            counts = {}

            if isinstance(result, dict):
                if "detections" in result and isinstance(result["detections"], dict):
                    # ✅ Your API format: {'success': True, 'detections': {'pizza': 2, 'burger': 1}}
                    counts = result["detections"]
                elif all(isinstance(v, int) for v in result.values()):
                    counts = result
                elif "predictions" in result:
                    for pred in result["predictions"]:
                        label = pred.get("label", "unknown")
                        counts[label] = counts.get(label, 0) + 1

            elif isinstance(result, list):
                for detection in result:
                    label = detection.get("label", detection.get("class", "unknown"))
                    counts[label] = counts.get(label, 0) + 1

            ai_logger.info(f"✅ Detection complete | items={counts}")
            return counts if counts else {"unknown": 1}

        else:
            ai_logger.error(f"❌ HF API error | status={response.status_code}")
            return {}

    except requests.exceptions.Timeout:
        ai_logger.error("❌ HF API timeout after 30 seconds")
        return {}
    except Exception as e:
        ai_logger.error(f"❌ Detection exception: {str(e)}", exc_info=True)
        return {}
# ========== ENDPOINTS ==========

@app.get("/")
async def serve_frontend(request: Request):
    api_logger.info("Rendering index.html via Jinja2")
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    api_logger.debug("Health check requested")
    return {
        "status": "healthy",
        "api": "food-tray-recognition",
        "timestamp": datetime.now().isoformat()
    }


# ── AI Detection ─────────────────────────────────────────────────
# -----------------------------
# In-memory cache (loaded once)
# -----------------------------
def invalidate_menu_cache():
    global MENU_CACHE
    MENU_CACHE = None
    api_logger.info("♻️ Menu cache invalidated")


def normalize(text: str):
    """Normalize text for matching"""
    return re.sub(r'\s+', ' ', text).strip().lower()


def load_menu_once():
    """
    Load menu items from Supabase only once
    """
    global MENU_CACHE

    if MENU_CACHE is None:
        menu_items = db_get("menu_items", {
            "select": "*"
        })

        # Build normalized lookup map
        MENU_CACHE = {
            normalize(item["name"]): item
            for item in menu_items
        }

        api_logger.info(f"📦 Menu cached | items_loaded={len(MENU_CACHE)}")

    return MENU_CACHE


# -----------------------------
# API Endpoint
# -----------------------------
@app.post("/detect")
async def detect_food(file: UploadFile = File(...)):
    """Detect food items and calculate bill"""

    api_logger.info(
        f"🖼️ Detection request | file={file.filename} | type={file.content_type}"
    )

    if not file.content_type.startswith("image/"):
        api_logger.warning(f"Invalid file type rejected: {file.content_type}")
        raise HTTPException(status_code=400, detail="File must be an image")

    temp_path = f"temp_{file.filename}"

    try:
        # -----------------------------
        # Save uploaded file
        # -----------------------------
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        api_logger.debug(f"📁 Temp file saved: {temp_path}")

        # -----------------------------
        # Step 1: Get model predictions
        # Example: {"Zinger Burger": 2, "Fries": 1}
        # -----------------------------
        counts = detect_food_items(temp_path)

        # -----------------------------
        # Step 2: Load menu ONCE
        # -----------------------------
        menu_map = load_menu_once()

        items = []
        total_items = 0
        total_price = 0.0

        # -----------------------------
        # Step 3: Process predictions
        # -----------------------------
        for label, qty in counts.items():
            total_items += qty

            normalized_label = normalize(label)

            item_data = menu_map.get(normalized_label)

            if not item_data:
                api_logger.warning(f"❌ Menu miss: {label}")
                continue

            price = float(item_data.get("price", 0))
            subtotal = price * qty
            total_price += subtotal

            items.append({
                "label": label,
                "normalized_label": normalized_label,
                "quantity": qty,
                "unit_price": price,
                "subtotal": subtotal,
                "confidence": 0.90
            })

        # -----------------------------
        # Step 4: Response
        # -----------------------------
        api_logger.info(
            f"✅ Detection success | items={len(items)} | total_price={total_price}"
        )

        return {
            "success": True,
            "items": items,
            "total_items": total_items,
            "total_price": total_price
        }

    finally:
        # cleanup temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)

# ── ADMIN: Login ─────────────────────────────────────────────────
class AdminLogin(BaseModel):
    username: str
    password: str


@app.post("/admin/login")
async def admin_login(data: AdminLogin):
    security_logger.info(f"🔐 Admin login attempt | username={data.username}")
    start_time = time.time()

    result = db_get("admins", {
        "username": f"eq.{data.username}",
        "password": f"eq.{data.password}",
        "select": "*"
    })

    duration_ms = (time.time() - start_time) * 1000

    if not result or len(result) == 0:
        security_logger.warning(f"❌ Failed login | username={data.username} | duration={duration_ms:.2f}ms")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    security_logger.info(f"✅ Successful login | username={data.username} | admin_id={result[0]['id']} | duration={duration_ms:.2f}ms")
    return {
        "success": True,
        "name": result[0]["full_name"],
        "username": result[0]["username"],
        "admin_id": result[0]["id"]
    }


# ── ADMIN: Register ──────────────────────────────────────────────
class AdminRegister(BaseModel):
    username: str
    password: str
    full_name: str
    admin_key: str


@app.post("/admin/register")
async def admin_register(data: AdminRegister):
    security_logger.info(f"📝 Admin registration attempt | username={data.username}")

    if data.admin_key != "123":
        security_logger.warning(f"❌ Registration failed: invalid admin key | username={data.username}")
        raise HTTPException(status_code=403, detail="Invalid admin key")

    existing = db_get("admins", {"username": f"eq.{data.username}", "select": "id"})
    if existing and len(existing) > 0:
        security_logger.warning(f"❌ Registration failed: username taken | username={data.username}")
        raise HTTPException(status_code=400, detail="Username already taken")

    result = db_post("admins", {
        "username": data.username,
        "password": data.password,
        "full_name": data.full_name
    })

    if not result:
        security_logger.error(f"❌ Registration failed: database error | username={data.username}")
        raise HTTPException(status_code=500, detail="Failed to create admin")

    security_logger.info(f"✅ Admin created successfully | username={data.username} | admin_id={result[0]['id']}")
    return {"success": True, "message": "Admin created successfully"}


# ── CUSTOMER: Check in ───────────────────────────────────────────
class CustomerInfo(BaseModel):
    first_name: str
    last_name: str
    google_id: str
    phone: str


@app.post("/customer/checkin")
async def customer_checkin(data: CustomerInfo):
    business_logger.info(f"👤 Customer check-in | google_id={data.google_id} | name={data.first_name} {data.last_name}")

    existing = db_get("customers", {"google_id": f"eq.{data.google_id}", "select": "*"})

    if existing and len(existing) > 0:
        business_logger.info(f"✅ Returning customer | customer_id={existing[0]['id']} | google_id={data.google_id}")
        return {
            "customer_id": existing[0]["id"],
            "returning": True,
            "customer": existing[0]
        }

    result = db_post("customers", {
        "first_name": data.first_name,
        "last_name": data.last_name,
        "google_id": data.google_id,
        "phone": data.phone
    })

    if not result:
        business_logger.error(f"❌ Failed to create customer | google_id={data.google_id}")
        raise HTTPException(status_code=500, detail="Failed to create customer")

    business_logger.info(f"✅ New customer created | customer_id={result[0]['id']} | google_id={data.google_id}")
    return {
        "customer_id": result[0]["id"],
        "returning": False,
        "customer": result[0]
    }


# ── ORDERS: Save ─────────────────────────────────────────────────
class OrderData(BaseModel):
    order_code: str
    customer_id: str
    items: str
    subtotal: float
    total: float
    payment_method: str


@app.post("/orders")
async def save_order(data: OrderData):
    business_logger.info(f"💰 New order | order_code={data.order_code} | customer_id={data.customer_id} | total=₹{data.total}")

    result = db_post("orders", {
        "order_code": data.order_code,
        "customer_id": data.customer_id,
        "items": data.items,
        "subtotal": data.subtotal,
        "total": data.total,
        "payment_method": data.payment_method,
        "status": "completed"
    })

    if not result:
        business_logger.error(f"❌ Failed to save order | order_code={data.order_code}")
        raise HTTPException(status_code=500, detail="Failed to save order")

    business_logger.info(f"✅ Order saved | order_id={result[0]['id']} | order_code={data.order_code} | total=₹{data.total}")
    return {"success": True, "order_id": result[0]["id"]}


# ── ORDERS: Get all ──────────────────────────────────────────────
@app.get("/orders")
async def get_all_orders(limit: int = 100, offset: int = 0):
    business_logger.info(f"📋 Fetching orders | limit={limit} | offset={offset}")
    result = db_get("orders", {
        "select": "*, customers(first_name, last_name, google_id, phone)",
        "order": "created_at.desc",
        "limit": limit,
        "offset": offset
    })
    business_logger.info(f"✅ Retrieved {len(result)} orders")
    return {"orders": result, "count": len(result)}


# ── ORDERS: Get by customer ──────────────────────────────────────
@app.get("/orders/customer/{customer_id}")
async def get_customer_orders(customer_id: str):
    business_logger.info(f"📋 Fetching orders for customer | customer_id={customer_id}")
    result = db_get("orders", {
        "customer_id": f"eq.{customer_id}",
        "select": "*",
        "order": "created_at.desc"
    })
    business_logger.info(f"✅ Retrieved {len(result)} orders for customer {customer_id}")
    return {"orders": result}


# ── MENU: Get all ────────────────────────────────────────────────
@app.get("/menu")
async def get_menu(category: str = None):
    api_logger.debug(f"📋 Fetching menu | category={category}")
    params = {"status": "eq.active", "select": "*"}
    if category:
        params["category"] = f"eq.{category}"

    result = db_get("menu_items", params)
    api_logger.debug(f"✅ Retrieved {len(result)} menu items")
    return {"items": result, "count": len(result)}


# ── MENU: Get single item ────────────────────────────────────────
@app.get("/menu/{item_id}")
async def get_menu_item(item_id: int):
    api_logger.debug(f"📋 Fetching menu item | id={item_id}")
    result = db_get("menu_items", {"id": f"eq.{item_id}", "select": "*"})
    if not result:
        api_logger.warning(f"❌ Menu item not found | id={item_id}")
        raise HTTPException(status_code=404, detail="Menu item not found")
    return {"item": result[0]}


# ── MENU: Add ────────────────────────────────────────────────────
class MenuItem(BaseModel):
    name: str
    price: float
    category: str
    emoji: str = "🍽️"
    ai_label: str = ""
    status: str = "active"


@app.post("/menu")
async def add_menu_item(item: MenuItem):
    business_logger.info(f"📝 Adding menu item | name={item.name} | price=₹{item.price} | category={item.category}")

    existing = db_get("menu_items", {"name": f"eq.{item.name}", "status": "eq.active"})
    if existing:
        business_logger.warning(f"❌ Menu item already exists | name={item.name}")
        raise HTTPException(status_code=400, detail="Menu item already exists")

    result = db_post("menu_items", item.model_dump())
    invalidate_menu_cache()
    if not result:
        business_logger.error(f"❌ Failed to add menu item | name={item.name}")
        raise HTTPException(status_code=500, detail="Failed to add menu item")

    business_logger.info(f"✅ Menu item added | id={result[0]['id']} | name={item.name}")
    return {"success": True, "item": result[0]}


# ── MENU: Update ─────────────────────────────────────────────────
class MenuItemUpdate(BaseModel):
    name: str = None
    price: float = None
    category: str = None
    emoji: str = None
    ai_label: str = None
    status: str = None


@app.put("/menu/{item_id}")
async def update_menu_item(item_id: int, updates: MenuItemUpdate):
    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}
    business_logger.info(f"✏️ Updating menu item | id={item_id} | updates={list(update_data.keys())}")
    if not update_data:
        raise HTTPException(status_code=400, detail="No updates provided")

    response = requests.patch(
        f"{SUPABASE_URL}/rest/v1/menu_items",
        headers=HEADERS,
        params={"id": f"eq.{item_id}"},
        json=update_data
    )

    if response.status_code != 200:
        business_logger.error(f"❌ Failed to update menu item | id={item_id} | status={response.status_code}")
        raise HTTPException(status_code=500, detail="Failed to update menu item")

    business_logger.info(f"✅ Menu item updated | id={item_id}")
    invalidate_menu_cache()
    return {"success": True, "message": "Menu item updated"}


# ── MENU: Delete ─────────────────────────────────────────────────
@app.delete("/menu/{item_id}")
async def delete_menu_item(item_id: int):
    business_logger.info(f"🗑️ Deleting menu item | id={item_id}")

    response = requests.patch(
        f"{SUPABASE_URL}/rest/v1/menu_items",
        headers=HEADERS,
        params={"id": f"eq.{item_id}"},
        json={"status": "inactive"}
    )

    if response.status_code != 200:
        business_logger.error(f"❌ Failed to delete menu item | id={item_id} | status={response.status_code}")
        raise HTTPException(status_code=500, detail="Failed to delete menu item")

    business_logger.info(f"✅ Menu item deleted (soft) | id={item_id}")
    invalidate_menu_cache()
    return {"success": True, "message": "Menu item deleted"}


# ── ANALYTICS: Get sales summary ─────────────────────────────────
@app.get("/analytics/sales")
async def get_sales_summary(days: int = 7):
    business_logger.info(f"📊 Analytics request | days={days}")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    orders = db_get("orders", {
        "created_at": f"gte.{start_date.isoformat()}",
        "select": "total,created_at"
    })

    if not orders:
        business_logger.info(f"📊 No orders found for last {days} days")
        return {"total_sales": 0, "order_count": 0, "average_order": 0}

    total_sales = sum(order.get("total", 0) for order in orders)
    avg_order = total_sales / len(orders) if orders else 0

    business_logger.info(f"📊 Analytics result | orders={len(orders)} | total_sales=₹{total_sales} | avg=₹{avg_order:.2f}")

    return {
        "total_sales": total_sales,
        "order_count": len(orders),
        "average_order": avg_order,
        "period_days": days
    }


# ── SHUTDOWN EVENT ───────────────────────────────────────────────
@app.on_event("shutdown")
async def shutdown_event():
    logger.info("=" * 60)
    logger.info("🛑 Food Tray Recognition API shutting down...")
    logger.info("=" * 60)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
