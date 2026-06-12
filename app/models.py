from datetime import datetime
from typing import List, Optional
from enum import Enum

from pydantic import BaseModel, Field

# ==========================================
# МОДЕЛИ ТОВАРОВ (ОБНОВЛЕНО ДЛЯ LOCAL-FIRST)
# ==========================================

class WarehouseItem(BaseModel):
    """Основная модель товара на складе (из Kotlin WarehouseItem)"""
    id: str = ""
    fullName: str = ""
    shortName: str = ""
    sku: Optional[str] = None
    description: Optional[str] = None
    category: str = "Общее"
    unit: str = "шт."
    stockCount: int = 0
    totalStock: int = 0
    lowStockThreshold: int = 10
    imageUrl: Optional[str] = None
    keywords: List[str] = []
    
    # НОВЫЕ ПОЛЯ ДЛЯ СИНХРОНИЗАЦИИ С БРАУЗЕРОМ
    updatedAt: Optional[datetime] = None
    isDeleted: bool = False


class WarehouseItemCreate(BaseModel):
    """Модель для создания товара"""
    fullName: str
    shortName: str
    sku: Optional[str] = None
    description: Optional[str] = None
    category: str = "Общее"
    unit: str = "шт."
    stockCount: int = 0
    totalStock: int = 0
    lowStockThreshold: int = 10
    imageUrl: Optional[str] = None


class WarehouseItemUpdate(BaseModel):
    """Модель для обновления товара"""
    fullName: Optional[str] = None
    shortName: Optional[str] = None
    sku: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    stockCount: Optional[int] = None
    totalStock: Optional[int] = None
    lowStockThreshold: Optional[int] = None
    imageUrl: Optional[str] = None


# ==========================================
# МОДЕЛИ ЖУРНАЛА ОПЕРАЦИЙ
# ==========================================

class WarehouseLog(BaseModel):
    """Модель записи в журнале операций (из Kotlin WarehouseLog)"""
    id: str = ""
    itemId: str = ""
    itemName: str = ""
    userId: str = ""
    userName: str = "Неизвестный"
    quantityChange: int = 0  # отриц. — взяли, полож. — добавили
    timestamp: Optional[datetime] = None


class GroupedActivity(BaseModel):
    """Сгруппированная запись для UI (из Kotlin GroupedActivity)"""
    userName: str
    items: List[dict]  # [{"itemName": str, "quantity": int}]
    timestamp: Optional[datetime] = None


# ==========================================
# СИСТЕМА ЗАКАЗОВ
# ==========================================

class OrderStatus(str, Enum):
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderItem(BaseModel):
    """Элемент внутри заказа (из Kotlin OrderItem)"""
    itemId: str = ""
    itemName: str = ""
    itemImageUrl: Optional[str] = None
    quantity: int = 0
    unit: str = "шт."


class WarehouseOrder(BaseModel):
    """Модель заказа (из Kotlin WarehouseOrder)"""
    id: str = ""
    userId: str = ""
    userName: str = ""
    userRole: str = ""
    items: List[OrderItem] = []
    status: OrderStatus = OrderStatus.CREATED
    createdAt: Optional[datetime] = None
    completedAt: Optional[datetime] = None


class WarehouseOrderCreate(BaseModel):
    """Модель для создания заказа"""
    userId: str
    userName: str
    userRole: str = ""
    items: List[OrderItem]
    status: OrderStatus = OrderStatus.CREATED


class OrderStatusUpdate(BaseModel):
    """Модель для обновления статуса заказа"""
    status: OrderStatus


class CompleteOrderRequest(BaseModel):
    """Запрос на завершение заказа (выдачу)"""
    warehouseManName: str = "Кладовщик"


# ==========================================
# ИСТОРИЯ ОПЕРАЦИЙ (СТАРЫЕ МОДЕЛИ)
# ==========================================

class HistoryEntry(BaseModel):
    """Краткая запись операции для таблицы"""
    id: str
    employee_name: str
    employee_id: Optional[str] = None
    item_name: str
    sku: Optional[str] = None
    quantity: int
    unit: str = "шт."
    status: str
    timestamp: datetime


class HistoryDetail(BaseModel):
    """Подробная информация о операции (для модального окна)"""
    id: str
    employee_name: str
    employee_id: Optional[str] = None
    items: List[dict]
    status: str
    notes: Optional[str] = None
    timestamp: datetime


class HistoryStats(BaseModel):
    """Агрегированные данные для графика"""
    dates: List[str]
    counts: List[int]


class HistorySummaryItem(BaseModel):
    """Товар и количество в сводке"""
    itemName: str
    totalQuantity: int


class EmployeeSummary(BaseModel):
    """Сводка по одному сотруднику"""
    userName: str
    items: List[HistorySummaryItem]


class HistorySummaryResponse(BaseModel):
    """Ответ для сводки инвентаризации"""
    perEmployee: List[EmployeeSummary]
    totals: List[HistorySummaryItem]
    grandTotal: int


# ==========================================
# НОВОСТИ
# ==========================================

class NewsTag(str, Enum):
    TODAY = "TODAY"
    TOMORROW = "TOMORROW"
    URGENT = "URGENT"
    GENERAL = "GENERAL"


class NewsItem(BaseModel):
    """Модель новости (из Kotlin NewsItem)"""
    id: str = ""
    title: str = ""
    content: str = ""
    tag: NewsTag = NewsTag.GENERAL


class NewsItemCreate(BaseModel):
    """Модель для создания новости"""
    title: str
    content: str
    tag: NewsTag = NewsTag.GENERAL


# ==========================================
# СОТРУДНИКИ
# ==========================================

class Employee(BaseModel):
    """Модель сотрудника"""
    id: str = ""
    name: str = ""
    role: str = "staff"
    imageUrl: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = "offline"


# ==========================================
# МОДЕЛИ СОТРУДНИКОВ (CRUD)
# ==========================================

class InternalUserCreate(BaseModel):
    """Модель для создания/обновления внутреннего пользователя"""
    displayName: str
    username: str
    password: str = ""
    role: str = "muver"
    warehouseId: str = "bestuzhevskaya_10"
    phone: str = ""


# ==========================================
# МОДЕЛИ АУТЕНТИФИКАЦИИ (Android AuthManager)
# ==========================================

class UserRole(str, Enum):
    ADMIN = "admin"
    MOVER = "muver"
    ELECTRICIAN = "electrician"
    INVENTORY_MANAGER = "inventory_manager"
    TECHNIC = "technic"
    SUPERVISOR = "supervisor"
    SECURITY = "security"
    USER = "user"

    @classmethod
    def from_key(cls, key: Optional[str]) -> "UserRole":
        for role in cls:
            if role.value == key:
                return role
        return cls.USER

    @classmethod
    def get_selectable_roles(cls) -> List["UserRole"]:
        return [role for role in cls if role != cls.USER]


class ShiftRequestStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"

    @classmethod
    def from_key(cls, key: Optional[str]) -> "ShiftRequestStatus":
        for status in cls:
            if status.value == key:
                return status
        return cls.NONE


class AuthState(BaseModel):
    is_logged_in: bool = False
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    is_admin: bool = False
    role: UserRole = UserRole.USER
    error: Optional[str] = None
    is_loading: bool = True
    is_shift_active: bool = False
    shift_start_time: int = 0
    is_allowed_to_work: bool = False
    shift_request_status: ShiftRequestStatus = ShiftRequestStatus.NONE
    version_error: bool = False


# ==========================================
# ЗАПРОСЫ
# ==========================================

class TakeItemRequest(BaseModel):
    """Запрос на списание товара"""
    itemId: str
    quantity: int = 1
    userName: str = "Пользователь"
    userId: str = ""


class TakeItemBatchElement(BaseModel):
    itemId: str
    quantity: int = 1


class TakeItemBatchRequest(BaseModel):
    items: List[TakeItemBatchElement]
    userName: str = "Пользователь"
    userId: str = ""


class AddStockRequest(BaseModel):
    """Запрос на пополнение товара"""
    itemId: str
    quantity: int
    userName: str = "Администратор"
    userId: str = ""


# ==========================================
# НОВЫЕ МОДЕЛИ ДЛЯ ОФЛАЙН-СИНХРОНИЗАЦИИ (DEXIE.JS)
# ==========================================

class SyncPushOperation(BaseModel):
    """Модель одной операции из офлайн-очереди браузера"""
    id: str  # Локальный ID операции (для идемпотентности)
    type: str  # "TAKE" или "ADD"
    itemId: str
    quantity: int
    userName: str
    userId: str
    timestamp: datetime  # Фактическое время, когда кладовщик нажал кнопку в офлайне


class SyncPushRequest(BaseModel):
    """Пакет операций, которые браузер отправляет при появлении интернета"""
    operations: List[SyncPushOperation]


class SyncPullResponse(BaseModel):
    """Ответ сервера с измененными товарами"""
    items: List[dict]
    serverTime: datetime


# ==========================================
# МОДЕЛИ ДЛЯ ВЫДАЧИ С ВЫБОРОМ ПОЛУЧАТЕЛЯ
# ==========================================

class TakeItemExtendedRequest(BaseModel):
    """Запрос на выдачу товара получателю (кладовщик → сотрудник)"""
    itemId: str
    quantity: int = 1
    recipientName: str           # Кто получает (Петя)
    recipientId: str = ""        # ID получателя
    issuerName: str = ""         # Кто выдаёт (кладовщик) — заполняется на сервере
    issuerId: str = ""           # ID выдающего
    notes: str = ""              # Примечание (опционально)


class ReturnItemRequest(BaseModel):
    """Запрос на возврат товара (сотрудник вернул на склад)"""
    itemId: str
    quantity: int = 1
    recipientName: str           # Кто возвращает (Петя)
    recipientId: str = ""        # ID возвращающего
    issuerName: str = ""         # Кто принял возврат (кладовщик)
    issuerId: str = ""           # ID принявшего
    notes: str = ""              # Причина возврата


# ==========================================
# ДАШБОРД СВОДКА (ОПТИМИЗАЦИЯ СЕТИ)
# ==========================================

class DashboardSummary(BaseModel):
    """Сводка ключевых показателей склада для минимизации чтений базы"""
    totalItems: int
    lowStockCount: int
    activeOrdersCount: int
    todayOperationsCount: int
    recentLogs: List[WarehouseLog]


# ==========================================
# ПРОГНОЗ ОСТАТКОВ
# ==========================================

class ForecastItem(BaseModel):
    """Прогноз по одному товару: на сколько дней хватит остатка"""
    itemId: str
    itemName: str
    sku: Optional[str] = None
    category: str = ""
    imageUrl: Optional[str] = None
    stockCount: int = 0
    lowStockThreshold: int = 10
    avgDailyConsumption: float = 0.0
    daysRemaining: Optional[float] = None  # None = нет данных о расходе (=∞)

