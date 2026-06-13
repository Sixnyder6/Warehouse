import sqlite3
import os
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Путь к файлу БД телеметрии в корне проекта
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "firebase_telemetry.db"
)

def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # WAL-режим для ускорения записи и безопасного параллельного чтения
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wms_cache (
                key TEXT PRIMARY KEY,
                value TEXT,
                expires_at DATETIME
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS firestore_operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_type TEXT, -- 'READ', 'WRITE', 'DELETE'
                collection TEXT,
                count INTEGER DEFAULT 1,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                latency_ms INTEGER DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cache_telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT, -- 'HIT', 'MISS'
                count INTEGER DEFAULT 1,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Попробуем добавить колонку latency_ms в firestore_operations, если её нет
        try:
            cursor.execute("ALTER TABLE firestore_operations ADD COLUMN latency_ms INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error initializing telemetry DB: {e}")

# Инициализируем при загрузке модуля
init_db()

def log_operation(op_type: str, collection: str, count: int = 1, latency_ms: int = 0):
    """
    Записывает операцию Firestore в локальную базу данных SQLite.
    op_type: 'READ', 'WRITE', 'DELETE'
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO firestore_operations (operation_type, collection, count, latency_ms) VALUES (?, ?, ?, ?)",
            (op_type.upper(), collection, count, latency_ms)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error logging telemetry: {e}")

def log_cache(event_type: str, count: int = 1):
    """
    Записывает кэш-хит или мисс в локальную базу данных.
    event_type: 'HIT', 'MISS'
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO cache_telemetry (event_type, count) VALUES (?, ?)",
            (event_type.upper(), count)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error logging cache telemetry: {e}")

def get_telemetry_summary_24h() -> Dict[str, Any]:
    """
    Возвращает суммарные данные по операциям за последние 24 часа.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Получаем общую сумму по операциям за последние 24 часа
        cursor.execute("""
            SELECT operation_type, SUM(count) 
            FROM firestore_operations 
            WHERE timestamp >= datetime('now', '-24 hours')
            GROUP BY operation_type
        """)
        rows = cursor.fetchall()
        summary = {"READ": 0, "WRITE": 0, "DELETE": 0}
        for op, cnt in rows:
            if op in summary:
                summary[op] = cnt or 0
        
        # Получаем среднее время отклика (ping) за последний час
        cursor.execute("""
            SELECT AVG(latency_ms) 
            FROM firestore_operations 
            WHERE timestamp >= datetime('now', '-1 hour') AND latency_ms > 0
        """)
        avg_latency = cursor.fetchone()[0] or 0
        
        # Если за последний час не было запросов, берем за последние 24 часа
        if not avg_latency:
            cursor.execute("""
                SELECT AVG(latency_ms) 
                FROM firestore_operations 
                WHERE timestamp >= datetime('now', '-24 hours') AND latency_ms > 0
            """)
            avg_latency = cursor.fetchone()[0] or 0
            
        # Получаем статистику по кэшу (hits vs misses) за 24 часа
        cursor.execute("""
            SELECT event_type, SUM(count)
            FROM cache_telemetry
            WHERE timestamp >= datetime('now', '-24 hours')
            GROUP BY event_type
        """)
        cache_rows = cursor.fetchall()
        cache_stats = {"HIT": 0, "MISS": 0}
        for ev, cnt in cache_rows:
            if ev in cache_stats:
                cache_stats[ev] = cnt or 0
        total_cache = cache_stats["HIT"] + cache_stats["MISS"]
        cache_hit_rate = (cache_stats["HIT"] / total_cache * 100) if total_cache > 0 else 100.0

        # Получаем данные почасово за последние 24 часа для графика
        now = datetime.now()
        hours_labels = []
        hourly_reads = [0] * 24
        hourly_writes = [0] * 24
        hourly_deletes = [0] * 24
        
        # Заполняем метки часов (например, "14:00") назад во времени на 24 часа
        for i in range(23, -1, -1):
            h_time = now - timedelta(hours=i)
            hours_labels.append(h_time.strftime("%H:00"))
            
        # Запрос к БД с группировкой по часам
        cursor.execute("""
            SELECT 
                strftime('%H:00', datetime(timestamp, 'localtime')) as hour_str,
                operation_type,
                SUM(count)
            FROM firestore_operations
            WHERE timestamp >= datetime('now', '-24 hours')
            GROUP BY hour_str, operation_type
        """)
        hourly_rows = cursor.fetchall()
        
        # Сопоставляем с часами в метках
        for hour_str, op, cnt in hourly_rows:
            if hour_str in hours_labels:
                idx = hours_labels.index(hour_str)
                if op == "READ":
                    hourly_reads[idx] = cnt
                elif op == "WRITE":
                    hourly_writes[idx] = cnt
                elif op == "DELETE":
                    hourly_deletes[idx] = cnt
                
        conn.close()
        return {
            "summary": summary,
            "chart": {
                "labels": hours_labels,
                "reads": hourly_reads,
                "writes": hourly_writes,
                "deletes": hourly_deletes
            },
            "metrics": {
                "avg_latency": round(avg_latency),
                "cache_hit_rate": round(cache_hit_rate, 1),
                "cache_hits": cache_stats["HIT"],
                "cache_misses": cache_stats["MISS"]
            }
        }
    except Exception as e:
        logger.error(f"Error reading telemetry: {e}")
        return {
            "summary": {"READ": 0, "WRITE": 0, "DELETE": 0},
            "chart": {"labels": [], "reads": [], "writes": [], "deletes": []},
            "metrics": {
                "avg_latency": 0,
                "cache_hit_rate": 100.0,
                "cache_hits": 0,
                "cache_misses": 0
            }
        }

_budget_status = {"exceeded": False, "last_check": 0}

def is_read_budget_exceeded(max_daily_reads: int = 40000) -> bool:
    """
    Проверяет, превышен ли суточный бюджет на операции чтения Firestore.
    Кэширует статус на 10 секунд во избежание частых обращений к локальной БД.
    """
    import time
    now = time.time()
    if now - _budget_status["last_check"] < 10:
        return _budget_status["exceeded"]

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT SUM(count) 
            FROM firestore_operations 
            WHERE operation_type = 'READ' AND date(timestamp) = date('now')
        """)
        row = cursor.fetchone()
        total_reads = row[0] or 0
        conn.close()
        
        exceeded = total_reads >= max_daily_reads
        _budget_status["exceeded"] = exceeded
        _budget_status["last_check"] = now
        
        if exceeded:
            logger.critical(f"🚨 Query Guard ACTIVE: Firestore read budget exceeded ({total_reads}/{max_daily_reads})!")
        return exceeded
    except Exception as e:
        logger.error(f"Error checking read budget: {e}")
        return _budget_status["exceeded"]


def get_cached_value(key: str) -> Optional[Any]:
    """
    Возвращает значение из SQLite-кэша, если оно существует и не истекло.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value, expires_at FROM wms_cache WHERE key = ?",
            (key,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            value_str, expires_at_str = row
            # expires_at_str в формате YYYY-MM-DD HH:MM:SS (UTC)
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            
            if datetime.now(timezone.utc) < expires_at:
                try:
                    return json.loads(value_str)
                except Exception as je:
                    logger.error(f"Error parsing cached JSON for {key}: {je}")
                    return None
            else:
                # Удаляем просроченный кэш
                clear_cached_value(key)
        return None
    except Exception as e:
        logger.error(f"Error reading sqlite cache for {key}: {e}")
        return None

def set_cached_value(key: str, value: Any, ttl_seconds: int = 600):
    """
    Записывает сериализованное в JSON значение в SQLite-кэш с заданным TTL.
    """
    try:
        value_str = json.dumps(value, default=str)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        expires_at_str = expires_at.isoformat().replace("+00:00", "Z")
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO wms_cache (key, value, expires_at) VALUES (?, ?, ?)",
            (key, value_str, expires_at_str)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error writing sqlite cache for {key}: {e}")

def clear_cached_value(key: str):
    """
    Удаляет ключ из SQLite-кэша.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM wms_cache WHERE key = ?", (key,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error clearing sqlite cache for {key}: {e}")

def clear_sqlite_logs_cache():
    """
    Удаляет все ключи кэша логов, новостей и статистики из SQLite.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM wms_cache WHERE key LIKE 'warehouse_logs_%' OR key LIKE 'news_%' OR key = 'today_activity_stats'")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error clearing sqlite logs/news cache: {e}")

def update_user_last_seen_in_cache(user_id: str, last_seen: int):
    """
    Точечно обновляет поле lastSeen у пользователя во всех списках пользователей в SQLite-кэше.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM wms_cache WHERE key LIKE 'internal_users_%'")
        rows = cursor.fetchall()
        for key, value_str in rows:
            try:
                users = json.loads(value_str)
                updated = False
                for u in users:
                    if u.get("id") == user_id:
                        u["lastSeen"] = last_seen
                        updated = True
                if updated:
                    cursor.execute(
                        "UPDATE wms_cache SET value = ? WHERE key = ?",
                        (json.dumps(users, default=str), key)
                    )
            except Exception as je:
                logger.error(f"Error updating user lastSeen in cache key {key}: {je}")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error updating user lastSeen in sqlite cache: {e}")


def update_item_in_sqlite_cache(item_id: str, updates: dict):
    """
    Точечно обновляет поля товара во всех списках товаров, кэшированных в SQLite.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Находим все ключи кэша товаров
        cursor.execute("SELECT key, value FROM wms_cache WHERE key LIKE 'warehouse_items_limit_%'")
        rows = cursor.fetchall()
        
        for key, value_str in rows:
            try:
                items = json.loads(value_str)
                updated = False
                for item in items:
                    if item.get("id") == item_id:
                        for k, v in updates.items():
                            item[k] = v
                        # Также обновим время обновления товара для синхронизации
                        item["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                        updated = True
                
                if updated:
                    cursor.execute(
                        "UPDATE wms_cache SET value = ? WHERE key = ?",
                        (json.dumps(items, default=str), key)
                    )
            except Exception as je:
                logger.error(f"Error updating item {item_id} in cache key {key}: {je}")
                
        # Также очистим индивидуальный кэш товара, если он есть
        cursor.execute("DELETE FROM wms_cache WHERE key = ?", (f"warehouse_item_{item_id}",))
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error performing incremental sqlite cache update for item {item_id}: {e}")

def add_item_to_sqlite_cache(item: dict):
    """
    Добавляет новый товар во все кэшированные списки товаров в SQLite.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT key, value FROM wms_cache WHERE key LIKE 'warehouse_items_limit_%'")
        rows = cursor.fetchall()
        
        # Убедимся, что updatedAt в формате ISO строки
        if isinstance(item.get("updatedAt"), datetime):
            item["updatedAt"] = item["updatedAt"].isoformat().replace("+00:00", "Z")
            
        for key, value_str in rows:
            try:
                items = json.loads(value_str)
                # Проверим, нет ли уже такого товара
                if not any(i.get("id") == item.get("id") for i in items):
                    items.append(item)
                    cursor.execute(
                        "UPDATE wms_cache SET value = ? WHERE key = ?",
                        (json.dumps(items, default=str), key)
                    )
            except Exception as je:
                logger.error(f"Error adding item to cache key {key}: {je}")
                
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error adding item to sqlite cache: {e}")

def delete_item_from_sqlite_cache(item_id: str):
    """
    Помечает товар как удаленный или удаляет его из всех кэшированных списков товаров.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT key, value FROM wms_cache WHERE key LIKE 'warehouse_items_limit_%'")
        rows = cursor.fetchall()
        
        for key, value_str in rows:
            try:
                items = json.loads(value_str)
                updated = False
                
                # Если ключ кэша включает удаленные, помечаем isDeleted=True, иначе физически удаляем из списка
                include_deleted = "True" in key
                
                new_items = []
                for item in items:
                    if item.get("id") == item_id:
                        if include_deleted:
                            item["isDeleted"] = True
                            item["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                            new_items.append(item)
                        updated = True
                    else:
                        new_items.append(item)
                
                if updated:
                    cursor.execute(
                        "UPDATE wms_cache SET value = ? WHERE key = ?",
                        (json.dumps(new_items, default=str), key)
                    )
            except Exception as je:
                logger.error(f"Error deleting item {item_id} from cache key {key}: {je}")
                
        # Очистим индивидуальный кэш товара
        cursor.execute("DELETE FROM wms_cache WHERE key = ?", (f"warehouse_item_{item_id}",))
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error deleting item from sqlite cache: {e}")

