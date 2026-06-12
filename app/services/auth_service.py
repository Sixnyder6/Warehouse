# =========================================================================================
# ⚠️ ВНИМАНИЕ / WARNING: ОГРАНИЧЕНИЕ ТРАФИКА FIRESTORE!
# Ежедневный лимит на операции чтения Firestore ограничен 50,000 запросов!
# Любые новые запросы, циклы опроса или синхронизации ДОЛЖНЫ БЫТЬ МАКСИМАЛЬНО ОПТИМИЗИРОВАНЫ.
# Обязательно используйте серверное кэширование и IndexedDB-синхронизацию на клиенте.
# Избегайте бесконечных циклов опроса (polling) и некэшированных повторных чтений!
# =========================================================================================

import os

# ── Убираем SOCKS/HTTP прокси из окружения ДО создания любых HTTP-клиентов.
# Clash / V2Ray / другие VPN-клиенты прописывают HTTP_PROXY=socks4://127.0.0.1:...
# httpx и google-auth подхватывают эти переменные и падают, т.к. socks4 требует
# отдельной библиотеки (httpx[socks]). Чистим здесь раз и навсегда для этого процесса.
for _proxy_env_var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                        "ALL_PROXY", "all_proxy"):
    os.environ.pop(_proxy_env_var, None)

import json
import hashlib
import time
import asyncio
import threading
import logging
import httpx

_http_client = None

def get_http_client() -> httpx.AsyncClient:
    """Чистый HTTP-клиент без прокси для Firestore/Google API."""
    global _http_client
    if _http_client is None:
                # trust_env=False — полностью отключает прокси из env И из реестра Windows.
        # Без этого Clash/V2Ray/другие VPN-клиенты ломают все запросы к Firestore.
        _http_client = httpx.AsyncClient(trust_env=False)
    return _http_client
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple
from google.oauth2 import service_account
from google.auth.transport.requests import Request as AuthRequest

from app.models import AuthState, UserRole, ShiftRequestStatus
from app.services.telemetry_service import log_operation

# ==========================================
# ЛОГГИРОВАНИЕ
# ==========================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# FIREBASE КОНФИГУРАЦИЯ
# ==========================================

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

PROJECT_ID = cred_data['project_id']
FIREBASE_BASE_URL = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents"

# API-ключ из google-services.json для Firebase Auth REST API
FIREBASE_AUTH_API_KEY = "AIzaSyCmI-vKOZs5ETMCLYh9-lSk9kdNfxT46-4"

# Создаем credentials и получаем токен
_creds = service_account.Credentials.from_service_account_info(
    cred_data,
    scopes=['https://www.googleapis.com/auth/datastore']
)

# Кэш + защёлка для токена
_token_cache: dict = {"token": None, "expires_at": None}
_token_lock = threading.Lock()  # гарантирует что только 1 поток обновляет токен


def _get_bearer_token_sync() -> Optional[str]:
    """Синхронное обновление OAuth2 токена — вызывать только из asyncio.to_thread!"""
    with _token_lock:  # только 1 поток в момент времени
        now = datetime.now()
        if _token_cache["token"] and _token_cache["expires_at"] and now < _token_cache["expires_at"]:
            return _token_cache["token"]  # другой поток уже обновил — отдаём закэшированный

        for attempt in range(2):
            try:
                import socket
                import requests as _requests
                # Создаём requests-сессию без прокси (для совместимости с VPN/Clash)
                _session = _requests.Session()
                _session.proxies = {}  # отключаем прокси
                _auth_request = AuthRequest(session=_session)
                socket.setdefaulttimeout(10)
                _creds.refresh(_auth_request)
                token = _creds.token
                _token_cache["token"] = token
                _token_cache["expires_at"] = now + timedelta(seconds=3000)
                logger.info("✅ OAuth2 token refreshed")
                return token
            except Exception as e:
                logger.warning(f"⚠️ Attempt {attempt + 1} to get OAuth2 token failed: {e}")
                if attempt < 1:
                    time.sleep(0.5)
                else:
                    logger.error(f"❌ Failed to get OAuth2 token after 2 attempts: {e}")
    return None

async def _get_headers_async() -> dict:
    """Асинхронное получение заголовков — НЕ блокирует event loop."""
    now = datetime.now()
    if _token_cache["token"] and _token_cache["expires_at"] and now < _token_cache["expires_at"]:
        return {
            'Authorization': f'Bearer {_token_cache["token"]}',
            'Content-Type': 'application/json',
        }
    token = await asyncio.to_thread(_get_bearer_token_sync)
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }


def _convert_fields(fields: dict) -> dict:
    """Конвертирует Firestore fields format в простой dict."""
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
            result[key] = value['timestampValue']
        elif 'arrayValue' in value:
            result[key] = value['arrayValue'].get('values', [])
        elif 'mapValue' in value:
            result[key] = _convert_fields(value['mapValue'].get('fields', {}))
        else:
            result[key] = str(value)
    return result


# ==========================================
# FIREBASE AUTH REST API
# ==========================================

async def firebase_auth_sign_in(email: str, password: str) -> Optional[dict]:
    """
    Вход через Firebase Authentication REST API.
    Возвращает ответ от Firebase Auth или None при ошибке.
    """
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_AUTH_API_KEY}"
    payload = {
        "email": email,
        "password": password,
        "returnSecureToken": True
    }
    try:
        client = get_http_client()
        response = await client.post(url, json=payload, timeout=10.0)
        if response.status_code == 200:
            data = response.json()
            logger.info(f"✅ Firebase Auth success for {email}: localId={data.get('localId')}")
            return data
        elif response.status_code == 400:
            error_data = response.json()
            error_message = error_data.get('error', {}).get('message', 'UNKNOWN')
            logger.warning(f"❌ Firebase Auth error for {email}: {error_message}")
            return None
        else:
            logger.error(f"❌ Firebase Auth HTTP {response.status_code}: {response.text[:200]}")
            return None
    except Exception as e:
        logger.error(f"❌ Firebase Auth exception: {e}")
        return None


# =========================================================================================
# ⚠️ ВНИМАНИЕ / WARNING: ОГРАНИЧЕНИЕ ТРАФИКА FIRESTORE!
# Следующие функции напрямую обращаются к удаленной базе данных Firestore.
# Любой вызов без серверного кэширования тратит драгоценный лимит (50,000 операций/день).
# Никогда не вызывайте эти функции в бесконечных циклах без адекватного кэша и дебаунса!
# =========================================================================================

# ==========================================
# FIRESTORE ФУНКЦИИ (через REST API)
# ==========================================

async def firestore_get_document(collection: str, doc_id: str) -> Optional[dict]:
    """Получить документ через REST API."""
    url = f"{FIREBASE_BASE_URL}/{collection}/{doc_id}"
    try:
        t0 = time.time()
        client = get_http_client()
        headers = await _get_headers_async()
        response = await client.get(url, headers=headers, timeout=10.0)
        latency_ms = int((time.time() - t0) * 1000)
        log_operation("READ", collection, 1, latency_ms)
        if response.status_code == 200:
            data = response.json()
            fields = data.get('fields', {})
            result = _convert_fields(fields)
            result['id'] = doc_id
            return result
        elif response.status_code == 429:
            logger.warning(f"Firestore quota exceeded (get document)")
            return None
        elif response.status_code == 404:
            logger.warning(f"Document {collection}/{doc_id} not found")
            return None
        elif response.status_code == 403:
            logger.error(f"Firestore 403: {response.text}")
            return None
        else:
            logger.error(f"Firestore get error {response.status_code}: {response.text[:200]}")
            return None
    except Exception as e:
        logger.error(f"Firestore get exception: {e}")
        return None


async def firestore_query_by_field(collection: str, field: str, value: str, limit: int = 1) -> List[dict]:
    """Найти документы по полю через REST API."""
    url = f"{FIREBASE_BASE_URL}:runQuery"

    query = {
        "structuredQuery": {
            "from": [{"collectionId": collection}],
            "where": {
                "fieldFilter": {
                    "field": {"fieldPath": field},
                    "op": "EQUAL",
                    "value": {"stringValue": value}
                }
            },
            "limit": limit
        }
    }

    try:
        t0 = time.time()
        client = get_http_client()
        headers = await _get_headers_async()
        response = await client.post(url, json=query, headers=headers, timeout=10.0)
        latency_ms = int((time.time() - t0) * 1000)
        if response.status_code == 200:
            results = response.json()
            documents = []
            for result in results:
                if 'document' in result:
                    doc = result['document']
                    doc_id = doc['name'].split('/')[-1]
                    fields = doc.get('fields', {})
                    doc_data = _convert_fields(fields)
                    doc_data['id'] = doc_id
                    documents.append(doc_data)
            log_operation("READ", collection, max(1, len(documents)), latency_ms)
            return documents
        elif response.status_code == 429:
            logger.warning(f"Firestore quota exceeded (query)")
            log_operation("READ", collection, 1, latency_ms)
            return []
        elif response.status_code == 403:
            logger.error(f"Firestore 403: {response.text[:200]}")
            log_operation("READ", collection, 1, latency_ms)
            return []
        else:
            logger.error(f"Firestore query error {response.status_code}: {response.text[:200]}")
            log_operation("READ", collection, 1, latency_ms)
            return []
    except Exception as e:
        logger.error(f"Firestore query exception: {e}")
        log_operation("READ", collection, 1)
        return []


async def firestore_update_document(collection: str, doc_id: str, updates: dict) -> bool:
    """Обновить документ в Firestore через REST API."""
    mask_params = "&".join(f"updateMask.fieldPaths={key}" for key in updates.keys())
    url = f"{FIREBASE_BASE_URL}/{collection}/{doc_id}?{mask_params}"

    fields = {}
    for key, value in updates.items():
        if isinstance(value, str):
            fields[key] = {"stringValue": value}
        elif isinstance(value, bool):
            fields[key] = {"booleanValue": value}
        elif isinstance(value, int):
            fields[key] = {"integerValue": str(value)}
        else:
            fields[key] = {"stringValue": str(value)}

    try:
        t0 = time.time()
        client = get_http_client()
        headers = await _get_headers_async()
        response = await client.patch(url, json={"fields": fields}, headers=headers, timeout=10.0)
        latency_ms = int((time.time() - t0) * 1000)
        log_operation("WRITE", collection, 1, latency_ms)
        if response.status_code == 200:
            return True
        elif response.status_code == 429:
            logger.warning(f"Firestore quota exceeded (update)")
            return False
        else:
            logger.warning(f"Firestore update error {response.status_code}: {response.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Firestore update exception: {e}")
        return False


# ==========================================
# КЭШ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ
# ==========================================

class UserCache:
    def __init__(self, default_ttl_seconds: int = 60):
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

_user_cache = UserCache(default_ttl_seconds=60)
_version_cache = UserCache(default_ttl_seconds=300)


# ==========================================
# ОСНОВНОЙ СЕРВИС
# ==========================================

class AuthService:
    def __init__(self):
        self.current_user_id: Optional[str] = None
        self._auth_state: Optional[AuthState] = None
        logger.info("🔐 AuthService initialized with Firebase Auth + REST API")

    async def get_user_by_email(self, email: str, use_cache: bool = True) -> Optional[dict]:
        """
        Найти пользователя в коллекции internal_users по email.
        """
        cache_key = f"user_email_{email}"
        if use_cache:
            cached = _user_cache.get(cache_key)
            if cached is not None:
                return cached

        users = await firestore_query_by_field("internal_users", "email", email, limit=1)
        if users:
            user = users[0]
            if use_cache:
                _user_cache.set(cache_key, user, ttl_seconds=120)
            return user
        return None

    async def get_user_by_username(self, username: str, use_cache: bool = True) -> Optional[dict]:
        """
        Поиск по username (оставлено для обратной совместимости, но не используется для входа).
        """
        cache_key = f"user_{username}"
        if use_cache:
            cached = _user_cache.get(cache_key)
            if cached is not None:
                return cached

        users = await firestore_query_by_field("internal_users", "username", username, limit=1)
        if users:
            user = users[0]
            if use_cache:
                _user_cache.set(cache_key, user, ttl_seconds=120)
            return user
        return None

    async def get_user_by_id(self, user_id: str, use_cache: bool = True) -> Optional[dict]:
        cache_key = f"user_id_{user_id}"
        if use_cache:
            cached = _user_cache.get(cache_key)
            if cached is not None:
                return cached

        user = await firestore_get_document("internal_users", user_id)
        if user and use_cache:
            _user_cache.set(cache_key, user, ttl_seconds=120)
        return user

    def _verify_password(self, password: str, stored_password: str) -> bool:
        """Проверяет пароль: поддерживает hash:SHA256 и открытый текст."""
        if not stored_password:
            return False
        # Хешированный пароль
        if stored_password.startswith("hash:"):
            try:
                hash_value = stored_password[5:]
                computed_hash = hashlib.sha256(password.encode()).hexdigest()
                return computed_hash == hash_value
            except Exception:
                return False
        # Открытый текст
        return password == stored_password

    async def login(self, login: str, password: str) -> AuthState:
        """
        Вход в систему:
        1. Если login содержит '@' — ищем по email, иначе по username
        2. Проверяем пароль локально (hash:SHA256 или открытый текст)
        3. Загружаем данные (роль, права, смена)
        """
        logger.info(f"🔐 Login attempt: {login}")

        if not login or not login.strip():
            return AuthState(
                is_logged_in=False,
                is_loading=False,
                error="Введите логин или email"
            )

        login = login.strip()

        # 1. Поиск пользователя: по email или username
        user = None
        if '@' in login:
            # Пробуем найти по email
            user = await self.get_user_by_email(login, use_cache=False)
            if not user:
                logger.warning(f"❌ Пользователь с email '{login}' не найден в internal_users")
                return AuthState(
                    is_logged_in=False,
                    is_loading=False,
                    error="Пользователь с таким email не найден в системе"
                )
        else:
            # Ищем по username
            user = await self.get_user_by_username(login, use_cache=False)
            if not user:
                logger.warning(f"❌ Пользователь '{login}' не найден в internal_users")
                return AuthState(
                    is_logged_in=False,
                    is_loading=False,
                    error="Пользователь не найден"
                )

        # 2. Проверка пароля
        stored_password = user.get("password", "")
        if not self._verify_password(password, stored_password):
            logger.warning(f"❌ Неверный пароль для {login}")
            return AuthState(
                is_logged_in=False,
                is_loading=False,
                error="Неверный логин или пароль"
            )

        # 3. Проверка isAllowedToWork
        is_allowed = user.get("isAllowedToWork", True)
        # Если поле отсутствует (N/A) — считаем что разрешено
        if is_allowed is None or is_allowed == "N/A":
            is_allowed = True
        if not is_allowed:
            logger.warning(f"❌ Пользователь {login} заблокирован (isAllowedToWork=False)")
            return AuthState(
                is_logged_in=False,
                is_loading=False,
                error="Доступ заблокирован"
            )

        # 4. Загружаем данные пользователя
        self.current_user_id = user.get('id')
        display_name = user.get('displayName') or user.get('username', login)

        role_str = user.get('role', 'user')
        try:
            role = UserRole(role_str)
        except ValueError:
            role = UserRole.USER

        is_shift_active = user.get('isShiftActive', False)
        shift_start_time = user.get('shiftStartTime', 0)
        shift_request_status_str = user.get('shiftRequestStatus', 'NONE')
        shift_request_status = ShiftRequestStatus.from_key(shift_request_status_str)

        # Конвертируем shift_start_time в int если строка
        if isinstance(shift_start_time, str):
            try:
                shift_start_time = int(shift_start_time)
            except (ValueError, TypeError):
                shift_start_time = 0

        auth_state = AuthState(
            is_logged_in=True,
            is_loading=False,
            user_id=self.current_user_id,
            user_name=display_name,
            role=role,
            is_admin=role == UserRole.ADMIN,
            is_allowed_to_work=is_allowed,
            is_shift_active=is_shift_active,
            shift_start_time=shift_start_time,
            shift_request_status=shift_request_status,
            error=None
        )

        self._auth_state = auth_state

        # Обновляем lastSeen в Firestore — для телеметрии (онлайн-статус)
        now_ms = int(datetime.now().timestamp() * 1000)
        await firestore_update_document("internal_users", self.current_user_id, {"lastSeen": now_ms})

        # Очищаем кэш авторизации
        _user_cache.clear(f"user_state_{self.current_user_id}")
        _user_cache.clear(f"user_id_{self.current_user_id}")

        logger.info(f"✅ {login} вошёл в систему как {role.value} ({display_name})")
        return auth_state

    async def logout(self) -> AuthState:
        if self.current_user_id:
            await firestore_update_document("internal_users", self.current_user_id, {"lastSeen": 0})
            logger.info(f"👋 {self.current_user_id} вышел")

        self.current_user_id = None
        self._auth_state = None
        return AuthState(is_logged_in=False, is_loading=False)

    async def initialize_auth_state(self, user_id: str) -> AuthState:
        logger.info(f"🔄 Инициализация состояния пользователя {user_id}")

        user = await self.get_user_by_id(user_id)
        if not user:
            return AuthState(is_logged_in=False, is_loading=False, error="Пользователь не найден")

        self.current_user_id = user_id

        role_str = user.get('role', 'user')
        try:
            role = UserRole(role_str)
        except ValueError:
            role = UserRole.USER

        is_shift_active = user.get('isShiftActive', False)
        shift_start_time = user.get('shiftStartTime', 0)
        shift_request_status_str = user.get('shiftRequestStatus', 'NONE')
        shift_request_status = ShiftRequestStatus.from_key(shift_request_status_str)

        if isinstance(shift_start_time, str):
            try:
                shift_start_time = int(shift_start_time)
            except (ValueError, TypeError):
                shift_start_time = 0

        auth_state = AuthState(
            is_logged_in=True,
            is_loading=False,
            user_id=user_id,
            user_name=user.get('displayName') or user.get('username'),
            role=role,
            is_admin=role == UserRole.ADMIN,
            is_allowed_to_work=user.get('isAllowedToWork', True),
            is_shift_active=is_shift_active,
            shift_start_time=shift_start_time,
            shift_request_status=shift_request_status,
            error=None
        )

        self._auth_state = auth_state
        return auth_state

    async def get_user_state(self, user_id: str) -> AuthState:
        cache_key = f"user_state_{user_id}"
        cached = _user_cache.get(cache_key)
        if cached:
            return cached

        auth_state = await self.initialize_auth_state(user_id)
        _user_cache.set(cache_key, auth_state, ttl_seconds=30)
        return auth_state

    async def start_shift_locally(self, user_id: str) -> AuthState:
        return await self.get_user_state(user_id)

    async def end_shift_locally(self, user_id: str) -> AuthState:
        return await self.get_user_state(user_id)

    def clear_error(self) -> AuthState:
        if self._auth_state:
            return AuthState(
                is_logged_in=self._auth_state.is_logged_in,
                is_loading=False,
                user_id=self._auth_state.user_id,
                user_name=self._auth_state.user_name,
                role=self._auth_state.role,
                error=None
            )
        return AuthState(is_logged_in=False, is_loading=False)

    async def check_version_and_block(self, min_version: str = "1.0.0") -> bool:
        return True


# ==========================================
# СИНГЛТОН
# ==========================================

_auth_service_instance: Optional[AuthService] = None

def get_auth_service() -> AuthService:
    global _auth_service_instance
    if _auth_service_instance is None:
        _auth_service_instance = AuthService()
    return _auth_service_instance