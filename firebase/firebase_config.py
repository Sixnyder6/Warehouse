import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

# Путь к твоему google-services.json (ключ из Android Studio)
CRED_PATH = os.path.join(os.path.dirname(__file__), "google-services.json")

# Загружаем конфиг из файла
with open(CRED_PATH, 'r') as f:
    android_config = json.load(f)

# Берем данные для Web SDK
firebase_config = {
    "apiKey": android_config['client'][0]['api_key'][0]['current_key'],
    "authDomain": f"{android_config['project_info']['project_id']}.firebaseapp.com",
    "projectId": android_config['project_info']['project_id'],
    "storageBucket": android_config['project_info']['storage_bucket'],
    "messagingSenderId": android_config['project_info']['project_number'],
    "appId": android_config['client'][0]['client_info']['mobilesdk_app_id']
}

# Инициализация Firebase Admin SDK (для бэкенда)
# Для Admin SDK нужен service account, но для чтения данных из Firestore подойдет и Web конфиг
if not firebase_admin._apps:
    # Используем credentials из Web конфига
    cred = credentials.Certificate(CRED_PATH)  # Это не сработает для google-services.json
    # Альтернатива: используем firestore напрямую через REST API

# Временное решение - будем использовать REST API
import requests


class FirestoreClient:
    def __init__(self, config):
        self.config = config
        self.base_url = f"https://firestore.googleapis.com/v1/projects/{config['projectId']}/databases/(default)/documents"

    def get_collection(self, collection_name):
        """Получить все документы из коллекции"""
        url = f"{self.base_url}/{collection_name}"
        params = {"key": self.config['apiKey']}

        try:
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                documents = []
                for doc in data.get('documents', []):
                    doc_id = doc['name'].split('/')[-1]
                    fields = doc.get('fields', {})
                    documents.append({
                        'id': doc_id,
                        **self._convert_fields(fields)
                    })
                return documents
            else:
                print(f"Error: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            print(f"Exception: {e}")
            return []

    def _convert_fields(self, fields):
        """Конвертирует Firestore поля в Python типы"""
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
            else:
                result[key] = str(value)
        return result


# Создаем клиента
db = FirestoreClient(firebase_config)