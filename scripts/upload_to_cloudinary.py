import os
import sys
import time
import hashlib
import requests
import asyncio
import logging

# Set up paths to import app modules correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import WarehouseItemUpdate
from app.services.warehouse_service import get_items, update_item

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("cloudinary_uploader")

# CLOUDINARY CREDENTIALS
CLOUD_NAME = "dcmmmfjl2"
API_KEY = "449877576177452"
API_SECRET = "Vbsb_HcviiEwTE2zs13g8GNzWqU"
UPLOAD_URL = f"https://api.cloudinary.com/v1_1/{CLOUD_NAME}/image/upload"
FOLDER = "qrscanner_parts"

IMAGE_DIR = r"C:\Users\pankr\PycharmProjects\Warehouse\app\static\images\parts"

def generate_signature(timestamp: str, folder: str) -> str:
    """Генерирует подпись SHA-1 для безопасной загрузки в Cloudinary"""
    to_sign = f"folder={folder}&timestamp={timestamp}{API_SECRET}"
    digest = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()
    return digest

def upload_image_to_cloudinary(filepath: str) -> str:
    """Загружает файл на Cloudinary и возвращает secure_url"""
    if not os.path.exists(filepath):
        logger.error(f"Файл не найден: {filepath}")
        return None

    timestamp = str(int(time.time()))
    signature = generate_signature(timestamp, FOLDER)

    filename = os.path.basename(filepath)
    
    # Подготавливаем multipart/form-data
    try:
        with open(filepath, "rb") as f:
            files = {
                "file": (filename, f, "image/png")
            }
            data = {
                "api_key": API_KEY,
                "timestamp": timestamp,
                "signature": signature,
                "folder": FOLDER
            }
            
            res = requests.post(UPLOAD_URL, files=files, data=data, timeout=30)
            
            if res.status_code == 200:
                json_data = res.json()
                secure_url = json_data.get("secure_url")
                logger.info(f"🚀 Успешно загружен на Cloudinary -> {secure_url}")
                return secure_url
            else:
                logger.error(f"❌ Сбой загрузки на Cloudinary ({res.status_code}): {res.text}")
                return None
    except Exception as e:
        logger.error(f"❌ Ошибка отправки запроса в Cloudinary: {e}")
        return None

async def upload_local_images():
    if not os.path.exists(IMAGE_DIR):
        logger.error(f"Папка с изображениями не найдена: {IMAGE_DIR}")
        return

    logger.info("📥 Получение списка всех товаров из Firestore...")
    items = []
    for attempt in range(5):
        items = await get_items(limit=1000, use_cache=False)
        if items:
            break
        logger.warning(f"⚠️ Товары не получены (возможно 429). Попытка {attempt+1}/5. Ждем перед повтором...")
        await asyncio.sleep(5.0 * (attempt + 1))
        
    if not items:
        logger.error("❌ Не удалось получить список товаров из Firestore после 5 попыток.")
        return
        
    logger.info(f"Найдено товаров в базе: {len(items)}")

    success_count = 0
    skipped_count = 0
    error_count = 0

    for item in items:
        item_id = item.get("id")
        sku = item.get("sku", "")
        if not sku:
            continue
            
        # Пропускаем, если картинка уже загружена на Cloudinary
        image_url = item.get("imageUrl") or ""
        if "cloudinary.com" in image_url:
            skipped_count += 1
            continue

        # Превращаем SKU в safe_sku для поиска локального файла
        safe_sku = sku.replace(" ", "_").replace("/", "_").replace("\\", "_")
        filename = f"{safe_sku}.png"
        filepath = os.path.join(IMAGE_DIR, filename)

        # Проверяем, есть ли у нас локальная картинка для этого SKU
        if not os.path.exists(filepath):
            skipped_count += 1
            continue

        logger.info(f"📦 Обнаружена картинка для SKU {sku}. Загрузка в Cloudinary...")
        
        # Загружаем картинку
        cloudinary_url = upload_image_to_cloudinary(filepath)
        if not cloudinary_url:
            error_count += 1
            continue

        # Обновляем imageUrl в Firestore
        update_payload = WarehouseItemUpdate(imageUrl=cloudinary_url)
        
        success = False
        msg = ""
        # 3 попытки обновления
        for attempt in range(3):
            success, msg = await update_item(item_id, update_payload)
            if success:
                break
            logger.warning(f"⚠️ Ошибка обновления ссылки в Firestore для {sku}, попытка {attempt+1}/3. Ждем...")
            await asyncio.sleep(2.0)

        if success:
            success_count += 1
            logger.info(f"✅ Обновлен URL товара [{sku}] в Firestore")
        else:
            error_count += 1
            logger.error(f"❌ Не удалось сохранить URL в Firestore для {sku}: {msg}")

        # Небольшая пауза для стабильности сетевых запросов
        await asyncio.sleep(0.2)

    logger.info("=== ЗАГРУЗКА ИЗОБРАЖЕНИЙ ЗАВЕРШЕНА ===")
    logger.info(f"Успешно загружено и обновлено: {success_count}")
    logger.info(f"Пропущено (нет локальной картинки): {skipped_count}")
    logger.info(f"Ошибок: {error_count}")

if __name__ == "__main__":
    asyncio.run(upload_local_images())
