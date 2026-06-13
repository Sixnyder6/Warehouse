# =========================================================================================
# ⚠️ ВНИМАНИЕ / WARNING: ОГРАНИЧЕНИЕ ТРАФИКА FIRESTORE!
# Ежедневный лимит на операции чтения Firestore ограничен 50,000 запросов!
# Любые новые эндпоинты, циклы опроса или синхронизации ДОЛЖНЫ БЫТЬ МАКСИМАЛЬНО ОПТИМИЗИРОВАНЫ.
# Обязательно используйте серверное кэширование и IndexedDB-синхронизацию на клиенте.
# Избегайте бесконечных циклов опроса (polling) и некэшированных повторных чтений!
# =========================================================================================

import os
import time
from fastapi import FastAPI, Request, HTTPException, Query, Depends, BackgroundTasks, UploadFile, File, WebSocket, WebSocketDisconnect, Response
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel
import logging

from app.models import (
    WarehouseItem, WarehouseItemCreate, WarehouseItemUpdate,
    WarehouseLog, GroupedActivity,
    WarehouseOrder, WarehouseOrderCreate, OrderStatus, OrderItem,
    CompleteOrderRequest,
    NewsItem, NewsItemCreate, NewsTag,
    TakeItemRequest, AddStockRequest, TakeItemBatchRequest,
    TakeItemExtendedRequest, ReturnItemRequest,  # ДОБАВЛЕНО ДЛЯ ВЫДАЧИ
    HistoryEntry, HistoryDetail, HistoryStats,
    SyncPushRequest, SyncPullResponse,
    UserRole, ShiftRequestStatus,
    DashboardSummary,
    ForecastItem,
)
from app.services.warehouse_service import (
    get_items, get_item, search_items,
    create_item, update_item, delete_item,
    take_item, take_items_batch, add_stock,
    take_item_to_recipient, return_item_to_stock,
    get_logs, get_logs_for_employee, get_grouped_logs,
    get_orders, create_order, update_order_status, complete_order,
    get_news, create_news, update_news, delete_news,
    get_employees, get_internal_users,
    firestore_update_document,
    # create_internal_user, update_internal_user, delete_internal_user,  # ЗАКОММЕНТИРОВАНО: веб не должен изменять internal_users
    check_firebase_connection,
    get_status_text, get_status_color,
    pull_items_changes, process_offline_operations,
    get_history_summary,
)
from app.api.auth import router as auth_router
from app.services.excel_importer import run_excel_import, import_tasks

# ==========================================
# ЛОГГИРОВАНИЕ
# ==========================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# СОЗДАЕМ ПРИЛОЖЕНИЕ
# ==========================================

app = FastAPI(title="Warehouse Management System")

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

# Mount React frontend assets
FRONTEND_DIST_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(FRONTEND_DIST_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST_DIR, "assets")), name="assets")

# Include authentication router
app.include_router(auth_router, prefix="/api/auth")

class MobileAccessDeniedException(Exception):
    pass

@app.exception_handler(MobileAccessDeniedException)
async def mobile_access_denied_exception_handler(request: Request, exc: MobileAccessDeniedException):
    return RedirectResponse(url="/desktop/dashboard", status_code=303)

# ==========================================
# КЭШ ДЛЯ ДАШБОРДА
# ==========================================

class DashboardCache:
    def __init__(self, ttl_seconds: int = 30):
        self._cache: dict = {}
        self._ttl = ttl_seconds
    
    def get(self, key: str):
        if key in self._cache:
            data, expires_at = self._cache[key]
            if datetime.now() < expires_at:
                logger.info(f"📦 DASHBOARD CACHE HIT: {key}")
                return data
            else:
                del self._cache[key]
        return None
    
    def set(self, key: str, data):
        expires_at = datetime.now() + timedelta(seconds=self._ttl)
        self._cache[key] = (data, expires_at)
    
    def clear(self):
        self._cache.clear()

_dashboard_cache = DashboardCache(ttl_seconds=120)

# ==========================================
# RATE LIMITER
# ==========================================

class RateLimiter:
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self._requests: dict = {}
    
    def check_and_record(self, client_id: str) -> bool:
        now = datetime.now()
        minute_ago = now - timedelta(minutes=1)
        
        if client_id in self._requests:
            self._requests[client_id] = [ts for ts in self._requests[client_id] if ts > minute_ago]
        else:
            self._requests[client_id] = []
        
        if len(self._requests[client_id]) >= self.requests_per_minute:
            logger.warning(f"🚫 Rate limit exceeded for {client_id}")
            return False
        
        self._requests[client_id].append(now)
        return True

_rate_limiter = RateLimiter(requests_per_minute=60)

def get_client_id(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

# ----- Login page routes -----
from fastapi import Form
from app.services.auth_service import AuthService

# Глобальный экземпляр AuthService (СИНГЛТОН!)
_auth_service_instance: Optional[AuthService] = None

def get_auth_service() -> AuthService:
    global _auth_service_instance
    if _auth_service_instance is None:
        _auth_service_instance = AuthService()
    return _auth_service_instance

@app.get("/")
async def root_redirect(request: Request):
    auth_service = get_auth_service()
    cookie_user_id = request.cookies.get("wms_user_id")
    user_id = auth_service.current_user_id or cookie_user_id
    
    if user_id:
        try:
            user_state = await auth_service.get_user_state(user_id)
            if user_state and user_state.is_logged_in:
                # Если роль не является административной (mover, electrician, technic, security, user) - принудительно на мобильный дашборд
                if user_state.role not in [UserRole.ADMIN, UserRole.INVENTORY_MANAGER, UserRole.SUPERVISOR]:
                    return RedirectResponse(url="/mobile/dashboard", status_code=303)
                else:
                    return RedirectResponse(url="/desktop/dashboard", status_code=303)
        except Exception as e:
            logger.error(f"Error resolving user role in root redirect: {e}")
            
    user_agent = request.headers.get("user-agent", "").lower()
    is_mobile = any(keyword in user_agent for keyword in ["mobi", "android", "iphone", "ipad", "ipod", "opera mini", "iemobile"])
    if is_mobile:
        return RedirectResponse(url="/mobile/dashboard", status_code=303)
    else:
        return RedirectResponse(url="/desktop/dashboard", status_code=303)

@app.get("/login")
async def login_page(request: Request, error: Optional[str] = Query(None)):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@app.post("/login")
async def login_submit(login: str = Form(...), password: str = Form(...)):
    auth_service = get_auth_service()
    try:
        auth_state = await auth_service.login(login, password)
        if auth_state.error:
            return RedirectResponse(url=f"/login?error={auth_state.error}", status_code=303)
        # РЕДИРЕКТИМ ПРЯМО НА ДАШБОРД!
        return RedirectResponse(url="/desktop/dashboard", status_code=303)
    except Exception as e:
        logger.error(f"🔥 Login error: {e}")
        return RedirectResponse(url=f"/login?error=Ошибка сервера: {str(e)}", status_code=303)

@app.get("/profile")
async def profile_page(request: Request):
    auth_service = get_auth_service()
    if auth_service.current_user_id:
        user_state = await auth_service.get_user_state(auth_service.current_user_id)
        user_data = await auth_service.get_user_by_id(auth_service.current_user_id)
        
        return templates.TemplateResponse("profile.html", {
            "request": request,
            "user_name": getattr(user_state, "userName", ""),
            "role": getattr(user_state, "role", ""),
            "user_role": getattr(user_state, "role", ""),  # для base/desktop_base.html
            "user_id": auth_service.current_user_id,
            "user_data": user_data or {},
        })
    return RedirectResponse(url="/login", status_code=303)

@app.get("/logout")
async def logout_route():
    auth_service = get_auth_service()
    await auth_service.logout()
    return RedirectResponse(url="/login", status_code=303)

firebase_status = {
    "connected": False,
    "last_check": None,
    "error": None,
    "collections": {},
}

# ==========================================
# API ЭНДПОИНТЫ
# ==========================================

@app.get("/api/online-users")
async def api_online_users():
    """
    Возвращает список пользователей с их онлайн-статусом.
    Онлайн = lastSeen обновлялся в последние 3 минуты.
    """
    users = await get_internal_users(include_stats=False)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    ONLINE_THRESHOLD_MS = 180_000

    result = []
    for u in users:
        last_seen = u.get("lastSeen")
        is_online = False
        if last_seen and isinstance(last_seen, (int, float)) and last_seen > 0:
            is_online = (now_ms - last_seen) < ONLINE_THRESHOLD_MS
        result.append({
            "userId": u.get("id", ""),
            "displayName": u.get("displayName", u.get("username", "Без имени")),
            "role": u.get("role", "user"),
            "isOnline": is_online,
            "lastSeen": last_seen,
            "isShiftActive": u.get("isShiftActive", False),
        })
    return result

@app.post("/api/ping")
async def api_ping(request: Request):
    """
    Обновляет lastSeen текущего пользователя в Firestore (heartbeat).
    Принимает JSON: {"user_id": "..."} или берёт из десктопной сессии.
    """
    try:
        body = await request.json()
        user_id = body.get("user_id", "")
    except Exception:
        user_id = ""

    # Если нет в body — пробуем взять из десктопной сессии
    if not user_id:
        auth_service = get_auth_service()
        user_id = auth_service.current_user_id

    if not user_id:
        return {"success": False, "error": "user_id не указан и нет активной сессии"}

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    success = await firestore_update_document("internal_users", user_id, {"lastSeen": now_ms})
    if success:
        from app.services.telemetry_service import update_user_last_seen_in_cache
        from app.services.warehouse_service import _cache
        update_user_last_seen_in_cache(user_id, now_ms)
        _cache.clear()
        return {"success": True, "lastSeen": now_ms}
    return {"success": False, "error": "Firestore update failed"}

@app.get("/api/firebase/status")
async def api_firebase_status():
    global firebase_status
    firebase_status = await check_firebase_connection()
    return firebase_status

@app.get("/api/admin/db-telemetry")
async def api_db_telemetry(user_role: str = Query("", description="Роль пользователя")):
    if user_role not in ("admin", "inventory_manager"):
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    from app.services.telemetry_service import get_telemetry_summary_24h
    data = get_telemetry_summary_24h()
    
    # Подсчет онлайн-пользователей
    try:
        users = await get_internal_users(include_stats=False)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        ONLINE_THRESHOLD_MS = 180_000
        online_count = 0
        for u in users:
            last_seen = u.get("lastSeen")
            if last_seen and isinstance(last_seen, (int, float)) and last_seen > 0:
                if (now_ms - last_seen) < ONLINE_THRESHOLD_MS:
                    online_count += 1
        data["metrics"]["online_users"] = max(1, online_count)
    except Exception as e:
        logger.warning(f"Error calculating online users in telemetry: {e}")
        data["metrics"]["online_users"] = 1
        
    return data

# --- НОВЫЕ ЭНДПОИНТЫ ДЛЯ СИНХРОНИЗАЦИИ ---

@app.get("/api/sync/pull", response_model=SyncPullResponse)
async def api_sync_pull(
    last_pulled_at: Optional[datetime] = Query(None, description="Время последней синхронизации")
):
    """
    PULL: Отдает браузеру только те товары, которые изменились после last_pulled_at.
    Если last_pulled_at пустой, отдает всю базу.
    """
    try:
        items = await pull_items_changes(last_pulled_at)
        server_time = datetime.now(timezone.utc)
        return SyncPullResponse(items=items, serverTime=server_time)
    except Exception as e:
        logger.error(f"Sync Pull Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

async def broadcast_operation_toast(user_name: str, action_type: str, item_id: str, quantity: int, recipient_name: str = ""):
    try:
        item = await get_item(item_id)
        item_name = item.get("shortName") if item else "Деталь"
    except Exception:
        item_name = "Деталь"
        
    await manager.broadcast({
        "type": "toast_notification",
        "userName": user_name,
        "actionType": action_type,
        "itemName": item_name,
        "quantity": quantity,
        "recipientName": recipient_name
    })

@app.post("/api/sync/push")
async def api_sync_push(request: SyncPushRequest):
    """
    PUSH: Принимает очередь операций (списания/пополнения), сделанных в офлайне.
    """
    try:
        result = await process_offline_operations(request.operations)
        _dashboard_cache.clear()
        
        # Broadcast sync notification to other clients
        await manager.broadcast({
            "type": "sync_notification",
            "userName": "Сотрудник",
            "count": len(request.operations)
        })
        
        return result
    except Exception as e:
        logger.error(f"Sync Push Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/api/ws/sync")
async def websocket_sync_endpoint(websocket: WebSocket):
    await websocket.accept()
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            
            if action == "pull":
                last_pulled_at_str = data.get("last_pulled_at")
                last_pulled_at = None
                if last_pulled_at_str:
                    try:
                        # Handle trailing Z
                        if last_pulled_at_str.endswith('Z'):
                            last_pulled_at_str = last_pulled_at_str[:-1] + '+00:00'
                        last_pulled_at = datetime.fromisoformat(last_pulled_at_str)
                    except ValueError:
                        pass
                
                try:
                    items = await pull_items_changes(last_pulled_at)
                except Exception as db_err:
                    logger.error(f"WS Pull DB Error: {db_err}")
                    continue
                
                server_time = datetime.now(timezone.utc)
                await websocket.send_json({
                    "type": "pull_response",
                    "items": items,
                    "serverTime": server_time.isoformat()
                })
                    
            elif action == "push":
                operations = data.get("operations", [])
                try:
                    result = await process_offline_operations(operations)
                    _dashboard_cache.clear()
                    
                    # Broadcast sync notification to other clients
                    await manager.broadcast({
                        "type": "sync_notification",
                        "userName": data.get("userName") or "Сотрудник",
                        "count": len(operations)
                    })
                except Exception as db_err:
                    logger.error(f"WS Push DB Error: {db_err}")
                    await websocket.send_json({
                        "type": "push_response",
                        "success": False,
                        "error": str(db_err)
                    })
                    continue
                
                await websocket.send_json({
                    "type": "push_response",
                    "success": True,
                    "result": result
                })
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("Sync Web Worker disconnected")

# -----------------------------------------

@app.get("/api/warehouse/items")
async def api_get_items(limit: int = Query(100, ge=1, le=500)):
    return await get_items(limit=limit)

@app.get("/api/warehouse/items/search")
async def api_search_items(code: str = Query(..., description="Код/SKU для поиска")):
    item = await search_items(code)
    if not item:
        raise HTTPException(status_code=404, detail=f"Товар не найден: {code}")
    return item

@app.get("/api/warehouse/items/{item_id}")
async def api_get_item(item_id: str):
    item = await get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Товар не найден")
    return item

@app.post("/api/warehouse/items")
async def api_create_item(
    item_data: WarehouseItemCreate,
    user_role: str = Query("", description="Роль пользователя для проверки прав"),
):
    # Только admin и inventory_manager могут создавать товары
    if user_role not in ("admin", "inventory_manager"):
        raise HTTPException(status_code=403, detail="Доступ запрещён. Только администратор и менеджер склада могут создавать товары")
    success, result = await create_item(item_data)
    if not success:
        raise HTTPException(status_code=400, detail=result)
    _dashboard_cache.clear()
    return {"success": True, "id": result}

@app.put("/api/warehouse/items/{item_id}")
async def api_update_item(
    item_id: str,
    item_data: WarehouseItemUpdate,
    user_role: str = Query("", description="Роль пользователя для проверки прав"),
):
    # Только admin и inventory_manager могут изменять товары
    if user_role not in ("admin", "inventory_manager"):
        raise HTTPException(status_code=403, detail="Доступ запрещён. Только администратор и менеджер склада могут изменять товары")
    success, error = await update_item(item_id, item_data)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    _dashboard_cache.clear()
    return {"success": True}

@app.delete("/api/warehouse/items/{item_id}")
async def api_delete_item(
    item_id: str,
    user_role: str = Query("", description="Роль пользователя для проверки прав"),
):
    # Только admin и inventory_manager могут удалять товары
    if user_role not in ("admin", "inventory_manager"):
        raise HTTPException(status_code=403, detail="Доступ запрещён. Только администратор и менеджер склада могут удалять товары")
    success, error = await delete_item(item_id)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    _dashboard_cache.clear()
    return {"success": True}

@app.post("/api/warehouse/import-excel")
async def api_import_excel(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_role: str = Query("", description="Роль пользователя для проверки прав")
):
    # Только admin и inventory_manager могут импортировать товары
    if user_role not in ("admin", "inventory_manager"):
        raise HTTPException(status_code=403, detail="Доступ запрещён. Только администратор и менеджер склада могут импортировать Excel")
    
    file_bytes = await file.read()
    task_id = f"excel_{int(time.time())}"
    
    # Запускаем фоновый импорт
    background_tasks.add_task(run_excel_import, file_bytes, task_id)
    return {"success": True, "task_id": task_id}

@app.get("/api/warehouse/import-excel/status/{task_id}")
async def api_import_excel_status(task_id: str):
    if task_id not in import_tasks:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return import_tasks[task_id]


@app.post("/api/warehouse/upload-image")
async def api_upload_item_image(file: UploadFile = File(...)):
    """
    Загрузить фото товара в Cloudinary.
    Принимает multipart/form-data с полем 'file'.
    Возвращает {'url': 'https://res.cloudinary.com/...'}.
    """
    import hashlib
    import time as _time

    # Cloudinary credentials (те же что в excel_importer)
    CLOUD_NAME = "dcmmmfjl2"
    API_KEY = "449877576177452"
    API_SECRET = "Vbsb_HcviiEwTE2zs13g8GNzWqU"
    UPLOAD_URL = f"https://api.cloudinary.com/v1_1/{CLOUD_NAME}/image/upload"
    FOLDER = "qrscanner_parts"

    # Читаем байты
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Пустой файл")

    if len(file_bytes) > 10 * 1024 * 1024:  # 10 МБ лимит
        raise HTTPException(status_code=400, detail="Файл слишком большой (макс. 10 МБ)")

    # Подпись для Cloudinary
    timestamp = str(int(_time.time()))
    to_sign = f"folder={FOLDER}&timestamp={timestamp}{API_SECRET}"
    signature = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()

    # Безопасное имя файла
    safe_name = (file.filename or "photo").replace(" ", "_")
    content_type = file.content_type or "image/jpeg"

    files = {"file": (safe_name, file_bytes, content_type)}
    data = {
        "api_key": API_KEY,
        "timestamp": timestamp,
        "signature": signature,
        "folder": FOLDER,
    }

    try:
        from app.services.warehouse_service import get_http_client
        client = get_http_client()
        res = await client.post(UPLOAD_URL, files=files, data=data, timeout=30.0)
        if res.status_code == 200:
            url = res.json().get("secure_url")
            logger.info(f"✅ Фото загружено в Cloudinary: {url}")
            return {"url": url}
        else:
            logger.error(f"❌ Cloudinary error {res.status_code}: {res.text[:300]}")
            raise HTTPException(status_code=502, detail=f"Ошибка Cloudinary: {res.status_code}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Upload exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def _validate_user_from_request(request_user_id: str) -> str:
    """
    Проверяет, что userId из запроса соответствует активной сессии.
    Возвращает валидный userId.
    Для десктопа — проверяет auth_service.current_user_id.
    Для мобильных — проверяет _mobile_auth_sessions.
    """
    auth_service = get_auth_service()
    
    # Если есть десктопная сессия — userId должен совпадать
    if auth_service.current_user_id:
        if request_user_id and request_user_id != auth_service.current_user_id:
            raise HTTPException(status_code=403, detail="Нельзя выполнить операцию от имени другого пользователя")
        return auth_service.current_user_id
    
    # Если это мобильный запрос — проверяем наличие сессии
    if request_user_id:
        if request_user_id not in _mobile_auth_sessions:
            # Попробуем восстановить сессию из Firestore (при перезапуске сервера)
            try:
                auth_state = await auth_service.get_user_state(request_user_id)
                if auth_state and auth_state.is_logged_in:
                    _mobile_auth_sessions[request_user_id] = auth_state
                    return request_user_id
            except Exception as e:
                logger.error(f"Error restoring mobile session from Firestore: {e}")
            raise HTTPException(status_code=403, detail="Сессия не найдена. Выполните вход заново.")
        return request_user_id
    
    # Без авторизации — разрешаем, но логируем (для обратной совместимости)
    logger.warning("⚠️ take/add без авторизации (нет userId и нет desktop сессии)")
    return ""


@app.post("/api/warehouse/take")
async def api_take_item(request: TakeItemRequest):
    # Валидация userId из сессии
    validated_user_id = await _validate_user_from_request(request.userId)
    
    success, msg = await take_item(
        item_id=request.itemId,
        quantity=request.quantity,
        user_name=request.userName,
        user_id=validated_user_id or request.userId,
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    _dashboard_cache.clear()
    
    # Broadcast real-time toast
    await broadcast_operation_toast(request.userName, "TAKE", request.itemId, request.quantity)
    
    return {"success": True, "message": msg}


@app.post("/api/warehouse/take-batch")
async def api_take_items_batch(request: TakeItemBatchRequest):
    # Валидация userId из сессии
    validated_user_id = await _validate_user_from_request(request.userId)
    
    items_list = [{"itemId": item.itemId, "quantity": item.quantity} for item in request.items]
    
    success, msg = await take_items_batch(
        items=items_list,
        user_name=request.userName,
        user_id=validated_user_id or request.userId,
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    _dashboard_cache.clear()
    
    # Broadcast real-time toast for each item in the batch
    for item in request.items:
        await broadcast_operation_toast(request.userName, "TAKE", item.itemId, item.quantity)
        
    return {"success": True, "message": msg}

@app.post("/api/warehouse/add")
async def api_add_stock(request: AddStockRequest):
    # Валидация userId из сессии
    validated_user_id = await _validate_user_from_request(request.userId)
    
    success, msg = await add_stock(
        item_id=request.itemId,
        quantity=request.quantity,
        user_name=request.userName,
        user_id=validated_user_id or request.userId,
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    _dashboard_cache.clear()
    
    # Broadcast real-time toast
    await broadcast_operation_toast(request.userName, "ADD", request.itemId, request.quantity)
    
    return {"success": True, "message": msg}


# --- НОВЫЕ ЭНДПОИНТЫ ДЛЯ ВЫДАЧИ С ВЫБОРОМ ПОЛУЧАТЕЛЯ ---

@app.post("/api/warehouse/take-extended")
async def api_take_item_extended(request: TakeItemExtendedRequest):
    """
    Расширенная выдача: кладовщик выдаёт товар сотруднику.
    В логе сохраняется кто выдал (issuer) и кому (recipient).
    """
    auth_service = get_auth_service()
    
    # Заполняем данные выдающего из текущего сеанса
    issuer_name = request.issuerName or getattr(auth_service, 'current_user_name', 'Кладовщик')
    issuer_id = request.issuerId or (auth_service.current_user_id or "")
    
    success, msg = await take_item_to_recipient(
        item_id=request.itemId,
        quantity=request.quantity,
        recipient_name=request.recipientName,
        recipient_id=request.recipientId,
        issuer_name=issuer_name,
        issuer_id=issuer_id,
        notes=request.notes,
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    _dashboard_cache.clear()
    
    # Broadcast real-time toast
    await broadcast_operation_toast(issuer_name, "TAKE_EXTENDED", request.itemId, request.quantity, request.recipientName)
    
    return {"success": True, "message": msg}


@app.post("/api/warehouse/return")
async def api_return_item(request: ReturnItemRequest):
    """
    Возврат товара на склад от сотрудника.
    """
    auth_service = get_auth_service()
    
    issuer_name = request.issuerName or getattr(auth_service, 'current_user_name', 'Кладовщик')
    issuer_id = request.issuerId or (auth_service.current_user_id or "")
    
    success, msg = await return_item_to_stock(
        item_id=request.itemId,
        quantity=request.quantity,
        recipient_name=request.recipientName,
        recipient_id=request.recipientId,
        issuer_name=issuer_name,
        issuer_id=issuer_id,
        notes=request.notes,
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    _dashboard_cache.clear()
    
    # Broadcast real-time toast
    await broadcast_operation_toast(issuer_name, "RETURN", request.itemId, request.quantity, request.recipientName)
    
    return {"success": True, "message": msg}

# --- КОНЕЦ НОВЫХ ЭНДПОИНТОВ ---

@app.get("/api/warehouse/dashboard-summary", response_model=DashboardSummary)
async def api_get_dashboard_summary():
    """
    Возвращает сводные показатели склада для дашборда с кэшированием.
    Служит для уменьшения количества запросов от клиентов.
    """
    cache_key = "api_dashboard_summary"
    cached = _dashboard_cache.get(cache_key)
    if cached is not None:
        return cached

    items = await get_items(limit=1000, use_cache=True)
    orders = await get_orders(limit=100)
    logs = await get_logs(limit=50)

    total_items = sum(item.get("stockCount", 0) for item in items)
    low_stock_count = sum(1 for item in items if item.get("stockCount", 0) < item.get("lowStockThreshold", 10))
    active_orders_count = sum(1 for o in orders if o.get("status") in ["CREATED", "PROCESSING", "READY"])
    
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_operations_count = 0
    
    for log in logs:
        ts = log.get("timestamp")
        if ts:
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except:
                    ts = None
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= today_start:
                    today_operations_count += 1

    recent_logs = []
    for log in logs[:5]:
        ts = log.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except:
                ts = None
        if isinstance(ts, datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
            
        recent_logs.append(WarehouseLog(
            id=log.get("id", ""),
            itemId=log.get("itemId", ""),
            itemName=log.get("itemName", "Неизвестно"),
            userId=log.get("userId", ""),
            userName=log.get("userName", "Неизвестный"),
            quantityChange=log.get("quantityChange", 0),
            timestamp=ts
        ))

    summary = DashboardSummary(
        totalItems=total_items,
        lowStockCount=low_stock_count,
        activeOrdersCount=active_orders_count,
        todayOperationsCount=today_operations_count,
        recentLogs=recent_logs
    )
    
    _dashboard_cache.set(cache_key, summary)
    return summary

@app.get("/api/warehouse/forecast", response_model=List[ForecastItem])
async def api_get_forecast(
    days: int = Query(30, ge=7, le=90, description="Период анализа в днях"),
):
    """
    Прогноз остатков: на сколько дней хватит каждого товара.
    Кэшируется на 60 секунд.
    """
    from app.services.forecast_service import calculate_forecast
    return await calculate_forecast(days=days)


@app.get("/api/warehouse/logs")
async def api_get_logs(limit: int = Query(50, ge=1, le=200)):
    return await get_logs(limit)

@app.get("/api/warehouse/logs/employee/{user_id}")
async def api_get_logs_for_employee(user_id: str):
    return await get_logs_for_employee(user_id)

@app.get("/api/warehouse/logs/grouped")
async def api_get_grouped_logs() -> List[GroupedActivity]:
    return await get_grouped_logs()

@app.get("/api/warehouse/orders")
async def api_get_orders(
    status: Optional[str] = Query(None, description="Фильтр по статусам через запятую"),
    userId: Optional[str] = Query(None, description="Фильтр по ID пользователя"),
    limit: int = Query(100, ge=1, le=500),
):
    return await get_orders(status_filter=status, user_id=userId, limit=limit)

@app.post("/api/warehouse/orders")
async def api_create_order(order_data: WarehouseOrderCreate):
    success, doc_id, error = await create_order(order_data)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    _dashboard_cache.clear()
    return {"success": True, "id": doc_id}

@app.patch("/api/warehouse/orders/{order_id}/status")
async def api_update_order_status(order_id: str, update: dict):
    try:
        new_status = OrderStatus(update["status"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=400, detail="Неверный статус")
    success, error = await update_order_status(order_id, new_status)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    _dashboard_cache.clear()
    return {"success": True}

@app.post("/api/warehouse/orders/{order_id}/complete")
async def api_complete_order(order_id: str, request: CompleteOrderRequest):
    success, msg = await complete_order(order_id, request.warehouseManName)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    _dashboard_cache.clear()
    return {"success": True, "message": msg}

@app.get("/api/warehouse/news")
async def api_get_news():
    return await get_news()

@app.post("/api/warehouse/news")
async def api_create_news(news_data: NewsItemCreate):
    success, error = await create_news(news_data)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return {"success": True}

@app.put("/api/warehouse/news/{news_id}")
async def api_update_news(news_id: str, news_data: NewsItemCreate):
    success, error = await update_news(news_id, news_data)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return {"success": True}

@app.delete("/api/warehouse/news/{news_id}")
async def api_delete_news(news_id: str):
    success, error = await delete_news(news_id)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return {"success": True}

@app.get("/api/warehouse/employees")
async def api_get_employees():
    return await get_employees()

@app.get("/api/internal-users")
async def api_get_internal_users():
    return await get_internal_users(include_stats=False)

@app.get("/api/internal-users/presence")
async def api_get_internal_users_presence():
    users = await get_internal_users(include_stats=True)
    presence_data = []
    for u in users:
        presence_data.append({
            "id": u.get("id"),
            "lastSeen": u.get("lastSeen"),
            "isShiftActive": u.get("isShiftActive", False),
            "shiftStartTime": u.get("shiftStartTime"),
            "scansToday": u.get("scansToday", 0),
            "batchesToday": u.get("batchesToday", 0),
            "scanRatePerHour": u.get("scanRatePerHour", 0),
        })
    return presence_data

# @app.post("/api/internal-users")
# async def api_create_internal_user(user_data: dict):
#     success, result = await create_internal_user(user_data)
#     if not success:
#         raise HTTPException(status_code=400, detail=result)
#     _dashboard_cache.clear()
#     return JSONResponse({"success": True, "id": result}, status_code=201)
# 
# @app.put("/api/internal-users/{user_id}")
# async def api_update_internal_user(user_id: str, user_data: dict):
#     success, error = await update_internal_user(user_id, user_data)
#     if not success:
#         raise HTTPException(status_code=400, detail=error)
#     _dashboard_cache.clear()
#     return {"success": True}
# 
# @app.delete("/api/internal-users/{user_id}")
# async def api_delete_internal_user(user_id: str):
#     success, error = await delete_internal_user(user_id)
#     if not success:
#         raise HTTPException(status_code=400, detail=error)
#     _dashboard_cache.clear()
#     return {"success": True}

@app.get("/api/history")
async def api_get_history(
    employee: Optional[str] = None,
    dateFrom: Optional[str] = None,
    dateTo: Optional[str] = None,
    lastTimestamp: Optional[str] = None,
):
    if lastTimestamp:
        try:
            from app.services.warehouse_service import firestore_query_with_filter
            clean_ts = lastTimestamp.replace('Z', '+00:00')
            last_dt = datetime.fromisoformat(clean_ts)
            logs = await firestore_query_with_filter(
                collection="warehouse_logs",
                field="timestamp",
                operator="GREATER_THAN",
                value=last_dt,
                limit=1000
            )
        except ValueError as e:
            logger.error(f"Failed to parse lastTimestamp {lastTimestamp}: {e}")
            logs = []
    else:
        logs = await get_logs(limit=1000)

    if employee:
        logs = [log for log in logs if log.get("userName") == employee or log.get("userId") == employee]

    if dateFrom:
        try:
            dt_from = datetime.fromisoformat(dateFrom).replace(tzinfo=timezone.utc)
            logs = [log for log in logs if log.get("timestamp") and log["timestamp"] >= dt_from]
        except ValueError:
            pass

    if dateTo:
        try:
            if 'T' in dateTo:
                dt_to = datetime.fromisoformat(dateTo).replace(tzinfo=timezone.utc)
            else:
                dt_to = datetime.fromisoformat(dateTo + 'T23:59:59').replace(tzinfo=timezone.utc)
            logs = [log for log in logs if log.get("timestamp") and log["timestamp"] <= dt_to]
        except ValueError:
            pass

    def serialize_dt(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return obj

    result = []
    for log in logs:
        row = {k: serialize_dt(v) for k, v in log.items()}
        result.append(row)

    return result

@app.get("/api/history/stats")
async def api_get_history_stats(
    dateFrom: Optional[str] = None,
    dateTo: Optional[str] = None,
):
    logs = await get_logs(limit=500)

    if dateFrom:
        try:
            dt_from = datetime.fromisoformat(dateFrom).replace(tzinfo=timezone.utc)
            logs = [log for log in logs if log.get("timestamp") and log["timestamp"] >= dt_from]
        except ValueError:
            pass
    if dateTo:
        try:
            if 'T' in dateTo:
                dt_to = datetime.fromisoformat(dateTo).replace(tzinfo=timezone.utc)
            else:
                dt_to = datetime.fromisoformat(dateTo + 'T23:59:59').replace(tzinfo=timezone.utc)
            logs = [log for log in logs if log.get("timestamp") and log["timestamp"] <= dt_to]
        except ValueError:
            pass

    day_counts = {}
    for log in logs:
        ts = log.get("timestamp")
        if ts and isinstance(ts, datetime):
            day_key = ts.strftime("%Y-%m-%d")
            day_counts[day_key] = day_counts.get(day_key, 0) + 1

    sorted_days = sorted(day_counts.keys())
    return HistoryStats(
        dates=sorted_days,
        counts=[day_counts[d] for d in sorted_days],
    )


@app.get("/api/history/summary")
async def api_get_history_summary(
    employee: Optional[str] = Query(None),
    dateFrom: Optional[str] = Query(None),
    dateTo: Optional[str] = Query(None),
):
    """Сводка инвентаризации: по сотрудникам и общая по товарам за период."""
    try:
        summary = await get_history_summary(
            employee=employee,
            dateFrom=dateFrom,
            dateTo=dateTo,
            limit=500
        )
        return summary
    except Exception as e:
        logger.error(f"🔥 History summary error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# ДЕСКТОПНЫЕ СТРАНИЦЫ
# ==========================================

# Desktop pages are now handled via React SPA client-side routing.

# ==========================================
# МОБИЛЬНЫЕ API (логин/профиль)
# ==========================================

from pydantic import BaseModel

class MobileLoginRequest(BaseModel):
    username: str
    password: str

_mobile_auth_sessions: dict = {}  # простейшая сессия: user_id -> auth_state

@app.post("/api/mobile/login")
async def mobile_api_login(request: Request, response: Response):
    try:
        body = await request.json()
        login = body.get("login", body.get("email", "")).strip()
        password = body.get("password", "")
    except Exception:
        return {"success": False, "error": "Неверный формат запроса"}

    if not login or not password:
        return {"success": False, "error": "Заполните логин и пароль"}

    auth_service = get_auth_service()
    try:
        auth_state = await auth_service.login(login, password)
        if auth_state.error or not auth_state.is_logged_in:
            return {"success": False, "error": auth_state.error or "Ошибка входа"}

        # Сохраняем сессию
        _mobile_auth_sessions[auth_state.user_id] = auth_state

        # Сохраняем user_id в HTTP-only cookie для восстановления сессии и редиректов
        if auth_state.user_id:
            response.set_cookie(
                key="wms_user_id",
                value=auth_state.user_id,
                httponly=True,
                max_age=60 * 60 * 24 * 7,  # 7 дней
                samesite="lax",
            )

        role_display = role_display_names.get(auth_state.role.value, "Сотрудник")
        return {
            "success": True,
            "user_id": auth_state.user_id,
            "user_name": auth_state.user_name,
            "user_role": auth_state.role.value,
            "user_display": role_display,
        }
    except Exception as e:
        logger.error(f"🔥 Mobile login error: {e}")
        return {"success": False, "error": "Ошибка сервера. Попробуйте позже."}

@app.post("/api/mobile/logout")
async def mobile_api_logout(request: Request, response: Response):
    try:
        body = await request.json()
        user_id = body.get("user_id", "")
    except Exception:
        user_id = ""

    auth_service = get_auth_service()
    if user_id and user_id in _mobile_auth_sessions:
        del _mobile_auth_sessions[user_id]

    await auth_service.logout()
    response.delete_cookie(key="wms_user_id")
    return {"success": True}

@app.get("/api/mobile/stats")
async def mobile_api_stats(request: Request):
    """Возвращает базовую статистику для профиля."""
    try:
        items = await get_items(limit=500)
        orders = await get_orders(limit=100)

        total_items = sum(item.get("stockCount", 0) for item in items)
        active_orders = [o for o in orders if o.get("status") in ["CREATED", "PROCESSING", "READY"]]
        low_stock = [i for i in items if i.get("stockCount", 0) < i.get("lowStockThreshold", 10)]

        return {
            "total_items": total_items,
            "active_orders": len(active_orders),
            "low_stock": len(low_stock),
        }
    except Exception as e:
        logger.error(f"🔥 Mobile stats error: {e}")
        return {"total_items": 0, "active_orders": 0, "low_stock": 0}

# ==========================================
# МОБИЛЬНЫЕ СТРАНИЦЫ
# ==========================================

role_display_names = {
    "muver": "Мувер",
    "electrician": "Электрик",
    "technic": "Техник",
    "admin": "Администратор",
    "inventory_manager": "Менеджер склада",
    "staff": "Сотрудник",
}

async def _resolve_mobile_user(request: Request) -> dict:
    """
    Достаёт данные пользователя из query-параметров или sessionStorage сессии.
    Если пользователь не авторизован — возвращает словарь с ошибкой.
    """
    user_id = request.query_params.get("user_id", "").strip()
    user_role = request.query_params.get("user_role", "").strip()
    user_name = request.query_params.get("user_name", "").strip()

    # Попробуем также достать из куки/активной сессии, если нет в query
    if not user_id:
        auth_service = get_auth_service()
        cookie_user_id = request.cookies.get("wms_user_id")
        user_id = auth_service.current_user_id or cookie_user_id

    # Если данные переданы или восстановлены
    if user_id:
        # Проверяем, есть ли сессия в _mobile_auth_sessions
        if user_id not in _mobile_auth_sessions:
            # Попробуем восстановить сессию из Firestore (при перезапуске сервера)
            try:
                auth_service = get_auth_service()
                auth_state = await auth_service.get_user_state(user_id)
                if auth_state and auth_state.is_logged_in:
                    _mobile_auth_sessions[user_id] = auth_state
            except Exception as e:
                logger.error(f"Error restoring mobile session for UI: {e}")

        if user_id in _mobile_auth_sessions:
            session = _mobile_auth_sessions[user_id]
            
            # Если роль является административной — принудительно перенаправляем на десктоп
            if session.role in [UserRole.ADMIN, UserRole.INVENTORY_MANAGER, UserRole.SUPERVISOR]:
                logger.info(f"👮 Administrative user {user_id} ({session.role}) accessed mobile route. Redirecting to desktop.")
                raise MobileAccessDeniedException()

            return {
                "authenticated": True,
                "user_id": user_id,
                "user_name": user_name or getattr(session, "user_name", "Сотрудник"),
                "user_role": user_role or getattr(session, "role", "muver"),
                "user_role_display": role_display_names.get(user_role or getattr(session, "role", "muver"), "Сотрудник"),
            }
        # Сессия не найдена — возможно, устарела
        logger.warning(f"⚠️ Mobile session not found for user_id={user_id}, allowing with query params")

    # Без авторизации — возвращаем данные как есть (с хардкодом только если пусто)
    return {
        "authenticated": bool(user_id),
        "user_id": user_id,
        "user_name": user_name or "Гость",
        "user_role": user_role or "user",
        "user_role_display": role_display_names.get(user_role, "Гость") if user_role else "Гость",
    }


def get_mobile_context(
    user_name: str = "Гость",
    user_role: str = "user",
    warehouse: str = "Бестужевская 10",
    active_tab: str = "dashboard",
    user_id: str = "",
):
    return {
        "user_name": user_name,
        "user_role": user_role,
        "user_role_display": role_display_names.get(user_role, "Сотрудник"),
        "warehouse": warehouse,
        "active_tab": active_tab,
        "user_id": user_id,
    }

# Mobile pages are now handled via React SPA client-side routing.

# ==========================================
# МОБИЛЬНЫЙ API — МОИ ОПЕРАЦИИ
# ==========================================

@app.get("/api/mobile/my-transactions")
async def mobile_my_transactions_api(
    request: Request,
    user_id: str = Query(""),
    limit: int = Query(500, ge=1, le=1000),
):
    """Возвращает сырой список логов операций для построения реактивной истории на клиенте."""
    try:
        if not user_id or user_id == "all":
            logs = await get_logs(limit=limit)
        else:
            logs = await get_logs_for_employee(user_id, limit=limit)
    except Exception as e:
        logger.error(f"🔥 my-transactions error: {e}")
        return {"success": False, "error": str(e), "logs": []}

    try:
        items = await get_items(limit=1000)
        item_cats = {item.get("id"): item.get("category", "Общее") for item in items}
    except Exception as e:
        logger.error(f"🔥 failed to fetch items for categories: {e}")
        item_cats = {}

    serialized_logs = []
    for log in logs:
        ts = log.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except:
                ts = None

        if ts and isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts_str = ts.isoformat()
        else:
            ts_str = None

        serialized_logs.append({
            "id": log.get("id", ""),
            "itemId": log.get("itemId", ""),
            "itemName": log.get("itemName", "Неизвестно"),
            "category": item_cats.get(log.get("itemId"), "Общее"),
            "quantityChange": log.get("quantityChange", 0) or 0,
            "userId": log.get("userId", ""),
            "userName": log.get("userName", "Неизвестно"),
            "timestamp": ts_str,
        })

    return {
        "success": True,
        "logs": serialized_logs,
    }

# ==========================================
# МОБИЛЬНЫЙ ЭКРАН — НАЧАЛО СМЕНЫ (Shift Lock Screen)
# ==========================================

# Shift lock page is now handled via React SPA client-side routing.


@app.post("/api/mobile/shift/start")
async def mobile_api_shift_start(request: Request):
    """
    Начать смену для мобильного веб-интерфейса.
    """
    try:
        body = await request.json()
        user_id = body.get("user_id", "").strip()
    except Exception:
        return {"success": False, "error": "Неверный формат запроса"}

    if not user_id:
        return {"success": False, "error": "user_id обязателен"}

    try:
        # Обновляем в Firestore
        now_ms = int(datetime.now().timestamp() * 1000)
        success = await firestore_update_document("internal_users", user_id, {
            "isShiftActive": True,
            "shiftStartTime": now_ms,
            "shiftRequestStatus": "APPROVED"
        })
        if not success:
            return {"success": False, "error": "Ошибка при записи в базу данных (Firestore)"}

        # Очищаем кэш и получаем обновленные данные из Firestore
        auth_service = get_auth_service()
        auth_service.clear_user_cache(user_id)
        user_data = await auth_service.get_user_by_id(user_id, use_cache=True)
        display_name = user_data.get("displayName") if user_data else "Сотрудник"
        role = user_data.get("role") if user_data else "muver"
        is_allowed = user_data.get("isAllowedToWork", True) if user_data else True

        from app.models import AuthState
        _mobile_auth_sessions[user_id] = AuthState(
            is_logged_in=True,
            user_id=user_id,
            user_name=display_name,
            role=UserRole.from_key(role),
            is_admin=role == "admin",
            is_shift_active=True,
            shift_start_time=now_ms,
            is_allowed_to_work=is_allowed,
            shift_request_status=ShiftRequestStatus.APPROVED
        )

        logger.info(f"🟢 Смена успешно начата для пользователя {user_id} ({display_name})")
        return {"success": True}
    except Exception as e:
        logger.error(f"🔥 Mobile shift start error: {e}")
        return {"success": False, "error": f"Ошибка сервера: {str(e)}"}


@app.post("/api/mobile/shift/request-access")
async def mobile_api_shift_request_access(request: Request):
    """
    Запросить доступ к смене (статус PENDING).
    """
    try:
        body = await request.json()
        user_id = body.get("user_id", "").strip()
    except Exception:
        return {"success": False, "error": "Неверный формат запроса"}

    if not user_id:
        return {"success": False, "error": "user_id обязателен"}

    try:
        # Обновляем статус в Firestore
        success = await firestore_update_document("internal_users", user_id, {
            "shiftRequestStatus": "PENDING"
        })
        if not success:
            return {"success": False, "error": "Ошибка при записи в базу данных"}

        # Обновляем локальную сессию
        if user_id in _mobile_auth_sessions:
            _mobile_auth_sessions[user_id].shift_request_status = ShiftRequestStatus.PENDING

        # Очищаем кэш авторизации (в памяти и в SQLite)
        auth_service = get_auth_service()
        auth_service.clear_user_cache(user_id)

        logger.info(f"📩 Запрошен доступ к смене для пользователя {user_id}")
        return {"success": True}
    except Exception as e:
        logger.error(f"🔥 Mobile request access error: {e}")
        return {"success": False, "error": f"Ошибка сервера: {str(e)}"}


@app.get("/api/mobile/status")
async def mobile_status():
    """Системный статус (ping, версия). Только чтение."""
    return {
        "status": "ok",
        "version": "1.0.5",
        "timestamp": datetime.now().isoformat(),
    }


# ==========================================
# МОБИЛЬНЫЕ СТРАНИЦЫ
# ==========================================

@app.get("/mobile/login")
async def mobile_login(request: Request):
    auth_service = get_auth_service()
    cookie_user_id = request.cookies.get("wms_user_id")
    user_id = auth_service.current_user_id or cookie_user_id
    if user_id:
        try:
            user_state = await auth_service.get_user_state(user_id)
            if user_state and user_state.is_logged_in:
                if user_state.role in [UserRole.ADMIN, UserRole.INVENTORY_MANAGER, UserRole.SUPERVISOR]:
                    return RedirectResponse(url="/desktop/dashboard", status_code=303)
                else:
                    return RedirectResponse(url="/mobile/dashboard", status_code=303)
        except Exception:
            pass
    return templates.TemplateResponse("mobile/mobile_login.html", {"request": request})


@app.get("/mobile/dashboard")
async def mobile_dashboard(request: Request):
    user_info = await _resolve_mobile_user(request)
    if not user_info.get("authenticated"):
        return RedirectResponse(url="/mobile/login", status_code=303)
        
    auth_service = get_auth_service()
    user_state = await auth_service.get_user_state(user_info["user_id"])
    if not user_state.is_shift_active:
        return RedirectResponse(
            url=f"/mobile/shift_lock?user_id={user_info['user_id']}&user_role={user_info['user_role']}&user_name={user_info['user_name']}",
            status_code=303
        )
        
    items = await get_items(limit=500)
    orders = await get_orders(limit=100)
    logs = await get_logs(limit=50)
    news = await get_news(limit=10)
    
    total_items = sum(item.get("stockCount", 0) for item in items)
    low_stock_count = sum(1 for item in items if item.get("stockCount", 0) < item.get("lowStockThreshold", 10))
    active_orders_count = sum(1 for o in orders if o.get("status") in ["CREATED", "PROCESSING", "READY"])
    
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_operations = 0
    for log in logs:
        ts = log.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except:
                ts = None
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= today_start:
                today_operations += 1
                
    recent_logs = []
    for log in logs[:5]:
        ts = log.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except:
                ts = None
        time_str = ts.strftime("%H:%M") if ts else ""
        recent_logs.append({
            "user_name": log.get("userName") or "Неизвестный",
            "action": "Взял" if log.get("quantityChange", 0) < 0 else "Добавил",
            "item_name": log.get("itemName") or "Неизвестно",
            "quantity": abs(log.get("quantityChange", 0)),
            "time": time_str
        })
        
    popular_items = []
    for item in items[:6]:
        popular_items.append({
            "id": item.get("id"),
            "name": item.get("shortName") or item.get("fullName"),
            "imageUrl": item.get("imageUrl"),
            "sku": item.get("sku") or "—",
            "stock": item.get("stockCount", 0),
            "unit": item.get("unit") or "шт."
        })
        
    context = get_mobile_context(
        user_name=user_info["user_name"],
        user_role=user_info["user_role"],
        active_tab="dashboard",
        user_id=user_info["user_id"]
    )
    context.update({
        "request": request,
        "total_items": total_items,
        "active_orders_count": active_orders_count,
        "low_stock_count": low_stock_count,
        "today_operations": today_operations,
        "catalog": popular_items,
        "recent_logs": recent_logs,
        "news": news,
    })
    return templates.TemplateResponse("mobile/dashboard.html", context)


@app.get("/mobile/parts_list")
async def mobile_parts_list(request: Request):
    user_info = await _resolve_mobile_user(request)
    if not user_info.get("authenticated"):
        return RedirectResponse(url="/mobile/login", status_code=303)
        
    auth_service = get_auth_service()
    user_state = await auth_service.get_user_state(user_info["user_id"])
    if not user_state.is_shift_active:
        return RedirectResponse(
            url=f"/mobile/shift_lock?user_id={user_info['user_id']}&user_role={user_info['user_role']}&user_name={user_info['user_name']}",
            status_code=303
        )
        
    items = await get_items(limit=1000)
    orders = await get_orders(limit=100)
    logs = await get_logs(limit=200)
    users = await get_internal_users(include_stats=False)
    
    low_stock_items_count = sum(1 for item in items if item.get("stockCount", 0) < item.get("lowStockThreshold", 10))
    
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    taken_today_count = 0
    for log in logs:
        ts = log.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except:
                ts = None
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= today_start and log.get("quantityChange", 0) < 0:
                taken_today_count += abs(log["quantityChange"])
                
    active_orders = [o for o in orders if o.get("status") in ["CREATED", "PROCESSING", "READY"]]
    can_manage = user_info["user_role"] in ["admin", "inventory_manager"]
    
    all_users_list = []
    for u in users:
        all_users_list.append({
            "id": u.get("id"),
            "name": u.get("displayName") or u.get("username") or "Сотрудник"
        })
        
    formatted_items = []
    for item in items:
        formatted_items.append({
            "id": item.get("id"),
            "fullName": item.get("fullName") or "",
            "shortName": item.get("shortName") or "",
            "sku": item.get("sku") or "",
            "unit": item.get("unit") or "шт.",
            "stockCount": item.get("stockCount", 0),
            "totalStock": item.get("totalStock", 0),
            "lowStockThreshold": item.get("lowStockThreshold", 10),
            "imageUrl": item.get("imageUrl"),
            "category": item.get("category") or "Общее",
        })
        
    context = get_mobile_context(
        user_name=user_info["user_name"],
        user_role=user_info["user_role"],
        active_tab="catalog",
        user_id=user_info["user_id"]
    )
    context.update({
        "request": request,
        "items": formatted_items,
        "low_stock_items_count": low_stock_items_count,
        "taken_today_count": taken_today_count,
        "orders": active_orders,
        "all_users": all_users_list,
        "can_manage": can_manage,
    })
    return templates.TemplateResponse("mobile/parts_list.html", context)


@app.get("/mobile/my_transactions")
async def mobile_my_transactions(request: Request):
    user_info = await _resolve_mobile_user(request)
    if not user_info.get("authenticated"):
        return RedirectResponse(url="/mobile/login", status_code=303)
        
    auth_service = get_auth_service()
    user_state = await auth_service.get_user_state(user_info["user_id"])
    if not user_state.is_shift_active:
        return RedirectResponse(
            url=f"/mobile/shift_lock?user_id={user_info['user_id']}&user_role={user_info['user_role']}&user_name={user_info['user_name']}",
            status_code=303
        )
        
    users = await get_internal_users(include_stats=False)
    all_users_list = []
    for u in users:
        all_users_list.append({
            "id": u.get("id"),
            "name": u.get("displayName") or u.get("username") or "Сотрудник"
        })

    context = get_mobile_context(
        user_name=user_info["user_name"],
        user_role=user_info["user_role"],
        active_tab="transactions",
        user_id=user_info["user_id"]
    )
    context.update({
        "request": request,
        "all_users": all_users_list
    })
    return templates.TemplateResponse("mobile/my_transactions.html", context)


@app.get("/mobile/shift_lock")
async def mobile_shift_lock(request: Request):
    user_info = await _resolve_mobile_user(request)
    if not user_info.get("authenticated"):
        return RedirectResponse(url="/mobile/login", status_code=303)
        
    auth_service = get_auth_service()
    user_state = await auth_service.get_user_state(user_info["user_id"])
    if user_state.is_shift_active:
        return RedirectResponse(
            url=f"/mobile/dashboard?user_id={user_info['user_id']}&user_role={user_info['user_role']}&user_name={user_info['user_name']}",
            status_code=303
        )
        
    context = get_mobile_context(
        user_name=user_info["user_name"],
        user_role=user_info["user_role"],
        active_tab="dashboard",
        user_id=user_info["user_id"]
    )
    context.update({
        "request": request,
        "is_allowed_to_work": user_state.is_allowed_to_work,
        "shift_request_status": user_state.shift_request_status.value,
    })
    return templates.TemplateResponse("mobile/shift_lock.html", context)


@app.get("/mobile/profile")
async def mobile_profile(request: Request):
    user_info = await _resolve_mobile_user(request)
    if not user_info.get("authenticated"):
        return RedirectResponse(url="/mobile/login", status_code=303)
        
    auth_service = get_auth_service()
    user_state = await auth_service.get_user_state(user_info["user_id"])
    if not user_state.is_shift_active:
        return RedirectResponse(
            url=f"/mobile/shift_lock?user_id={user_info['user_id']}&user_role={user_info['user_role']}&user_name={user_info['user_name']}",
            status_code=303
        )
        
    context = get_mobile_context(
        user_name=user_info["user_name"],
        user_role=user_info["user_role"],
        active_tab="profile",
        user_id=user_info["user_id"]
    )
    context.update({"request": request})
    return templates.TemplateResponse("mobile/profile.html", context)


@app.get("/mobile/scan")
async def mobile_scan(request: Request):
    user_info = await _resolve_mobile_user(request)
    if not user_info.get("authenticated"):
        return RedirectResponse(url="/mobile/login", status_code=303)
        
    auth_service = get_auth_service()
    user_state = await auth_service.get_user_state(user_info["user_id"])
    if not user_state.is_shift_active:
        return RedirectResponse(
            url=f"/mobile/shift_lock?user_id={user_info['user_id']}&user_role={user_info['user_role']}&user_name={user_info['user_name']}",
            status_code=303
        )
        
    context = get_mobile_context(
        user_name=user_info["user_name"],
        user_role=user_info["user_role"],
        active_tab="scan",
        user_id=user_info["user_id"]
    )
    context.update({"request": request})
    return templates.TemplateResponse("mobile/scan.html", context)


@app.get("/mobile/take_part")
async def mobile_take_part(
    request: Request,
    id: Optional[str] = Query(None, description="ID товара"),
    sku: Optional[str] = Query(None, description="SKU товара"),
    code: Optional[str] = Query(None, description="Код/SKU товара")
):
    user_info = await _resolve_mobile_user(request)
    if not user_info.get("authenticated"):
        return RedirectResponse(url="/mobile/login", status_code=303)
        
    auth_service = get_auth_service()
    user_state = await auth_service.get_user_state(user_info["user_id"])
    if not user_state.is_shift_active:
        return RedirectResponse(
            url=f"/mobile/shift_lock?user_id={user_info['user_id']}&user_role={user_info['user_role']}&user_name={user_info['user_name']}",
            status_code=303
        )
        
    item = None
    # 1. Попытка по id
    if id:
        item = await get_item(id)
        if not item:
            # Возможно, в параметре id передан SKU/код детали
            item = await search_items(id)
            
    # 2. Попытка по sku
    if not item and sku:
        item = await search_items(sku)
        
    # 3. Попытка по code
    if not item and code:
        item = await search_items(code)
        
    if not item:
        raise HTTPException(status_code=404, detail="Товар не найден")
        
    context = get_mobile_context(
        user_name=user_info["user_name"],
        user_role=user_info["user_role"],
        active_tab="catalog",
        user_id=user_info["user_id"]
    )
    context.update({
        "request": request,
        "item": item
    })
    return templates.TemplateResponse("mobile/take_part.html", context)


# ==========================================
# CATCH-ALL ROUTE FOR REACT SPA FALLBACK
# ==========================================
@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    # 1. API routes must return 404
    if path_name.startswith("api/") or path_name.startswith("docs") or path_name.startswith("openapi.json"):
        raise HTTPException(status_code=404, detail="API route not found")
        
    # Если пользователь авторизован и пытается зайти на десктопный маршрут, проверяем его роль
    auth_service = get_auth_service()
    cookie_user_id = request.cookies.get("wms_user_id")
    user_id = auth_service.current_user_id or cookie_user_id
    
    if user_id and not path_name.startswith("mobile/"):
        try:
            user_state = await auth_service.get_user_state(user_id)
            if user_state and user_state.is_logged_in:
                # Если роль не административная - принудительно перенаправляем на мобильную версию
                if user_state.role not in [UserRole.ADMIN, UserRole.INVENTORY_MANAGER, UserRole.SUPERVISOR]:
                    return RedirectResponse(url="/mobile/dashboard", status_code=303)
        except Exception as e:
            logger.error(f"Error checking user role in catch_all: {e}")
    
    # 2. Check if the file exists directly in frontend/dist folder (e.g. favicon.svg, icons.svg)
    file_path = os.path.join(FRONTEND_DIST_DIR, path_name)
    if path_name and os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
        
    # 3. Otherwise serve index.html for SPA client-side routing
    frontend_index = os.path.join(FRONTEND_DIST_DIR, "index.html")
    if os.path.exists(frontend_index):
        return FileResponse(frontend_index)
    
    return JSONResponse({"error": "Frontend build not found. Please compile frontend folder."}, status_code=404)


# ==========================================
# ЗАПУСК
# ==========================================
if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("🚀 ЗАПУСК WAREHOUSE MANAGEMENT SYSTEM")
    print("=" * 60)
    print(f"📍 Локальный сервер: http://localhost:8000")
    print(f"📋 API документация: http://localhost:8000/docs")
    print(f"📱 Мобильная версия: http://localhost:8000/mobile/dashboard")
    print(f"📁 Каталог: http://localhost:8000/desktop/parts_list")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)