"""Проверка пользователей в Firebase через Admin SDK"""
import json
import os
import firebase_admin
from firebase_admin import credentials, firestore

cred_path = os.path.join('firebase', 'firebase_credentials.json')
cred = credentials.Certificate(cred_path)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# 1. Получим ВСЕХ пользователей
print('=== ВСЕ ПОЛЬЗОВАТЕЛИ В internal_users ===')
users = db.collection('internal_users').stream()
count = 0
for user in users:
    count += 1
    data = user.to_dict()
    print(f'\n--- Пользователь {count} ---')
    print(f'ID: {user.id}')
    print(f'  username: {data.get("username", "N/A")}')
    print(f'  displayName: {data.get("displayName", "N/A")}')
    print(f'  password: {data.get("password", "N/A")}')
    print(f'  role: {data.get("role", "N/A")}')
    print(f'  isAllowedToWork: {data.get("isAllowedToWork", "N/A")}')
    print(f'  status: {data.get("status", "N/A")}')

if count == 0:
    print('НЕТ ПОЛЬЗОВАТЕЛЕЙ!')
else:
    print(f'\nВсего пользователей: {count}')

# 2. Проверим какие коллекции есть
print('\n=== ДОСТУПНЫЕ КОЛЛЕКЦИИ ===')
collections = db.collections()
print([col.id for col in collections])