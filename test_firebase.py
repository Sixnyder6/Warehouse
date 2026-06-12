"""Тест Firebase REST API с OAuth2"""
import json
import os
import requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request as AuthRequest

# Загружаем сервисный аккаунт
import os
for _proxy_env_var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_proxy_env_var, None)

cred_path = os.path.join('firebase', 'firebase_credentials.json')
with open(cred_path) as f:
    cred_data = json.load(f)

# Создаем credentials
creds = service_account.Credentials.from_service_account_info(
    cred_data,
    scopes=['https://www.googleapis.com/auth/datastore']
)

# Получаем токен
session = requests.Session()
session.trust_env = False
session.proxies = {}
auth_req = AuthRequest(session=session)
creds.refresh(auth_req)
token = creds.token
print(f"Token OK: {token[:30]}...")
print(f"Project: {cred_data['project_id']}")
print()

project_id = cred_data['project_id']
base_url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents"
headers = {
    'Authorization': f'Bearer {token}',
    'Content-Type': 'application/json',
}

# 1. Сначала просто получим все документы из internal_users
url_list = f"{base_url}/internal_users"
print("=== 1. Получение всех документов internal_users ===")
r = session.get(url_list, headers=headers, timeout=10)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    docs = data.get('documents', [])
    print(f"Найдено документов: {len(docs)}")
    for doc in docs:
        doc_id = doc['name'].split('/')[-1]
        fields = doc.get('fields', {})
        print(f"\nID: {doc_id}")
        print(f"  username: {fields.get('username', {}).get('stringValue', 'N/A')}")
        print(f"  displayName: {fields.get('displayName', {}).get('stringValue', 'N/A')}")
        print(f"  password: {fields.get('password', {}).get('stringValue', 'N/A')[:20]}...")
        print(f"  role: {fields.get('role', {}).get('stringValue', 'N/A')}")
else:
    print(f"Error: {r.text[:500]}")

# 2. Query по username=admin
print("\n=== 2. Query: username = admin ===")
query_url = f"{base_url}:runQuery"
query = {
    "structuredQuery": {
        "from": [{"collectionId": "internal_users"}],
        "where": {
            "fieldFilter": {
                "field": {"fieldPath": "username"},
                "op": "EQUAL",
                "value": {"stringValue": "admin"}
            }
        },
        "limit": 10
    }
}
r = session.post(query_url, json=query, headers=headers, timeout=10)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    results = r.json()
    print(f"Results count: {len(results)}")
    for item in results:
        if 'document' in item:
            doc = item['document']
            doc_id = doc['name'].split('/')[-1]
            print(f"Found user: {doc_id}")
            print(f"  Fields: {json.dumps(doc.get('fields', {}), indent=2)}")
        elif 'readTime' in item:
            print(f"  (no document, just readTime)")
else:
    print(f"Error: {r.text[:500]}")

# 3. Попробуем query по username=test или другим
print("\n=== 3. Все коллекции ===")
r = session.get(f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents", headers=headers, timeout=10)
print(f"List collections Status: {r.status_code}")
if r.status_code == 200:
    print(f"Collections: {json.dumps(r.json(), indent=2)[:500]}")