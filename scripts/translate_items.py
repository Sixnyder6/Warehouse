import os
import sys
import io
import asyncio
import logging
import urllib.parse
import requests
import re

# Set up paths to import app modules correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import WarehouseItemUpdate
from app.services.warehouse_service import get_items, update_item

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("translation_service")

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

def has_chinese(text):
    if not text:
        return False
    return bool(CHINESE_REGEX.search(text))

def translate_text(text, sl='zh-CN', tl='ru'):
    if not text:
        return ""
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={sl}&tl={tl}&dt=t&q={urllib.parse.quote(text)}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            translated = "".join(part[0] for part in data[0] if part[0])
            return translated
    except Exception as e:
        logger.error(f"❌ Ошибка перевода для '{text[:30]}...': {e}")
    return text

async def translate_database():
    logger.info("📥 Получение списка всех товаров из Firestore...")
    items = await get_items(limit=1000, use_cache=False)
    logger.info(f"Найдено товаров в базе: {len(items)}")

    translated_count = 0
    skipped_count = 0
    error_count = 0

    for i, item in enumerate(items):
        item_id = item.get("id")
        sku = item.get("sku", "")
        old_short_name = item.get("shortName", "")
        old_full_name = item.get("fullName", "")
        old_desc = item.get("description", "")
        old_category = item.get("category", "")

        needs_update = False
        updates = {}

        # 1. Перевод категории
        new_category = CATEGORY_TRANSLATION.get(old_category)
        if new_category and new_category != old_category:
            updates["category"] = new_category
            needs_update = True
            logger.info(f"🏷️ Замена категории для {sku}: '{old_category}' -> '{new_category}'")

        # 2. Перевод shortName (если есть китайские иероглифы)
        if has_chinese(old_short_name):
            new_short_name = translate_text(old_short_name)
            if new_short_name and new_short_name != old_short_name:
                # Ограничиваем длину
                new_short_name = new_short_name[:100].strip()
                updates["shortName"] = new_short_name
                # Также перестраиваем fullName
                updates["fullName"] = f"{new_short_name} ({sku})"
                needs_update = True
                logger.info(f"📝 Перевод shortName [{sku}]: '{old_short_name}' -> '{new_short_name}'")
        
        # 3. Перевод fullName (если иероглифы остались, а shortName не менялся)
        elif has_chinese(old_full_name) and "fullName" not in updates:
            # Rebuild based on current shortName
            clean_short = old_short_name.strip()
            updates["fullName"] = f"{clean_short} ({sku})"
            needs_update = True
            logger.info(f"📝 Обновлен fullName [{sku}]: '{old_full_name}' -> '{updates['fullName']}'")

        # 4. Перевод description (если есть китайские иероглифы)
        if has_chinese(old_desc):
            new_desc = translate_text(old_desc)
            if new_desc and new_desc != old_desc:
                updates["description"] = new_desc
                needs_update = True
                logger.info(f"📖 Перевод описания для [{sku}]...")

        if needs_update:
            # Запускаем обновление с повторными попытками
            success = False
            msg = ""
            update_payload = WarehouseItemUpdate(**updates)
            
            for attempt in range(3):
                success, msg = await update_item(item_id, update_payload)
                if success:
                    break
                logger.warning(f"⚠️ Ошибка обновления при переводе SKU {sku}, попытка {attempt+1}/3. Ждем...")
                await asyncio.sleep(2.0)

            if success:
                translated_count += 1
            else:
                error_count += 1
                logger.error(f"❌ Не удалось обновить переведенный товар {sku}: {msg}")
        else:
            skipped_count += 1

        # Небольшая пауза между товарами для стабильности
        await asyncio.sleep(0.15)

    logger.info("=== ПЕРЕВОД БАЗЫ ДАННЫХ ЗАВЕРШЕН ===")
    logger.info(f"Переведено и обновлено товаров: {translated_count}")
    logger.info(f"Пропущено (уже на русском): {skipped_count}")
    logger.info(f"Ошибок обновления: {error_count}")

if __name__ == "__main__":
    asyncio.run(translate_database())
