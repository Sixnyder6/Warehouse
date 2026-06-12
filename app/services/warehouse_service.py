# =========================================================================================
# ⚠️ ВНИМАНИЕ / WARNING: ОГРАНИЧЕНИЕ ТРАФИКА FIRESTORE!
# Ежедневный лимит на операции чтения Firestore ограничен 50,000 запросов!
# Любые новые запросы, циклы опроса или синхронизации ДОЛЖНЫ БЫТЬ МАКСИМАЛЬНО ОПТИМИЗИРОВАНЫ.
# Обязательно используйте серверное кэширование и IndexedDB-синхронизацию на клиенте.
# Избегайте бесконечных циклов опроса (polling) и некэшированных повторных чтений!
# Превышение лимита заморозит работу склада и парализует бизнес.
# =========================================================================================

import os

# Убираем SOCKS/HTTP прокси из окружения — VPN-клиенты (Clash, V2Ray) прописывают
# HTTP_PROXY=socks4://... что ломает httpx и google-auth.
for _pv in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_pv, None)

import json
import time
import asyncio
import httpx
import logging

_http_client = None

def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        # trust_env=False — полностью игнорирует системный прокси (env + реестр Windows)
        _http_client = httpx.AsyncClient(trust_env=False)
    return _http_client
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Dict, Any

from app.models import (
    WarehouseItem, WarehouseItemCreate, WarehouseItemUpdate,
    WarehouseLog, GroupedActivity,
    WarehouseOrder, WarehouseOrderCreate, OrderStatus, OrderItem,
    NewsItem, NewsItemCreate, NewsTag, Employee,
    SyncPushOperation
)
from app.services.telemetry_service import log_operation, is_read_budget_exceeded

# ==========================================
# ЛОГГИРОВАНИЕ
# ==========================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# FIREBASE КОНФИГУРАЦИЯ (OAuth2 Bearer Token)
# ==========================================

from google.oauth2 import service_account
from google.auth.transport.requests import Request as AuthRequest

FIREBASE_CRED_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "firebase", "firebase_credentials.json"
)

# Load Firebase credentials: check environment variable first (for cloud container deploys),
# otherwise fall back to local credentials file.
firebase_cred_env = os.environ.get("FIREBASE_CREDENTIALS_JSON")
if firebase_cred_env:
    try:
        cred_data = json.loads(firebase_cred_env)
        logger.info("🔐 Loaded Firebase credentials from environment variable")
    except Exception as e:
        logger.error(f"❌ Failed to parse FIREBASE_CREDENTIALS_JSON from env: {e}")
        raise e
else:
    with open(FIREBASE_CRED_PATH, 'r') as f:
        cred_data = json.load(f)

FIREBASE_PROJECT_ID = cred_data['project_id']
FIREBASE_BASE_URL = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents"

# Сервисный аккаунт для OAuth2 токена
_creds = service_account.Credentials.from_service_account_info(
    cred_data,
    scopes=['https://www.googleapis.com/auth/datastore']
)

# Кэш для токена (токен живет ~1 час)
_token_cache: dict = {"token": None, "expires_at": None}

def _get_bearer_token_sync() -> Optional[str]:
    """Синхронное обновление OAuth2 токена — вызывать только из asyncio.to_thread!"""
    now = datetime.now()
    if _token_cache["token"] and _token_cache["expires_at"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    for attempt in range(3):
        try:
            import requests as _requests
            # Сессия без прокси — VPN-клиент мог прописать SOCKS в env/реестр
            _session = _requests.Session()
            _session.proxies = {}
            _creds.refresh(AuthRequest(session=_session))
            token = _creds.token
            _token_cache["token"] = token
            _token_cache["expires_at"] = now + timedelta(seconds=3000)
            logger.info("✅ OAuth2 token refreshed")
            return token
        except Exception as e:
            logger.warning(f"⚠️ Attempt {attempt + 1} to get OAuth2 token failed: {e}")
            if attempt < 2:
                time.sleep(1)
            else:
                logger.error(f"❌ Failed to get OAuth2 token after 3 attempts: {e}")
    return None

async def _get_headers_async() -> dict:
    """Асинхронное получение заголовков — НЕ блокирует event loop."""
    # Если токен ещё живой — возвращаем сразу без thread
    now = datetime.now()
    if _token_cache["token"] and _token_cache["expires_at"] and now < _token_cache["expires_at"]:
        return {
            'Authorization': f'Bearer {_token_cache["token"]}',
            'Content-Type': 'application/json',
        }
    # Токен нужно обновить — делаем в отдельном потоке чтобы не блокировать event loop
    token = await asyncio.to_thread(_get_bearer_token_sync)
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }

# ==========================================
# КЭШ (in-memory с TTL)
# ==========================================

class TimedCache:
    """Простой кэш с временем жизни"""
    def __init__(self, default_ttl_seconds: int = 30):
        self._cache: Dict[str, tuple[Any, datetime]] = {}
        self._default_ttl = default_ttl_seconds
    
    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            value, expires_at = self._cache[key]
            if datetime.now() < expires_at:
                try:
                    from app.services.telemetry_service import log_cache
                    log_cache("HIT", 1)
                except Exception:
                    pass
                return value
            else:
                del self._cache[key]
        try:
            from app.services.telemetry_service import log_cache
            log_cache("MISS", 1)
        except Exception:
            pass
        return None
    
    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None):
        ttl = ttl_seconds or self._default_ttl
        expires_at = datetime.now() + timedelta(seconds=ttl)
        self._cache[key] = (value, expires_at)
    
    def clear(self, key: Optional[str] = None):
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

_cache = TimedCache(default_ttl_seconds=60)

# ==========================================
# УТИЛИТЫ ФОРМАТИРОВАНИЯ
# ==========================================

def firestore_to_python(fields: dict) -> dict:
    """Конвертирует Firestore fields в Python dict"""
    result = {}
    for key, value in fields.items():
        if 'stringValue' in value:
            result[key] = value['stringValue']
        elif 'integerValue' in value:
            result[key] = int(value['integerValue'])
        elif 'booleanValue' in value:
            result[key] = value['booleanValue']
        elif 'doubleValue' in value:
            result[key] = float(value['doubleValue'])
        elif 'timestampValue' in value:
            ts = value['timestampValue']
            if 'T' in ts:
                ts = ts.replace('Z', '+00:00')
                result[key] = datetime.fromisoformat(ts)
            else:
                result[key] = datetime.now()
        elif 'arrayValue' in value:
            arr = []
            for v in value['arrayValue'].get('values', []):
                if 'stringValue' in v:
                    arr.append(v['stringValue'])
                elif 'mapValue' in v:
                    arr.append(firestore_to_python(v['mapValue'].get('fields', {})))
            result[key] = arr
        elif 'mapValue' in value:
            result[key] = firestore_to_python(value['mapValue'].get('fields', {}))
        elif 'nullValue' in value:
            result[key] = None
        else:
            result[key] = None
    return result


def python_to_firestore(obj) -> dict:
    """Конвертирует Python dict в Firestore fields"""
    fields = {}
    for key, value in obj.items():
        if value is None:
            fields[key] = {"nullValue": None}
        elif isinstance(value, str):
            fields[key] = {"stringValue": value}
        elif isinstance(value, bool):
            fields[key] = {"booleanValue": value}
        elif isinstance(value, int):
            fields[key] = {"integerValue": str(value)}
        elif isinstance(value, float):
            fields[key] = {"doubleValue": value}
        elif isinstance(value, datetime):
            # Переводим в UTC формат для Firestore (важно для дельта-синхронизации)
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            fields[key] = {"timestampValue": value.isoformat().replace("+00:00", "Z")}
        elif isinstance(value, list):
            vals = []
            for v in value:
                if isinstance(v, str):
                    vals.append({"stringValue": v})
                elif isinstance(v, dict):
                    vals.append({"mapValue": {"fields": python_to_firestore(v)}})
            fields[key] = {"arrayValue": {"values": vals}}
        elif isinstance(value, dict):
            fields[key] = {"mapValue": {"fields": python_to_firestore(value)}}
        elif isinstance(value, OrderStatus):
            fields[key] = {"stringValue": value.value}
        else:
            fields[key] = {"stringValue": str(value)}
    return fields


def generate_keywords(*strings: Optional[str]) -> List[str]:
    """Генерация ключевых слов для поиска"""
    keywords = set()
    for s in strings:
        if not s:
            continue
        clean = s.lower().strip()
        for word in clean.replace("-", " ").replace(".", " ").replace("_", " ").replace("/", " ").split():
            if word:
                keywords.add(word)
        temp = ""
        for ch in clean:
            temp += ch
            keywords.add(temp)
    return sorted(keywords)


# =========================================================================================
# ⚠️ ВНИМАНИЕ / WARNING: ОГРАНИЧЕНИЕ ТРАФИКА FIRESTORE!
# Следующие функции напрямую обращаются к удаленной базе данных Firestore.
# Любой вызов без серверного кэширования тратит драгоценный лимит (50,000 операций/день).
# Никогда не вызывайте эти функции в бесконечных циклах без адекватного кэша и дебаунса!
# =========================================================================================

# ==========================================
# ОПЕРАЦИИ С FIRESTORE
# ==========================================

async def firestore_query_with_filter(
    collection: str, 
    field: str, 
    operator: str, 
    value: Any,
    limit: int = 50
) -> List[dict]:
    """
    Выполняет запрос к Firestore с фильтрацией на сервере.
    """
    if is_read_budget_exceeded():
        logger.warning(f"🚨 Query Guard: Firestore read budget exceeded! Query blocked for {collection}.")
        return []
        
    url = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents:runQuery"
    
    if isinstance(value, str):
        value_type = {"stringValue": value}
    elif isinstance(value, int):
        value_type = {"integerValue": str(value)}
    elif isinstance(value, bool):
        value_type = {"booleanValue": value}
    elif isinstance(value, float):
        value_type = {"doubleValue": value}
    elif isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value_type = {"timestampValue": value.isoformat().replace("+00:00", "Z")}
    else:
        value_type = {"stringValue": str(value)}
    
    query = {
        "structuredQuery": {
            "from": [{"collectionId": collection}],
            "where": {
                "fieldFilter": {
                    "field": {"fieldPath": field},
                    "op": operator,
                    "value": value_type
                }
            },
            "limit": limit
        }
    }
    
    logger.info(f"📊 FIRESTORE QUERY: {collection} WHERE {field} {operator} {value} (limit={limit})")
    
    try:
        t0 = time.time()
        client = get_http_client()
        headers = await _get_headers_async()
        response = await client.post(url, json=query, headers=headers, timeout=15.0)
        latency_ms = int((time.time() - t0) * 1000)
        if response.status_code == 200:
            results = response.json()
            documents = []
            for result in results:
                if 'document' in result:
                    doc = result['document']
                    doc_id = doc['name'].split('/')[-1]
                    fields = doc.get('fields', {})
                    doc_data = firestore_to_python(fields)
                    doc_data['id'] = doc_id
                    documents.append(doc_data)
            log_operation("READ", collection, max(1, len(documents)), latency_ms)
            return documents
        else:
            logger.error(f"❌ Query failed: {response.status_code}")
            log_operation("READ", collection, 1, latency_ms)
            return []
    except Exception as e:
        logger.error(f"❌ Query exception: {e}")
        log_operation("READ", collection, 1)
        return []


async def firestore_query_ordered(
    collection: str,
    order_by_field: str,
    direction: str = "DESCENDING",
    limit: int = 50
) -> List[dict]:
    """
    Выполняет запрос к Firestore с сортировкой.
    """
    if is_read_budget_exceeded():
        logger.warning(f"🚨 Query Guard: Firestore read budget exceeded! Ordered query blocked for {collection}.")
        return []
        
    url = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents:runQuery"
    
    query = {
        "structuredQuery": {
            "from": [{"collectionId": collection}],
            "orderBy": [
                {
                    "field": {"fieldPath": order_by_field},
                    "direction": direction
                }
            ],
            "limit": limit
        }
    }
    
    logger.info(f"📊 FIRESTORE QUERY ORDERED: {collection} ORDER BY {order_by_field} {direction} (limit={limit})")
    
    try:
        t0 = time.time()
        client = get_http_client()
        headers = await _get_headers_async()
        response = await client.post(url, json=query, headers=headers, timeout=15.0)
        latency_ms = int((time.time() - t0) * 1000)
        if response.status_code == 200:
            results = response.json()
            documents = []
            for result in results:
                if 'document' in result:
                    doc = result['document']
                    doc_id = doc['name'].split('/')[-1]
                    fields = doc.get('fields', {})
                    doc_data = firestore_to_python(fields)
                    doc_data['id'] = doc_id
                    documents.append(doc_data)
            log_operation("READ", collection, max(1, len(documents)), latency_ms)
            return documents
        else:
            logger.error(f"❌ Ordered query failed: {response.status_code}")
            log_operation("READ", collection, 1, latency_ms)
            return []
    except Exception as e:
        logger.error(f"❌ Ordered query exception: {e}")
        log_operation("READ", collection, 1)
        return []



async def firestore_get_all_paginated(
    collection: str, 
    page_size: int = 50, 
    page_token: str = None
) -> Tuple[List[dict], Optional[str]]:
    if is_read_budget_exceeded():
        logger.warning(f"🚨 Query Guard: Firestore read budget exceeded! Paginated query blocked for {collection}.")
        return [], None
        
    url = f"{FIREBASE_BASE_URL}/{collection}"
    params = {
        "pageSize": page_size,
    }
    if page_token:
        params["pageToken"] = page_token
    
    try:
        t0 = time.time()
        client = get_http_client()
        headers = await _get_headers_async()
        response = await client.get(url, params=params, headers=headers, timeout=15.0)
        latency_ms = int((time.time() - t0) * 1000)
        if response.status_code == 200:
            data = response.json()
            documents = []
            for doc in data.get('documents', []):
                doc_id = doc['name'].split('/')[-1]
                fields = doc.get('fields', {})
                doc_data = firestore_to_python(fields)
                doc_data['id'] = doc_id
                documents.append(doc_data)
            next_token = data.get('nextPageToken')
            log_operation("READ", collection, max(1, len(documents)), latency_ms)
            return documents, next_token
        else:
            logger.error(f"❌ Failed to read {collection}: {response.status_code}")
            log_operation("READ", collection, 1, latency_ms)
            return [], None
    except Exception as e:
        logger.error(f"❌ Exception reading {collection}: {e}")
        log_operation("READ", collection, 1)
        return [], None


async def firestore_get_document(collection: str, doc_id: str) -> Optional[dict]:
    if is_read_budget_exceeded():
        logger.warning(f"🚨 Query Guard: Firestore read budget exceeded! Get document blocked for {collection}/{doc_id}.")
        return None
        
    url = f"{FIREBASE_BASE_URL}/{collection}/{doc_id}"
    
    try:
        t0 = time.time()
        client = get_http_client()
        headers = await _get_headers_async()
        response = await client.get(url, headers=headers, timeout=15.0)
        latency_ms = int((time.time() - t0) * 1000)
        log_operation("READ", collection, 1, latency_ms)
        if response.status_code == 200:
            data = response.json()
            fields = data.get('fields', {})
            result = firestore_to_python(fields)
            result['id'] = doc_id
            return result
        return None
    except Exception as e:
        return None


async def firestore_create_document(collection: str, data: dict) -> str:
    url = f"{FIREBASE_BASE_URL}/{collection}"
    firestore_data = {"fields": python_to_firestore(data)}
    
    try:
        t0 = time.time()
        client = get_http_client()
        headers = await _get_headers_async()
        response = await client.post(url, json=firestore_data, headers=headers, timeout=15.0)
        latency_ms = int((time.time() - t0) * 1000)
        log_operation("WRITE", collection, 1, latency_ms)
        if response.status_code == 200:
            return response.json().get('name', '').split('/')[-1]
        raise Exception(f"Firestore error: {response.status_code}")
    except Exception as e:
        raise e


async def firestore_update_document(collection: str, doc_id: str, updates: dict) -> bool:
    mask_params = "&".join(f"updateMask.fieldPaths={key}" for key in updates.keys())
    url = f"{FIREBASE_BASE_URL}/{collection}/{doc_id}?{mask_params}"
    firestore_data = {"fields": python_to_firestore(updates)}
    
    try:
        logger.info(f"🔥 FIRESTORE UPDATE: {collection}/{doc_id} — {list(updates.keys())}")
        t0 = time.time()
        client = get_http_client()
        headers = await _get_headers_async()
        response = await client.patch(url, json=firestore_data, headers=headers, timeout=15.0)
        latency_ms = int((time.time() - t0) * 1000)
        log_operation("WRITE", collection, 1, latency_ms)
        if response.status_code != 200:
            logger.error(f"❌ Firestore UPDATE failed [{response.status_code}]: {response.text[:300]}")
            return False
        logger.info(f"✅ Firestore UPDATE OK: {collection}/{doc_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Firestore UPDATE exception: {e}")
        return False


async def firestore_delete_document(collection: str, doc_id: str) -> bool:
    url = f"{FIREBASE_BASE_URL}/{collection}/{doc_id}"
    try:
        t0 = time.time()
        client = get_http_client()
        headers = await _get_headers_async()
        response = await client.delete(url, headers=headers, timeout=15.0)
        latency_ms = int((time.time() - t0) * 1000)
        log_operation("DELETE", collection, 1, latency_ms)
        return response.status_code == 200
    except Exception as e:
        return False


# ==========================================
# СКЛАД — ТОВАРЫ (С ПОДДЕРЖКОЙ OFFLINE-FIRST)
# ==========================================

async def get_items(limit: int = 1000, use_cache: bool = True, include_deleted: bool = False) -> List[dict]:
    """Получить товары. Теперь отфильтровывает удаленные по умолчанию."""
    cache_key = f"warehouse_items_limit_{limit}_{include_deleted}"
    
    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached
    
    items, _ = await firestore_get_all_paginated("warehouse_items", page_size=limit)
    
    if not include_deleted:
        items = [i for i in items if not i.get("isDeleted", False)]
    
    if use_cache:
        _cache.set(cache_key, items, ttl_seconds=600)
    
    return items


async def get_item(item_id: str, use_cache: bool = True) -> Optional[dict]:
    cache_key = f"warehouse_item_{item_id}"
    
    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached
    
    item = await firestore_get_document("warehouse_items", item_id)
    if use_cache and item:
        _cache.set(cache_key, item, ttl_seconds=60)
    
    return item


async def search_items(code: str) -> Optional[dict]:
    results = await firestore_query_with_filter(
        collection="warehouse_items",
        field="sku",
        operator="EQUAL",
        value=code,
        limit=5
    )
    if results:
        return results[0]
    
    try:
        item_by_id = await get_item(code)
        if item_by_id:
            return item_by_id
    except:
        pass
    
    return None


async def create_item(item_data: WarehouseItemCreate) -> Tuple[bool, str]:
    try:
        keywords = generate_keywords(item_data.fullName, item_data.shortName, item_data.sku)
        data = {
            "fullName": item_data.fullName,
            "shortName": item_data.shortName,
            "sku": item_data.sku,
            "description": item_data.description,
            "category": item_data.category,
            "unit": item_data.unit,
            "stockCount": item_data.stockCount,
            "totalStock": item_data.totalStock,
            "lowStockThreshold": item_data.lowStockThreshold,
            "imageUrl": item_data.imageUrl,
            "keywords": keywords,
            "updatedAt": datetime.now(timezone.utc), # ДЛЯ СИНХРОНИЗАЦИИ
            "isDeleted": False
        }
        doc_id = await firestore_create_document("warehouse_items", data)
        _cache.clear()
        return True, doc_id
    except Exception as e:
        return False, str(e)


async def update_item(item_id: str, item_data: WarehouseItemUpdate) -> Tuple[bool, str]:
    try:
        existing = await get_item(item_id, use_cache=False)
        if not existing:
            return False, "Товар не найден"

        updates = {}
        for field, value in item_data.model_dump(exclude_unset=True).items():
            if value is not None:
                updates[field] = value

        if any(f in updates for f in ["fullName", "shortName", "sku"]):
            full = updates.get("fullName", existing.get("fullName", ""))
            short = updates.get("shortName", existing.get("shortName", ""))
            sku = updates.get("sku", existing.get("sku"))
            updates["keywords"] = generate_keywords(full, short, sku)

        # ДЛЯ СИНХРОНИЗАЦИИ
        updates["updatedAt"] = datetime.now(timezone.utc)

        success = await firestore_update_document("warehouse_items", item_id, updates)
        
        if success:
            _cache.clear()
        
        return success, ""
    except Exception as e:
        return False, str(e)


async def delete_item(item_id: str) -> Tuple[bool, str]:
    """SOFT DELETE: Не стираем, а помечаем удаленным для браузеров"""
    try:
        updates = {
            "isDeleted": True,
            "updatedAt": datetime.now(timezone.utc)
        }
        success = await firestore_update_document("warehouse_items", item_id, updates)
        
        if success:
            _cache.clear()
        
        return success, "" if success else "Ошибка удаления"
    except Exception as e:
        return False, str(e)


# ==========================================
# СКЛАД — ВЗЯТЬ/ДОБАВИТЬ ТОВАР (ТРАНЗАКЦИИ)
# ==========================================

async def take_item(item_id: str, quantity: int, user_name: str, user_id: str = "", timestamp: datetime = None) -> Tuple[bool, str]:
    try:
        item = await get_item(item_id, use_cache=False)
        if not item:
            return False, "Товар не найден"

        current_stock = item.get("stockCount", 0)
        item_name = item.get("shortName", "Неизвестно")

        if current_stock < quantity:
            return False, f"Недостаточно товара! Остаток: {current_stock}"

        new_stock = current_stock - quantity

        update_success = await firestore_update_document(
            "warehouse_items", item_id,
            {"stockCount": new_stock, "updatedAt": datetime.now(timezone.utc)}
        )

        if not update_success:
            return False, "Ошибка обновления остатка"

        log_data = {
            "itemId": item_id,
            "itemName": item_name,
            "userId": user_id,
            "userName": user_name,
            "quantityChange": -quantity,
            "timestamp": timestamp or datetime.now(timezone.utc),
        }
        await firestore_create_document("warehouse_logs", log_data)
        
        _cache.clear()
        return True, f"{item_name}: -{quantity} {item.get('unit', 'шт')}"
    except Exception as e:
        return False, str(e)


async def take_items_batch(items: List[dict], user_name: str, user_id: str, timestamp: datetime = None) -> Tuple[bool, str]:
    try:
        # 1. Валидация остатков для всех товаров в батче
        items_to_process = []
        for item_req in items:
            item_id = item_req.get("itemId")
            quantity = item_req.get("quantity", 1)
            if quantity <= 0:
                return False, f"Неверное количество для списания: {quantity}"

            item = await get_item(item_id, use_cache=False)
            if not item:
                return False, f"Товар не найден (ID: {item_id})"

            current_stock = item.get("stockCount", 0)
            item_name = item.get("shortName", "Неизвестно")

            if current_stock < quantity:
                return False, f"Недостаточно товара '{item_name}'! Остаток: {current_stock}, требуется: {quantity}"

            items_to_process.append((item, quantity))

        # 2. Выполнение списаний и запись в лог
        now_time = timestamp or datetime.now(timezone.utc)
        success_messages = []
        for item, quantity in items_to_process:
            item_id = item.get("id")
            item_name = item.get("shortName", "Неизвестно")
            new_stock = item.get("stockCount", 0) - quantity

            update_success = await firestore_update_document(
                "warehouse_items", item_id,
                {"stockCount": new_stock, "updatedAt": now_time}
            )

            if not update_success:
                return False, f"Ошибка обновления остатка для '{item_name}'"

            log_data = {
                "itemId": item_id,
                "itemName": item_name,
                "userId": user_id,
                "userName": user_name,
                "quantityChange": -quantity,
                "timestamp": now_time,
            }
            await firestore_create_document("warehouse_logs", log_data)
            success_messages.append(f"{item_name}: -{quantity} {item.get('unit', 'шт')}")

        _cache.clear()
        return True, ", ".join(success_messages)
    except Exception as e:
        return False, str(e)


async def add_stock(item_id: str, quantity: int, user_name: str, user_id: str = "", timestamp: datetime = None) -> Tuple[bool, str]:
    try:
        item = await get_item(item_id, use_cache=False)
        if not item:
            return False, "Товар не найден"

        current_stock = item.get("stockCount", 0)
        item_name = item.get("shortName", "Неизвестно")
        new_stock = current_stock + quantity

        update_success = await firestore_update_document(
            "warehouse_items", item_id,
            {"stockCount": new_stock, "updatedAt": datetime.now(timezone.utc)}
        )

        if not update_success:
            return False, "Ошибка обновления остатка"

        log_data = {
            "itemId": item_id,
            "itemName": item_name,
            "userId": user_id,
            "userName": user_name,
            "quantityChange": quantity,
            "timestamp": timestamp or datetime.now(timezone.utc),
        }
        await firestore_create_document("warehouse_logs", log_data)
        
        _cache.clear()
        return True, f"{item_name}: +{quantity} {item.get('unit', 'шт')}"
    except Exception as e:
        return False, str(e)


# ==========================================
# OFFLINE FIRST: ЛОГИКА СИНХРОНИЗАЦИИ
# ==========================================

async def pull_items_changes(last_pulled_at: Optional[datetime] = None) -> List[dict]:
    """Отдает только те товары, которые изменились после last_pulled_at"""
    if not last_pulled_at:
        # При первом пуле используем кэш и лимит 500 вместо 2000
        items = await get_items(limit=500, use_cache=True, include_deleted=True)
        return items
    
    changed_items = await firestore_query_with_filter(
        collection="warehouse_items",
        field="updatedAt",
        operator="GREATER_THAN",
        value=last_pulled_at,
        limit=500
    )
    return changed_items


async def process_offline_operations(operations: List[Any]) -> Dict[str, Any]:
    """Принимает пакет операций из офлайн-очереди браузера"""
    results = {"success_count": 0, "failed_count": 0, "errors": []}
    
    for op in operations:
        try:
            # Поддержка как Pydantic моделей, так и словарей (dict)
            op_type = op.type if hasattr(op, 'type') else op.get('type')
            op_itemId = op.itemId if hasattr(op, 'itemId') else op.get('itemId')
            op_quantity = op.quantity if hasattr(op, 'quantity') else op.get('quantity')
            op_userName = op.userName if hasattr(op, 'userName') else op.get('userName')
            op_userId = op.userId if hasattr(op, 'userId') else op.get('userId')
            op_timestamp = op.timestamp if hasattr(op, 'timestamp') else op.get('timestamp')
            op_id = op.id if hasattr(op, 'id') else op.get('id')
            
            # Парсинг временной метки, если это строка
            if isinstance(op_timestamp, str):
                try:
                    if op_timestamp.endswith('Z'):
                        op_timestamp = op_timestamp[:-1] + '+00:00'
                    op_timestamp = datetime.fromisoformat(op_timestamp)
                except ValueError:
                    op_timestamp = None
            
            if op_type == "TAKE":
                success, msg = await take_item(
                    item_id=op_itemId, 
                    quantity=op_quantity, 
                    user_name=op_userName, 
                    user_id=op_userId,
                    timestamp=op_timestamp
                )
            elif op_type == "ADD":
                success, msg = await add_stock(
                    item_id=op_itemId, 
                    quantity=op_quantity, 
                    user_name=op_userName, 
                    user_id=op_userId,
                    timestamp=op_timestamp
                )
            else:
                success, msg = False, f"Неизвестный тип операции: {op_type}"
            
            if success:
                results["success_count"] += 1
            else:
                results["failed_count"] += 1
                results["errors"].append({"id": op_id, "error": msg})
                
        except Exception as e:
            op_id = op.id if hasattr(op, 'id') else op.get('id', 'unknown')
            results["failed_count"] += 1
            results["errors"].append({"id": op_id, "error": str(e)})
            
    return results


# ==========================================
# ВЫДАЧА ТОВАРА С ВЫБОРОМ ПОЛУЧАТЕЛЯ
# ==========================================

async def take_item_to_recipient(
    item_id: str, 
    quantity: int, 
    recipient_name: str,
    recipient_id: str,
    issuer_name: str,
    issuer_id: str = "",
    notes: str = "",
    timestamp: datetime = None
) -> Tuple[bool, str]:
    """
    Расширенная выдача: кладовщик выдаёт товар сотруднику.
    В логе сохраняется: кто выдал (issuer) + кому выдал (recipient).
    """
    try:
        item = await get_item(item_id, use_cache=False)
        if not item:
            return False, "Товар не найден"

        current_stock = item.get("stockCount", 0)
        item_name = item.get("shortName", "Неизвестно")

        if current_stock < quantity:
            return False, f"Недостаточно товара! Остаток: {current_stock}"

        new_stock = current_stock - quantity

        update_success = await firestore_update_document(
            "warehouse_items", item_id,
            {"stockCount": new_stock, "updatedAt": datetime.now(timezone.utc)}
        )

        if not update_success:
            return False, "Ошибка обновления остатка"

        # Расширенный лог с issuer и recipient
        ts = timestamp or datetime.now(timezone.utc)
        log_data = {
            "itemId": item_id,
            "itemName": item_name,
            "quantityChange": -quantity,
            # Кто выдал (кладовщик)
            "issuerId": issuer_id,
            "issuerName": issuer_name,
            # Кто получил (сотрудник)
            "recipientId": recipient_id,
            "recipientName": recipient_name,
            # Для обратной совместимости со старым UI
            "userId": recipient_id,
            "userName": f"{recipient_name} (выдал {issuer_name})",
            "notes": notes,
            "timestamp": ts,
        }
        await firestore_create_document("warehouse_logs", log_data)
        
        _cache.clear()
        return True, f"{issuer_name} выдал {recipient_name}: {item_name} -{quantity} {item.get('unit', 'шт')}"
    except Exception as e:
        return False, str(e)


async def return_item_to_stock(
    item_id: str,
    quantity: int,
    recipient_name: str,
    recipient_id: str,
    issuer_name: str,
    issuer_id: str = "",
    notes: str = "",
    timestamp: datetime = None
) -> Tuple[bool, str]:
    """
    Возврат товара на склад (от сотрудника).
    quantityChange: +quantity (положительное — добавление на склад)
    """
    try:
        item = await get_item(item_id, use_cache=False)
        if not item:
            return False, "Товар не найден"

        current_stock = item.get("stockCount", 0)
        item_name = item.get("shortName", "Неизвестно")
        new_stock = current_stock + quantity

        update_success = await firestore_update_document(
            "warehouse_items", item_id,
            {"stockCount": new_stock, "updatedAt": datetime.now(timezone.utc)}
        )

        if not update_success:
            return False, "Ошибка обновления остатка"

        ts = timestamp or datetime.now(timezone.utc)
        log_data = {
            "itemId": item_id,
            "itemName": item_name,
            "quantityChange": quantity,  # положительное = возврат
            "issuerId": issuer_id,
            "issuerName": issuer_name,
            "recipientId": recipient_id,
            "recipientName": recipient_name,
            "userId": recipient_id,
            "userName": f"{recipient_name} (принял {issuer_name})",
            "notes": f"ВОЗВРАТ: {notes}" if notes else "ВОЗВРАТ",
            "timestamp": ts,
        }
        await firestore_create_document("warehouse_logs", log_data)
        
        _cache.clear()
        return True, f"{recipient_name} вернул: {item_name} +{quantity} {item.get('unit', 'шт')}"
    except Exception as e:
        return False, str(e)


# ==========================================
# СКЛАД — ЛОГИ
# ==========================================

async def get_logs(limit: int = 50) -> List[dict]:
    cache_key = f"warehouse_logs_{limit}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    
    # Запрашиваем логи, упорядоченные по времени в порядке убывания (DESCENDING)
    logs = await firestore_query_ordered("warehouse_logs", "timestamp", "DESCENDING", limit=limit)
    
    # Кэшируем логи на 10 минут
    _cache.set(cache_key, logs, ttl_seconds=600)
    return logs


async def get_logs_for_employee(user_id: str, limit: int = 100) -> List[dict]:
    logs = await firestore_query_with_filter(
        collection="warehouse_logs",
        field="userId",
        operator="EQUAL",
        value=user_id,
        limit=limit
    )
    logs.sort(key=lambda x: x.get('timestamp', datetime.min) if x.get('timestamp') else datetime.min, reverse=True)
    return logs


async def get_grouped_logs(limit: int = 200) -> List[GroupedActivity]:
    logs = await get_logs(limit=limit)
    if not logs:
        return []

    def parse_ts(log_entry):
        ts = log_entry.get('timestamp')
        if ts is None:
            return 0
        if isinstance(ts, datetime):
            return ts.timestamp()
        return 0

    grouped = []
    current_group = [logs[0]]

    for i in range(1, len(logs)):
        current = logs[i]
        last_in_group = current_group[-1]
        time_diff = parse_ts(last_in_group) - parse_ts(current)

        if current.get("userName") != last_in_group.get("userName") or time_diff > 90:
            grouped.append(_create_grouped_activity(current_group))
            current_group = [current]
        else:
            current_group.append(current)

    if current_group:
        grouped.append(_create_grouped_activity(current_group))

    return grouped


def _create_grouped_activity(logs_in_group: List[dict]) -> GroupedActivity:
    ref = logs_in_group[0]
    items = [
        {"itemName": log.get("itemName", ""), "quantity": log.get("quantityChange", 0)}
        for log in logs_in_group
    ]
    return GroupedActivity(
        userName=ref.get("userName", "Неизвестный"),
        items=items,
        timestamp=ref.get("timestamp")
    )


# ==========================================
# СИСТЕМА ЗАКАЗОВ
# ==========================================

async def get_orders(
    status_filter: Optional[str] = None, 
    user_id: Optional[str] = None,
    limit: int = 100
) -> List[dict]:
    cache_key = f"orders_{status_filter}_{user_id}_{limit}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    
    orders, _ = await firestore_get_all_paginated("warehouse_orders", page_size=limit)
    result = orders
    
    if status_filter:
        statuses = [s.strip() for s in status_filter.split(",")]
        result = [o for o in result if o.get("status") in statuses]
    
    if user_id:
        result = [o for o in result if o.get("userId") == user_id]
    
    result.sort(key=lambda x: x.get('createdAt', datetime.min) if x.get('createdAt') else datetime.min, reverse=True)
    _cache.set(cache_key, result, ttl_seconds=600)
    
    return result


async def create_order(order_data: WarehouseOrderCreate) -> Tuple[bool, str, Optional[str]]:
    try:
        now = datetime.now()
        data = {
            "userId": order_data.userId,
            "userName": order_data.userName,
            "userRole": order_data.userRole,
            "items": [oi.model_dump() for oi in order_data.items],
            "status": order_data.status.value,
            "createdAt": now,
            "completedAt": None,
        }
        doc_id = await firestore_create_document("warehouse_orders", data)
        _cache.clear()
        return True, doc_id, None
    except Exception as e:
        return False, "", str(e)


async def update_order_status(order_id: str, new_status: OrderStatus) -> Tuple[bool, str]:
    try:
        order = await firestore_get_document("warehouse_orders", order_id)
        if not order:
            return False, "Заказ не найден"

        success = await firestore_update_document("warehouse_orders", order_id, {"status": new_status.value})
        if success:
            _cache.clear()
        return success, "" if success else "Ошибка обновления"
    except Exception as e:
        return False, str(e)


async def complete_order(order_id: str, warehouse_man_name: str) -> Tuple[bool, str]:
    try:
        order = await firestore_get_document("warehouse_orders", order_id)
        if not order:
            return False, "Заказ не найден"

        if order.get("status") == "COMPLETED":
            return False, "Заказ уже выдан"

        items = order.get("items", [])
        if isinstance(items, dict):
            items = [items]

        errors = []
        for order_item in items:
            item_id = order_item.get("itemId", "")
            quantity = order_item.get("quantity", 0)
            item_name = order_item.get("itemName", "")

            if not item_id:
                continue

            item = await get_item(item_id, use_cache=False)
            if not item:
                errors.append(f"Товар {item_name} не найден в базе")
                continue

            current_stock = item.get("stockCount", 0)
            new_stock = current_stock - quantity

            await firestore_update_document("warehouse_items", item_id, {"stockCount": new_stock})

            log_data = {
                "itemId": item_id,
                "itemName": item_name,
                "userId": order.get("userId", ""),
                "userName": f"{order.get('userName', '')} (выдал {warehouse_man_name})",
                "quantityChange": -quantity,
                "timestamp": datetime.now(),
            }
            await firestore_create_document("warehouse_logs", log_data)

        await firestore_update_document("warehouse_orders", order_id, {
            "status": "COMPLETED",
            "completedAt": datetime.now(),
        })
        _cache.clear()

        msg = "Заказ завершен. Товары списаны."
        if errors:
            msg += " Предупреждения: " + "; ".join(errors)
        return True, msg
    except Exception as e:
        return False, str(e)


# ==========================================
# НОВОСТИ
# ==========================================

async def get_news(limit: int = 50) -> List[dict]:
    cache_key = f"news_{limit}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    
    news, _ = await firestore_get_all_paginated("warehouse_news", page_size=limit)
    _cache.set(cache_key, news, ttl_seconds=300)
    return news


async def create_news(news_data: NewsItemCreate) -> Tuple[bool, str]:
    try:
        data = {
            "title": news_data.title,
            "content": news_data.content,
            "tag": news_data.tag.value,
        }
        await firestore_create_document("warehouse_news", data)
        _cache.clear()
        return True, ""
    except Exception as e:
        return False, str(e)


async def update_news(news_id: str, news_data: NewsItemCreate) -> Tuple[bool, str]:
    try:
        updates = {
            "title": news_data.title,
            "content": news_data.content,
            "tag": news_data.tag.value,
        }
        success = await firestore_update_document("warehouse_news", news_id, updates)
        if success:
            _cache.clear()
        return success, "" if success else "Ошибка обновления"
    except Exception as e:
        return False, str(e)


async def delete_news(news_id: str) -> Tuple[bool, str]:
    try:
        success = await firestore_delete_document("warehouse_news", news_id)
        if success:
            _cache.clear()
        return success, "" if success else "Ошибка удаления"
    except Exception as e:
        return False, str(e)


# ==========================================
# СОТРУДНИКИ И ПОЛЬЗОВАТЕЛИ
# ==========================================

async def get_employees(limit: int = 200) -> List[dict]:
    cache_key = f"employees_{limit}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    
    employees, _ = await firestore_get_all_paginated("warehouse_employees", page_size=limit)
    _cache.set(cache_key, employees, ttl_seconds=60)
    return employees


async def get_today_activity_stats() -> Dict[str, Dict[str, int]]:
    """
    Возвращает статистику сканирования сотрудников за сегодня, сгруппированную по ID (creatorId).
    """
    cache_key = "today_activity_stats"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        local_today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_today_ms = int(local_today.timestamp() * 1000)
        
        # Запрашиваем записи активности за сегодня
        logs = await firestore_query_with_filter(
            collection="activity_log",
            field="timestamp",
            operator="GREATER_THAN_OR_EQUAL",
            value=start_of_today_ms,
            limit=1000
        )
        
        stats = {}
        for log in logs:
            creator_id = log.get("creatorId")
            if not creator_id:
                continue
            
            item_count = log.get("itemCount", 0)
            try:
                item_count = int(item_count)
            except:
                item_count = 0
                
            if creator_id not in stats:
                stats[creator_id] = {"scansToday": 0, "batchesToday": 0}
                
            stats[creator_id]["scansToday"] += item_count
            stats[creator_id]["batchesToday"] += 1
            
        _cache.set(cache_key, stats, ttl_seconds=180) # Кэшируем на 3 минуты
        return stats
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики активности: {e}")
        return {}


async def get_internal_users(limit: int = 100) -> List[dict]:
    cache_key = f"internal_users_{limit}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    
    users, _ = await firestore_get_all_paginated("internal_users", page_size=limit)
    
    # Подтягиваем сегодняшую активность
    activity_stats = await get_today_activity_stats()
    
    # Вычисляем прошедшее время в часах для расчёта средней скорости сканирования
    local_today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_today_ms = int(local_today.timestamp() * 1000)
    now_ms = int(time.time() * 1000)
    hours_elapsed = max((now_ms - start_of_today_ms) / 3600000.0, 1.0)
    
    # Примешиваем статистику к каждому пользователю
    for user in users:
        user_id = user.get("id")
        user_stats = activity_stats.get(user_id, {"scansToday": 0, "batchesToday": 0})
        user["scansToday"] = user_stats["scansToday"]
        user["batchesToday"] = user_stats["batchesToday"]
        user["scanRatePerHour"] = int(user_stats["scansToday"] / hours_elapsed)
        
    _cache.set(cache_key, users, ttl_seconds=300) # Увеличили TTL кэша до 5 минут для экономии лимитов
    return users



def invalidate_internal_users_cache():
    """Сбрасывает кэш internal_users после изменений."""
    _cache.clear()


# async def create_internal_user(user_data: dict) -> Tuple[bool, str]:
#     try:
#         now = datetime.now(timezone.utc)
#         data = {
#             "displayName": user_data.get("displayName", ""),
#             "username": user_data.get("username", ""),
#             "password": user_data.get("password", "000000"),
#             "role": user_data.get("role", "muver"),
#             "warehouseId": user_data.get("warehouseId", "bestuzhevskaya_10"),
#             "phone": user_data.get("phone", ""),
#             "status": "offline",
#             "isAllowedToWork": True,
#             "registrationTimestamp": int(now.timestamp() * 1000),
#         }
#         doc_id = await firestore_create_document("internal_users", data)
#         _cache.clear("internal_users")
#         return True, doc_id
#     except Exception as e:
#         return False, str(e)
# 
# 
# async def update_internal_user(user_id: str, user_data: dict) -> Tuple[bool, str]:
#     try:
#         updates = {}
#         if "displayName" in user_data:
#             updates["displayName"] = user_data["displayName"]
#         if "username" in user_data:
#             updates["username"] = user_data["username"]
#         if "password" in user_data and user_data["password"]:
#             updates["password"] = user_data["password"]
#         if "role" in user_data:
#             updates["role"] = user_data["role"]
#         if "warehouseId" in user_data:
#             updates["warehouseId"] = user_data["warehouseId"]
#         if "phone" in user_data:
#             updates["phone"] = user_data["phone"]
# 
#         if not updates:
#             return True, ""
# 
#         success = await firestore_update_document("internal_users", user_id, updates)
#         if success:
#             _cache.clear("internal_users")
#         return success, "" if success else "Ошибка обновления"
#     except Exception as e:
#         return False, str(e)
# 
# 
# async def delete_internal_user(user_id: str) -> Tuple[bool, str]:
#     try:
#         success = await firestore_delete_document("internal_users", user_id)
#         if success:
#             _cache.clear("internal_users")
#         return success, "" if success else "Ошибка удаления"
#     except Exception as e:
#         return False, str(e)


# ==========================================
# СВОДКА ИНВЕНТАРИЗАЦИИ (History Summary)
# ==========================================

async def get_history_summary(
    employee: Optional[str] = None,
    dateFrom: Optional[str] = None,
    dateTo: Optional[str] = None,
    limit: int = 500
) -> "HistorySummaryResponse":
    """
    Формирует сводку по сотрудникам и общую сводку по товарам за период.
    Учитываются только списания (quantityChange < 0).
    """
    from app.models import HistorySummaryResponse, EmployeeSummary, HistorySummaryItem

    logs = await get_logs(limit=limit)

    # Фильтр по сотруднику
    if employee:
        logs = [log for log in logs if log.get("userName") == employee or log.get("userId") == employee]

    from datetime import timezone
    # Фильтр по дате с
    if dateFrom:
        try:
            dt_from = datetime.fromisoformat(dateFrom).replace(tzinfo=timezone.utc)
            logs = [log for log in logs if log.get("timestamp") and log["timestamp"] >= dt_from]
        except ValueError:
            pass

    # Фильтр по дате по — включаем весь день до 23:59:59
    if dateTo:
        try:
            if 'T' in dateTo:
                dt_to = datetime.fromisoformat(dateTo).replace(tzinfo=timezone.utc)
            else:
                dt_to = datetime.fromisoformat(dateTo + 'T23:59:59').replace(tzinfo=timezone.utc)
            logs = [log for log in logs if log.get("timestamp") and log["timestamp"] <= dt_to]
        except ValueError:
            pass

    # Берём только списания (выдачи со склада)
    taken_logs = [log for log in logs if log.get("quantityChange", 0) < 0]

    # Группировка по сотрудникам
    per_employee: dict = {}
    totals: dict = {}

    for log in taken_logs:
        user_name = log.get("userName", "Неизвестный")
        item_name = log.get("itemName", "Неизвестный товар")
        quantity = abs(log.get("quantityChange", 0))

        # По сотрудникам
        if user_name not in per_employee:
            per_employee[user_name] = {}
        per_employee[user_name][item_name] = per_employee[user_name].get(item_name, 0) + quantity

        # Общие итоги
        totals[item_name] = totals.get(item_name, 0) + quantity

    grand_total = sum(totals.values())

    # Сортируем товары внутри каждого сотрудника по убыванию
    employee_summaries = []
    for user_name, items_dict in per_employee.items():
        sorted_items = sorted(items_dict.items(), key=lambda x: x[1], reverse=True)
        employee_summaries.append(EmployeeSummary(
            userName=user_name,
            items=[HistorySummaryItem(itemName=name, totalQuantity=qty) for name, qty in sorted_items]
        ))

    # Сортируем сотрудников по суммарному количеству взятых товаров
    employee_summaries.sort(key=lambda e: sum(it.totalQuantity for it in e.items), reverse=True)

    # Общие итоги — сортировка по убыванию
    sorted_totals = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    totals_list = [HistorySummaryItem(itemName=name, totalQuantity=qty) for name, qty in sorted_totals]

    return HistorySummaryResponse(
        perEmployee=employee_summaries,
        totals=totals_list,
        grandTotal=grand_total
    )


# ==========================================
# СТАТУС FIREBASE
# ==========================================

async def check_firebase_connection() -> dict:
    status = {
        "connected": False,
        "last_check": datetime.now(),
        "error": None,
        "collections": {},
    }
    try:
        url = f"{FIREBASE_BASE_URL}/warehouse_items"
        params = {"pageSize": 1}
        client = get_http_client()
        response = await client.get(url, params=params, headers=await _get_headers_async(), timeout=10.0)
        if response.status_code == 200:
            status["connected"] = True
        else:
            status["error"] = f"HTTP {response.status_code}"
        return status
    except Exception as e:
        status["error"] = str(e)
        return status


# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ
# ==========================================

def get_status_text(status: str) -> str:
    texts = {
        "CREATED": "Новый",
        "PROCESSING": "В сборке",
        "READY": "Готов к выдаче",
        "COMPLETED": "Выдан",
        "CANCELLED": "Отменён",
    }
    return texts.get(status, "Создан")


def get_status_color(status: str) -> str:
    colors = {
        "CREATED": "created",
        "PROCESSING": "processing",
        "READY": "ready",
        "COMPLETED": "completed",
        "CANCELLED": "danger",
    }
    return colors.get(status, "created")