import os
import io
import time
import hashlib
import urllib.parse
import re
import asyncio
import logging
from typing import Dict, Any, List
import httpx
from PIL import Image
import openpyxl

import random
from app.models import WarehouseItemCreate, WarehouseItemUpdate
from app.services.warehouse_service import search_items, create_item, update_item, get_items

# Set up logging
logger = logging.getLogger("excel_web_importer")

# CLOUDINARY CREDENTIALS
CLOUD_NAME = "dcmmmfjl2"
API_KEY = "449877576177452"
API_SECRET = "Vbsb_HcviiEwTE2zs13g8GNzWqU"
UPLOAD_URL = f"https://api.cloudinary.com/v1_1/{CLOUD_NAME}/image/upload"
FOLDER = "qrscanner_parts"

# Map of English sheet names to premium Russian categories
CATEGORY_TRANSLATION = {
    "Main pole assembly": "Рулевая стойка в сборе",
    "Frame assembly": "Рама в сборе",
    "Front number plate set": "Комплект переднего номера",
    "Phoner holder": "Держатель телефона",
    "Front hub assembly": "Переднее колесо / Ступица",
    "Rear curved deck assembly": "Заднее крыло / Крыло в сборе",
    "Motor assembly": "Мотор-колесо в сборе",
    "ECU assembly": "Блок управления (ECU) в сборе",
    "Batttery": "Аккумуляторная батарея",
    "Battery lid assembly": "Крышка батарейного отсека",
    "Kickstand": "Подножка",
    "Charger": "Зарядное устройство",
    "Tools": "Специальный инструмент",
    "IOT": "Модуль IOT (телеметрия)"
}

CHINESE_REGEX = re.compile(r"[\u4e00-\u9fff]")

# Глобальный словарь для отслеживания статуса фоновых импортов
import_tasks: Dict[str, Dict[str, Any]] = {}

def has_chinese(text: str) -> bool:
    if not text:
        return False
    return bool(CHINESE_REGEX.search(text))

async def translate_text(text: str, sl: str = 'zh-CN', tl: str = 'ru') -> str:
    if not text:
        return ""
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={sl}&tl={tl}&dt=t&q={urllib.parse.quote(text)}"
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=10.0)
        if res.status_code == 200:
            data = res.json()
            translated = "".join(part[0] for part in data[0] if part[0])
            return translated
    except Exception as e:
        logger.error(f"Error translating: {e}")
    return text

async def upload_image_bytes_to_cloudinary(img_bytes: bytes, filename: str) -> str:
    """Загружает картинку из памяти в Cloudinary"""
    try:
        timestamp = str(int(time.time()))
        to_sign = f"folder={FOLDER}&timestamp={timestamp}{API_SECRET}"
        signature = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()
        
        files = {
            "file": (filename, img_bytes, "image/png")
        }
        data = {
            "api_key": API_KEY,
            "timestamp": timestamp,
            "signature": signature,
            "folder": FOLDER
        }
        async with httpx.AsyncClient() as client:
            res = await client.post(UPLOAD_URL, files=files, data=data, timeout=30.0)
        if res.status_code == 200:
            return res.json().get("secure_url")
        else:
            logger.error(f"Cloudinary upload failed ({res.status_code}): {res.text}")
    except Exception as e:
        logger.error(f"Exception during Cloudinary upload: {e}")
    return None

def extract_image_for_row_in_memory(ws, row_1_indexed) -> bytes:
    """Находит картинку для строки в Excel-листе и возвращает ее бинарные данные"""
    images = getattr(ws, '_images', [])
    target_row_index = row_1_indexed - 1
    
    for img in images:
        anchor = img.anchor
        if hasattr(anchor, '_from') and anchor._from.row == target_row_index:
            try:
                return img._data()
            except Exception as e:
                logger.error(f"Error reading image data: {e}")
    return None

def add_task_log(task_id: str, msg: str):
    """Добавляет строку лога для задачи"""
    timestamp = datetime_now_str()
    log_line = f"[{timestamp}] {msg}"
    if task_id in import_tasks:
        import_tasks[task_id]["logs"].append(log_line)
        # Ограничиваем историю логов 300 строками для экономии памяти
        if len(import_tasks[task_id]["logs"]) > 300:
            import_tasks[task_id]["logs"].pop(0)
    logger.info(f"Task {task_id}: {msg}")

def datetime_now_str() -> str:
    return time.strftime("%H:%M:%S")

def get_backoff_delay(attempt: int, base_delay: float = 1.0, max_delay: float = 15.0) -> float:
    """Вычисляет задержку экспоненциального отката со случайным джиттером"""
    factor = 2 ** attempt
    delay = base_delay * factor + random.uniform(0.1, 0.5)
    return min(delay, max_delay)

async def run_excel_import(file_bytes: bytes, task_id: str):
    """Основная фоновая функция выполнения импорта"""
    import_tasks[task_id] = {
        "status": "RUNNING",
        "progress": 0,
        "status_text": "Чтение Excel файла...",
        "created_count": 0,
        "updated_count": 0,
        "error_count": 0,
        "logs": []
    }
    
    add_task_log(task_id, "Инициализация импорта Excel BOM...")
    
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes))
        add_task_log(task_id, "Файл Excel успешно загружен в память.")
        
        sheets = [name for name in wb.sheetnames if name != "Catalog"]
        add_task_log(task_id, f"Обнаружено листов для обработки: {len(sheets)} ({', '.join(sheets)})")
        
        # 1. Предварительный подсчет количества деталей для точного прогресс-бара
        add_task_log(task_id, "Сканирование структуры файла...")
        total_items = 0
        for sheet_name in sheets:
            ws = wb[sheet_name]
            for r in range(1, ws.max_row + 1):
                if ws.cell(row=r, column=2).value == "Package No.":
                    total_items += 1
                    
        add_task_log(task_id, f"Найдено спецификаций товаров для импорта: {total_items}")
        if total_items == 0:
            import_tasks[task_id]["status"] = "COMPLETED"
            import_tasks[task_id]["progress"] = 100
            import_tasks[task_id]["status_text"] = "Завершено. Нет деталей для импорта."
            add_task_log(task_id, "В файле не найдено строк со спецификациями деталей.")
            return

        # Предварительная загрузка каталога во избежание N+1 запросов поиска
        import_tasks[task_id]["status_text"] = "Загрузка существующего каталога из базы..."
        add_task_log(task_id, "Загрузка существующего каталога товаров из базы данных...")
        
        existing_items = {}
        try:
            items_list = await get_items(limit=10000, use_cache=False)
            for item in items_list:
                sku_val = item.get("sku")
                if sku_val:
                    existing_items[str(sku_val).strip()] = item
            add_task_log(task_id, f"Каталог успешно загружен: {len(existing_items)} активных деталей в базе.")
        except Exception as e:
            add_task_log(task_id, f"⚠️ Не удалось загрузить каталог из базы на старте: {e}. Поиск будет происходить построчно с сетевыми запросами.")

        # 2. Обработка деталей
        processed_items = 0
        
        for sheet_name in sheets:
            ws = wb[sheet_name]
            max_row = ws.max_row
            
            # Переводим категорию
            category_ru = CATEGORY_TRANSLATION.get(sheet_name, sheet_name)
            add_task_log(task_id, f"Начало обработки категории: \"{category_ru}\" (Лист: {sheet_name})")
            
            r = 1
            while r <= max_row:
                cell_b = ws.cell(row=r, column=2).value
                cell_c = ws.cell(row=r, column=3).value
                
                if cell_b == "Package No.":
                    sku = str(cell_c).strip() if cell_c is not None else ""
                    if not sku:
                        r += 1
                        continue
                    
                    block_data = {
                        "sku": sku,
                        "description_tech": "",
                        "name_ru": "",
                        "specs": "",
                        "price": "",
                        "size": "",
                        "weight": "",
                        "moq": "",
                        "applicable_model": ""
                    }
                    
                    # Парсим 9 строк блока
                    for offset in range(9):
                        check_row = r + offset
                        if check_row > max_row:
                            break
                        lbl = ws.cell(row=check_row, column=2).value
                        val = ws.cell(row=check_row, column=3).value
                        
                        lbl_str = str(lbl).strip() if lbl is not None else ""
                        val_str = str(val).strip() if val is not None else ""
                        
                        if offset == 0:
                            continue
                        elif offset == 1:
                            block_data["description_tech"] = val_str
                        elif offset == 2 and lbl_str == "":
                            block_data["name_ru"] = val_str
                        else:
                            lbl_lower = lbl_str.lower()
                            if "spec" in lbl_lower:
                                block_data["specs"] = val_str
                            elif "price" in lbl_lower:
                                block_data["price"] = val_str
                            elif "size" in lbl_lower:
                                block_data["size"] = val_str
                            elif "weight" in lbl_lower:
                                block_data["weight"] = val_str
                            elif "moq" in lbl_lower:
                                block_data["moq"] = val_str
                            elif "model" in lbl_lower:
                                block_data["applicable_model"] = val_str
                            elif lbl_str == "" and not block_data["name_ru"]:
                                block_data["name_ru"] = val_str
                    
                    processed_items += 1
                    progress_pct = int((processed_items / total_items) * 100)
                    import_tasks[task_id]["progress"] = progress_pct
                    import_tasks[task_id]["status_text"] = f"Обработка {processed_items}/{total_items}: SKU {sku}..."
                    
                    # а. Выполняем русификацию полей
                    short_name = block_data["name_ru"]
                    if not short_name:
                        short_name = block_data["description_tech"].split('\n')[0] if block_data["description_tech"] else sku
                    
                    # Перевод short_name (китайский -> русский)
                    if has_chinese(short_name):
                        translated_name = await translate_text(short_name)
                        if translated_name:
                            short_name = translated_name.strip()
                    
                    short_name = short_name[:100]
                    
                    # Перевод технического описания
                    desc_tech = block_data["description_tech"]
                    if has_chinese(desc_tech):
                        translated_desc = await translate_text(desc_tech)
                        if translated_desc:
                            desc_tech = translated_desc.strip()
                            
                    # б. Компонуем полное русское описание
                    desc_parts = []
                    if desc_tech and desc_tech != short_name:
                        desc_parts.append(desc_tech)
                    if block_data["specs"]:
                        translated_specs = await translate_text(block_data["specs"]) if has_chinese(block_data["specs"]) else block_data["specs"]
                        desc_parts.append(f"Характеристики: {translated_specs}")
                    if block_data["size"]:
                        desc_parts.append(f"Размер упаковки: {block_data['size']}")
                    if block_data["weight"]:
                        desc_parts.append(f"Вес: {block_data['weight']} кг")
                    if block_data["moq"]:
                        desc_parts.append(f"MOQ: {block_data['moq']} шт")
                    if block_data["applicable_model"]:
                        desc_parts.append(f"Применимо для: {block_data['applicable_model']}")
                    if block_data["price"]:
                        desc_parts.append(f"Цена детали: {block_data['price']} USD")
                        
                    full_description = "\n".join(desc_parts)
                    full_name = f"{short_name} ({sku})"
                    
                    # в. Извлечение изображения и загрузка в Cloudinary
                    image_url = None
                    img_bytes = extract_image_for_row_in_memory(ws, r)
                    if img_bytes:
                        safe_sku = sku.replace(" ", "_").replace("/", "_").replace("\\", "_")
                        filename = f"{safe_sku}.png"
                        add_task_log(task_id, f"☁️ SKU {sku}: Загрузка картинки в Cloudinary...")
                        
                        # Делаем попытки загрузки в Cloudinary
                        cloudinary_url = None
                        for upload_attempt in range(3):
                            cloudinary_url = await upload_image_bytes_to_cloudinary(img_bytes, filename)
                            if cloudinary_url:
                                break
                            add_task_log(task_id, f"⚠️ Попытка загрузки картинки {upload_attempt+1}/3 не удалась. Повтор...")
                            await asyncio.sleep(get_backoff_delay(upload_attempt))
                            
                        if cloudinary_url:
                            image_url = cloudinary_url
                            add_task_log(task_id, f"🚀 Картинка для SKU {sku} загружена: {cloudinary_url}")
                        else:
                            add_task_log(task_id, f"❌ Не удалось загрузить картинку для SKU {sku} в Cloudinary.")
                    
                    # г. Сохранение в Firestore
                    item_payload = {
                        "fullName": full_name,
                        "shortName": short_name,
                        "sku": sku,
                        "description": full_description,
                        "category": category_ru,
                        "unit": "шт.",
                        "stockCount": 0,
                        "totalStock": 0,
                        "lowStockThreshold": 5
                    }
                    if image_url:
                        item_payload["imageUrl"] = image_url
                        
                    # Поиск существующего товара в локальном кэше или по сети
                    existing = None
                    sku_stripped = sku.strip()
                    if existing_items:
                        existing = existing_items.get(sku_stripped)
                    else:
                        for search_attempt in range(3):
                            try:
                                existing = await search_items(sku)
                                break
                            except Exception as e:
                                if search_attempt == 2:
                                    raise e
                                add_task_log(task_id, f"⚠️ Попытка поиска SKU {sku} {search_attempt+1}/3 не удалась: {e}")
                                await asyncio.sleep(get_backoff_delay(search_attempt))
                    
                    # Логика пропуска идентичных товаров (возобновление работы с места остановки)
                    if existing:
                        existing_url = existing.get("imageUrl") or ""
                        payload_url = item_payload.get("imageUrl") or ""
                        
                        is_same = (
                            existing.get("fullName") == full_name and
                            existing.get("shortName") == short_name and
                            existing.get("category") == category_ru and
                            existing.get("description") == full_description and
                            existing_url == payload_url
                        )
                        if is_same:
                            # Пропускаем, так как товар совпадает с импортированным
                            import_tasks[task_id]["updated_count"] += 1
                            processed_items += 1
                            progress_pct = int((processed_items / total_items) * 100)
                            import_tasks[task_id]["progress"] = progress_pct
                            import_tasks[task_id]["status_text"] = f"Обработка {processed_items}/{total_items}: SKU {sku} (уже импортирован, пропуск)..."
                            
                            # Небольшая пауза для разгрузки процессора
                            await asyncio.sleep(0.01)
                            r += 10
                            continue

                    try:
                        if existing:
                            item_id = existing["id"]
                            # Если у существующего товара уже есть картинка, а в этой строке Excel картинки нет - сохраняем старую ссылку
                            if "imageUrl" not in item_payload and existing.get("imageUrl"):
                                item_payload["imageUrl"] = existing["imageUrl"]
                                
                            update_data = WarehouseItemUpdate(**item_payload)
                            
                            success = False
                            msg = ""
                            for update_attempt in range(3):
                                success, msg = await update_item(item_id, update_data)
                                if success:
                                    break
                                add_task_log(task_id, f"⚠️ Попытка Firestore update SKU {sku} {update_attempt+1}/3 не удалась: {msg}")
                                await asyncio.sleep(get_backoff_delay(update_attempt))
                                
                            if success:
                                import_tasks[task_id]["updated_count"] += 1
                                add_task_log(task_id, f"✅ Обновлен товар: SKU {sku} [{short_name}]")
                                if existing_items:
                                    existing_items[sku_stripped] = {**existing, **item_payload}
                            else:
                                raise Exception(f"Не удалось обновить товар в базе: {msg}")
                        else:
                            create_data = WarehouseItemCreate(**item_payload)
                            
                            success = False
                            doc_id = ""
                            for create_attempt in range(3):
                                success, doc_id = await create_item(create_data)
                                if success:
                                    break
                                add_task_log(task_id, f"⚠️ Попытка Firestore create SKU {sku} {create_attempt+1}/3 не удалась: {doc_id}")
                                await asyncio.sleep(get_backoff_delay(create_attempt))
                                
                            if success:
                                import_tasks[task_id]["created_count"] += 1
                                add_task_log(task_id, f"✨ Создан новый товар: SKU {sku} (ID: {doc_id})")
                                if existing_items:
                                    new_item = {**item_payload, "id": doc_id}
                                    existing_items[sku_stripped] = new_item
                            else:
                                raise Exception(f"Не удалось создать новый товар в базе: {doc_id}")
                                
                    except Exception as fe:
                        # Логируем ошибку и останавливаем импорт, чтобы пользователь мог исправить / перезапустить
                        import_tasks[task_id]["error_count"] += 1
                        error_msg = f"Ошибка базы данных для SKU {sku}: {fe}"
                        add_task_log(task_id, f"❌ {error_msg}")
                        raise fe
                        
                    # Небольшая пауза для стабильности сети
                    await asyncio.sleep(0.15)
                    
                    r += 10
                else:
                    r += 1
                    
        import_tasks[task_id]["status"] = "COMPLETED"
        import_tasks[task_id]["progress"] = 100
        import_tasks[task_id]["status_text"] = "Импорт успешно завершен!"
        add_task_log(task_id, f"=== ИМПОРТ ЗАВЕРШЕН ===")
        add_task_log(task_id, f"Добавлено новых товаров: {import_tasks[task_id]['created_count']}")
        add_task_log(task_id, f"Обновлено товаров: {import_tasks[task_id]['updated_count']}")
        add_task_log(task_id, f"Ошибок: {import_tasks[task_id]['error_count']}")
        
    except Exception as ex:
        import_tasks[task_id]["status"] = "FAILED"
        import_tasks[task_id]["status_text"] = f"Ошибка импорта: {str(ex)}"
        add_task_log(task_id, f"❌ Смертельная ошибка импорта Excel: {ex}")
