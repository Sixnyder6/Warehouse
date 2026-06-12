"""
Маршруты аутентификации.
ОПТИМИЗИРОВАННАЯ ВЕРСИЯ - с кэшированием и rate limiting
"""
from fastapi import APIRouter, HTTPException, Depends, Request, Query, Response
from typing import Optional
from dataclasses import asdict
from datetime import datetime, timedelta
import logging

from app.services.auth_service import get_auth_service, AuthService
from app.models import AuthState

# ==========================================
# ЛОГГИРОВАНИЕ
# ==========================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

# ==========================================
# КЭШ ДЛЯ СОСТОЯНИЯ АУТЕНТИФИКАЦИИ
# ==========================================

class AuthStateCache:
    """Кэш для состояния аутентификации с TTL"""
    def __init__(self, ttl_seconds: int = 10):
        self._cache: dict = {}
        self._ttl = ttl_seconds
    
    def get(self, key: str):
        if key in self._cache:
            data, expires_at = self._cache[key]
            if datetime.now() < expires_at:
                logger.info(f"📦 AUTH CACHE HIT: {key[:30]}...")
                return data
            else:
                del self._cache[key]
        return None
    
    def set(self, key: str, data):
        expires_at = datetime.now() + timedelta(seconds=self._ttl)
        self._cache[key] = (data, expires_at)
    
    def clear(self, key: Optional[str] = None):
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

_auth_cache = AuthStateCache(ttl_seconds=10)

# ==========================================
# ПРОСТОЙ RATE LIMITER
# ==========================================

class RateLimiter:
    def __init__(self, requests_per_minute: int = 30):
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

_rate_limiter = RateLimiter(requests_per_minute=30)

def get_client_id(request: Request) -> str:
    """Получает идентификатор клиента по IP"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

# ==========================================
# ВНИМАНИЕ! Используем СИНГЛТОН через get_auth_service()
# вместо создания нового экземпляра каждый раз
# ==========================================

# Удаляем функцию get_auth_service и используем импортированную из auth_service
# Теперь AuthService создается 1 раз при старте приложения

@router.post("/login", response_model=AuthState)
async def login(
    request: Request,
    response: Response,
    login: str = Query(..., description="Логин (username или email)"),
    password: str = Query(..., description="Пароль"),
):
    """
    Аутентификация пользователя.
    Поддерживает вход по username или email.
    Rate limit: 10 попыток в минуту.
    """
    client_id = get_client_id(request)
    
    # Строгий лимит для логина
    login_limiter = RateLimiter(requests_per_minute=10)
    if not login_limiter.check_and_record(f"login_{client_id}"):
        logger.warning(f"🚫 Login rate limit exceeded for {client_id}")
        raise HTTPException(
            status_code=429, 
            detail="Слишком много попыток входа. Попробуйте через минуту."
        )
    
    logger.info(f"🔐 Login attempt from {client_id} for: {login}")
    
    if not login or not login.strip():
        raise HTTPException(status_code=400, detail="Логин обязателен")
    
    if not password or not password.strip():
        raise HTTPException(status_code=400, detail="Пароль обязателен")
    
    auth_service = get_auth_service()
    auth_state = await auth_service.login(login.strip(), password.strip())
    
    if auth_state.error:
        logger.warning(f"❌ Login failed for {login}: {auth_state.error}")
        raise HTTPException(status_code=401, detail=auth_state.error)
    
    # Очищаем кэш для этого пользователя
    if auth_state.user_id:
        _auth_cache.clear(f"state_{auth_state.user_id}")
        _auth_cache.clear(f"me_{auth_state.user_id}")
    
    # Сохраняем user_id в HTTP-only cookie для восстановления сессии после перезапуска сервера
    if auth_state.user_id:
        response.set_cookie(
            key="wms_user_id",
            value=auth_state.user_id,
            httponly=True,
            max_age=60 * 60 * 24 * 7,  # 7 дней
            samesite="lax",
        )
    
    logger.info(f"✅ Successful login: {login} from {client_id}")
    
    return auth_state


@router.post("/logout", response_model=AuthState)
async def logout(request: Request, response: Response):
    """
    Выход пользователя.
    """
    client_id = get_client_id(request)
    
    if not _rate_limiter.check_and_record(client_id):
        raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте позже.")
    
    logger.info(f"👋 Logout request from {client_id}")
    
    auth_service = get_auth_service()
    auth_state = await auth_service.logout()
    
    # Удаляем cookie сессии
    response.delete_cookie(key="wms_user_id")
    
    logger.info(f"✅ Successful logout from {client_id}")
    
    return auth_state


@router.get("/state", response_model=AuthState)
async def get_auth_state(
    request: Request,
    user_id: Optional[str] = Query(None, description="ID пользователя"),
    force_refresh: bool = Query(False, description="Принудительное обновление кэша"),
):
    """
    Получить текущее состояние аутентификации.
    Использует кэширование для уменьшения нагрузки на Firestore.
    """
    client_id = get_client_id(request)
    
    if not _rate_limiter.check_and_record(client_id):
        raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте позже.")
    
    auth_service = get_auth_service()
    
    # Если нет user_id, возвращаем состояние текущего пользователя
    if not user_id:
        if auth_service.current_user_id:
            user_id = auth_service.current_user_id
        else:
            logger.info(f"📭 No user_id provided, returning default state")
            return AuthState(is_logged_in=False, is_loading=False)
    
    # Проверяем кэш
    cache_key = f"state_{user_id}"
    if not force_refresh:
        cached = _auth_cache.get(cache_key)
        if cached:
            return cached
    
    logger.info(f"🔄 Fetching fresh auth state for user {user_id}")
    
    auth_state = await auth_service.get_user_state(user_id)
    
    # Кэшируем
    _auth_cache.set(cache_key, auth_state)
    
    return auth_state


@router.get("/me", response_model=AuthState)
async def get_current_user(
    request: Request,
    response: Response,
    force_refresh: bool = Query(False, description="Принудительное обновление кэша"),
):
    """
    Получить информацию о текущем авторизованном пользователе.
    Если сессия сброшена (перезапуск сервера) — пробует восстановить её из cookie.
    """
    client_id = get_client_id(request)
    
    if not _rate_limiter.check_and_record(client_id):
        raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте позже.")
    
    auth_service = get_auth_service()
    
    # Если in-memory сессия пуста — пробуем восстановить из cookie (после перезапуска сервера)
    if not auth_service.current_user_id:
        cookie_user_id = request.cookies.get("wms_user_id")
        if cookie_user_id:
            logger.info(f"🍪 Restoring session from cookie for user_id={cookie_user_id}")
            try:
                restored_state = await auth_service.initialize_auth_state(cookie_user_id)
                if restored_state.is_logged_in:
                    logger.info(f"✅ Session restored from cookie for {cookie_user_id}")
                    cache_key = f"me_{cookie_user_id}"
                    _auth_cache.set(cache_key, restored_state)
                    return restored_state
                else:
                    logger.warning(f"⚠️ Cookie user_id={cookie_user_id} not found in Firestore, clearing cookie")
                    response.delete_cookie(key="wms_user_id")
                    return AuthState(is_logged_in=False, is_loading=False)
            except Exception as e:
                logger.error(f"❌ Failed to restore session from cookie: {e}")
                response.delete_cookie(key="wms_user_id")
                return AuthState(is_logged_in=False, is_loading=False)
        else:
            logger.info(f"📭 No current user and no cookie for {client_id}")
            return AuthState(is_logged_in=False, is_loading=False)
    
    # Проверяем кэш
    cache_key = f"me_{auth_service.current_user_id}"
    if not force_refresh:
        cached = _auth_cache.get(cache_key)
        if cached:
            return cached
    
    auth_state = await auth_service.get_user_state(auth_service.current_user_id)
    _auth_cache.set(cache_key, auth_state)
    
    return auth_state


@router.post("/shift/start", response_model=AuthState)
async def start_shift(
    request: Request,
    user_id: str = Query(..., description="ID пользователя"),
):
    """
    Начать смену.
    """
    client_id = get_client_id(request)
    
    # Более строгий лимит для операций со сменами
    shift_limiter = RateLimiter(requests_per_minute=5)
    if not shift_limiter.check_and_record(f"shift_{client_id}"):
        raise HTTPException(
            status_code=429, 
            detail="Слишком много операций со сменами. Попробуйте позже."
        )
    
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id обязателен")
    
    logger.info(f"🟢 Start shift request from {client_id} for user {user_id}")
    
    auth_service = get_auth_service()
    auth_state = await auth_service.start_shift_locally(user_id)
    
    if auth_state.error:
        raise HTTPException(status_code=400, detail=auth_state.error)
    
    # Очищаем кэш для этого пользователя
    _auth_cache.clear(f"state_{user_id}")
    _auth_cache.clear(f"me_{user_id}")
    
    logger.info(f"✅ Shift started for user {user_id}")
    
    return auth_state


@router.post("/shift/end", response_model=AuthState)
async def end_shift(
    request: Request,
    user_id: str = Query(..., description="ID пользователя"),
):
    """
    Закончить смену.
    """
    client_id = get_client_id(request)
    
    # Более строгий лимит для операций со сменами
    shift_limiter = RateLimiter(requests_per_minute=5)
    if not shift_limiter.check_and_record(f"shift_{client_id}"):
        raise HTTPException(
            status_code=429, 
            detail="Слишком много операций со сменами. Попробуйте позже."
        )
    
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id обязателен")
    
    logger.info(f"🔴 End shift request from {client_id} for user {user_id}")
    
    auth_service = get_auth_service()
    auth_state = await auth_service.end_shift_locally(user_id)
    
    if auth_state.error:
        raise HTTPException(status_code=400, detail=auth_state.error)
    
    # Очищаем кэш для этого пользователя
    _auth_cache.clear(f"state_{user_id}")
    _auth_cache.clear(f"me_{user_id}")
    
    logger.info(f"✅ Shift ended for user {user_id}")
    
    return auth_state


@router.post("/clear-error", response_model=AuthState)
async def clear_error(request: Request):
    """
    Очистить ошибку аутентификации.
    """
    client_id = get_client_id(request)
    
    if not _rate_limiter.check_and_record(client_id):
        raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте позже.")
    
    logger.info(f"🧹 Clear error request from {client_id}")
    
    auth_service = get_auth_service()
    auth_state = auth_service.clear_error()
    
    return auth_state


@router.get("/version-check")
async def version_check(
    request: Request,
    min_version: Optional[str] = Query(None, description="Минимальная версия приложения"),
):
    """
    Проверка версии приложения.
    Результат кэшируется на стороне сервиса.
    """
    client_id = get_client_id(request)
    
    # Либеральный лимит для проверки версии
    version_limiter = RateLimiter(requests_per_minute=60)
    if not version_limiter.check_and_record(f"version_{client_id}"):
        raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте позже.")
    
    auth_service = get_auth_service()
    version_ok = await auth_service.check_version_and_block(min_version or "1.0.0")
    
    return {
        "version_ok": version_ok,
        "timestamp": datetime.now().isoformat(),
        "cache_ttl_seconds": 300
    }


@router.get("/health")
async def auth_health():
    """
    Health check для auth роутов.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "AuthService (singleton)"
    }