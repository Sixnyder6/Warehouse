"""
Сервис прогноза остатков.
Считает среднесуточный расход по логам за последние N дней
и вычисляет на сколько дней хватит текущего остатка.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from collections import defaultdict

from app.models import ForecastItem
from app.services.warehouse_service import get_logs, get_items

logger = logging.getLogger(__name__)

_forecast_cache: Optional[tuple] = None  # (data, expires_at)


async def calculate_forecast(days: int = 30) -> List[ForecastItem]:
    """
    Вычисляет прогноз остатков для всех товаров.
    
    Алгоритм:
    1. Загружаем логи за последние N дней
    2. Суммируем только отрицательные quantityChange (списания)
    3. avgDailyConsumption = totalTaken / days
    4. daysRemaining = stockCount / avgDailyConsumption
    5. Сортируем по возрастанию daysRemaining (самые критичные первые)
    
    Кэшируется на 60 секунд чтобы не грузить Firestore.
    """
    global _forecast_cache
    
    # Проверяем кэш
    now = datetime.now()
    if _forecast_cache:
        data, expires_at = _forecast_cache
        if now < expires_at:
            logger.info(f"📦 FORECAST CACHE HIT ({len(data)} items)")
            return data
    
    # 1. Загружаем логи за последние N дней
    cutoff_date = now - timedelta(days=days)
    cutoff_ts = cutoff_date.replace(tzinfo=timezone.utc)
    
    # Берём максимум 5000 логов (Firestore limit)
    logs = await get_logs(limit=5000)
    
    # Фильтруем логи за нужный период
    recent_logs = []
    for log in logs:
        ts = log.get("timestamp")
        if ts is None:
            continue
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except:  # noqa: E722
                continue
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff_ts:
                recent_logs.append(log)
    
    logger.info(
        f"📊 Forecast: {len(logs)} total logs → "
        f"{len(recent_logs)} in last {days} days (since {cutoff_date.strftime('%Y-%m-%d')})"
    )
    
    # 2. Группируем по itemId, суммируем только списания (quantityChange < 0)
    consumption_by_item: dict[str, float] = defaultdict(float)
    for log in recent_logs:
        item_id = log.get("itemId", "")
        qty = log.get("quantityChange", 0)
        if item_id and qty < 0:
            consumption_by_item[item_id] += abs(qty)
    
    # 3. Загружаем все товары
    items = await get_items(limit=1000, use_cache=True)
    
    # 4. Строим прогноз
    forecast_items: List[ForecastItem] = []
    
    for item in items:
        item_id = item.get("id", "")
        stock_count = item.get("stockCount", 0)
        total_consumed = consumption_by_item.get(item_id, 0)
        
        avg_daily = total_consumed / days if days > 0 else 0
        
        # daysRemaining
        if avg_daily > 0 and stock_count > 0:
            days_remaining = stock_count / avg_daily
            # Округляем до 1 знака
            days_remaining = round(days_remaining, 1)
        elif stock_count == 0:
            days_remaining = 0.0
        else:
            # Нет данных о расходе — товар не списывали = ∞
            days_remaining = None
        
        forecast_items.append(ForecastItem(
            itemId=item_id,
            itemName=item.get("shortName", item.get("fullName", "")),
            sku=item.get("sku"),
            category=item.get("category", ""),
            imageUrl=item.get("imageUrl"),
            stockCount=stock_count,
            lowStockThreshold=item.get("lowStockThreshold", 10),
            avgDailyConsumption=round(avg_daily, 2),
            daysRemaining=days_remaining,
        ))
    
    # 5. Сортируем: сначала самые критичные (наименьший daysRemaining)
    # None (∞) — в конец
    forecast_items.sort(
        key=lambda x: (x.daysRemaining is None, x.daysRemaining if x.daysRemaining is not None else float('inf'))
    )
    
    # Кэшируем на 60 секунд
    _forecast_cache = (forecast_items, now + timedelta(seconds=60))
    logger.info(f"✅ Forecast calculated: {len(forecast_items)} items, "
                f"{sum(1 for f in forecast_items if f.daysRemaining is not None and f.daysRemaining < 3)} critical")
    
    return forecast_items