import sqlite3
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any

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
