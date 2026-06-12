import os
import sys
import io
import asyncio
import logging
from PIL import Image
import openpyxl

# Set up paths to import app modules correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import WarehouseItemCreate, WarehouseItemUpdate
from app.services.warehouse_service import search_items, create_item, update_item

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("excel_importer")

# CONFIGURATION
EXCEL_PATH = r"C:\Users\pankr\PycharmProjects\Warehouse\app\YGW5.0-BOM-Assembly-20260514.xlsx"
IMAGE_OUTPUT_DIR = r"C:\Users\pankr\PycharmProjects\Warehouse\app\static\images\parts"
GITHUB_USERNAME = "pankratov"  # Замените на ваше актуальное имя пользователя GitHub
GITHUB_REPO = "Warehouse"
GITHUB_IMAGE_URL_TEMPLATE = f"https://raw.githubusercontent.com/{GITHUB_USERNAME}/{GITHUB_REPO}/main/app/static/images/parts/{{sku}}.png"

DRY_RUN = False  # Установите в True, чтобы просто протестировать парсинг и сохранение картинок без отправки в Firebase

# Ensure image directory exists
os.makedirs(IMAGE_OUTPUT_DIR, exist_ok=True)

def extract_image_for_row(ws, row_1_indexed, sku):
    """
    Находит и сохраняет изображение, привязанное к строке row_1_indexed.
    Анкор строки в ws._images 0-индексирован, поэтому Row r в Excel соответствует row_1_indexed - 1.
    """
    images = getattr(ws, '_images', [])
    target_row_index = row_1_indexed - 1
    
    for img in images:
        anchor = img.anchor
        if hasattr(anchor, '_from') and anchor._from.row == target_row_index:
            # Извлекаем байты
            try:
                img_bytes = img._data()
                pil_img = Image.open(io.BytesIO(img_bytes))
                
                # Создаем имя файла на основе SKU
                safe_sku = sku.replace(" ", "_").replace("/", "_").replace("\\", "_")
                filename = f"{safe_sku}.png"
                filepath = os.path.join(IMAGE_OUTPUT_DIR, filename)
                
                # Сохраняем в формате PNG
                pil_img.save(filepath, format="PNG")
                logger.info(f"📸 Извлечена картинка для SKU {sku} -> {filename}")
                return GITHUB_IMAGE_URL_TEMPLATE.format(sku=safe_sku)
            except Exception as e:
                logger.error(f"❌ Ошибка извлечения картинки для SKU {sku}: {e}")
    return None

async def import_excel():
    if not os.path.exists(EXCEL_PATH):
        logger.error(f"Excel-файл не найден по пути: {EXCEL_PATH}")
        return

    logger.info(f"Загрузка Excel-файла: {EXCEL_PATH} ...")
    wb = openpyxl.load_workbook(EXCEL_PATH)
    logger.info("Excel загружен успешно!")

    sheets = [name for name in wb.sheetnames if name != "Catalog"]
    logger.info(f"Будет обработано листов: {len(sheets)} ({', '.join(sheets)})")

    success_count = 0
    update_count = 0
    error_count = 0

    for sheet_name in sheets:
        logger.info(f"📖 Парсинг листа: '{sheet_name}'...")
        ws = wb[sheet_name]
        max_row = ws.max_row

        r = 1
        while r <= max_row:
            cell_b = ws.cell(row=r, column=2).value
            cell_c = ws.cell(row=r, column=3).value

            if cell_b == "Package No.":
                # Нашли начало блока товара
                sku = str(cell_c).strip() if cell_c is not None else ""
                if not sku:
                    r += 1
                    continue

                # Инициализируем структуру данных
                block_data = {
                    "sku": sku,
                    "category": sheet_name,
                    "description_tech": "",
                    "name_ru": "",
                    "specs": "",
                    "price": "",
                    "size": "",
                    "weight": "",
                    "moq": "",
                    "applicable_model": ""
                }

                # Парсим 9 строк блока (от r до r+8)
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

                # Извлекаем изображение детали (оно привязано к первой строке блока `r`)
                image_url = extract_image_for_row(ws, r, sku)

                # Определяем имена
                short_name = block_data["name_ru"]
                if not short_name:
                    # Если нет перевода, берем первую часть описания
                    short_name = block_data["description_tech"].split('\n')[0] if block_data["description_tech"] else sku
                
                # Обрезаем имя если оно слишком длинное
                short_name = short_name[:100]

                # Формируем полное описание
                desc_parts = []
                if block_data["description_tech"] and block_data["description_tech"] != short_name:
                    desc_parts.append(block_data["description_tech"])
                if block_data["specs"]:
                    desc_parts.append(f"Характеристики: {block_data['specs']}")
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

                # Создаем payload
                item_payload = {
                    "fullName": full_name,
                    "shortName": short_name,
                    "sku": sku,
                    "description": full_description,
                    "category": sheet_name,
                    "unit": "шт.",
                    "stockCount": 0,
                    "totalStock": 0,
                    "lowStockThreshold": 5,
                    "imageUrl": image_url
                }

                if DRY_RUN:
                    logger.info(f"[DRY RUN] Товар SKU: {sku} | Имя: {short_name} | Категория: {sheet_name} | Картинка: {image_url}")
                    success_count += 1
                else:
                    try:
                        # Проверяем существование товара в БД по SKU
                        existing = None
                        for attempt in range(3):
                            try:
                                existing = await search_items(sku)
                                # Если получили результат (товар найден или не найден, но запрос успешен), выходим из цикла
                                # Заметьте: search_items возвращает None, если товар не найден ИЛИ если был сбой.
                                # Поэтому сделаем небольшую паузу и попробуем еще раз на случай сбоя
                                break
                            except Exception as e:
                                if attempt == 2:
                                    raise e
                                logger.warning(f"⚠️ Сбой поиска SKU {sku}, попытка {attempt+1}/3. Ждем...")
                                await asyncio.sleep(1.0)
                        
                        # Дополнительная проверка на случай сетевого сбоя: если вернулся None, 
                        # попробуем подождать 1 сек и запросить повторно, чтобы не создать дубликат по ошибке.
                        if existing is None:
                            await asyncio.sleep(0.5)
                            existing = await search_items(sku)

                        if existing:
                            item_id = existing["id"]
                            update_data = WarehouseItemUpdate(**item_payload)
                            
                            success = False
                            msg = ""
                            for attempt in range(3):
                                success, msg = await update_item(item_id, update_data)
                                if success:
                                    break
                                logger.warning(f"⚠️ Попытка обновления SKU {sku} не удалась: {msg}. Повтор {attempt+1}/3 через 2 сек...")
                                await asyncio.sleep(2.0)
                                
                            if success:
                                update_count += 1
                                logger.info(f"🔄 Обновлен товар: SKU {sku} (ID: {item_id})")
                            else:
                                error_count += 1
                                logger.error(f"❌ Ошибка обновления SKU {sku}: {msg}")
                        else:
                            create_data = WarehouseItemCreate(**item_payload)
                            
                            success = False
                            doc_id = ""
                            for attempt in range(3):
                                success, doc_id = await create_item(create_data)
                                if success:
                                    break
                                logger.warning(f"⚠️ Попытка создания SKU {sku} не удалась: {doc_id}. Повтор {attempt+1}/3 через 2 сек...")
                                await asyncio.sleep(2.0)
                                
                            if success:
                                success_count += 1
                                logger.info(f"✅ Создан новый товар: SKU {sku} (ID: {doc_id})")
                            else:
                                error_count += 1
                                logger.error(f"❌ Ошибка создания SKU {sku}: {doc_id}")
                    except Exception as ex:
                        error_count += 1
                        logger.error(f"❌ Системная ошибка импорта SKU {sku}: {ex}")

                    # Небольшая пауза между товарами для предотвращения разрыва соединения
                    await asyncio.sleep(0.15)

                # Сдвигаемся на длину блока (9 строк + 1 пустая строка spacer = 10)
                r += 10
            else:
                r += 1

    logger.info("=== ИМПОРТ ЗАВЕРШЕН ===")
    logger.info(f"Создано новых товаров: {success_count}")
    logger.info(f"Обновлено товаров: {update_count}")
    logger.info(f"Ошибок: {error_count}")

if __name__ == "__main__":
    asyncio.run(import_excel())
