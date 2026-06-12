# 🏭 Warehouse Management System

Склад запчастей «Бестужевская 10». FastAPI + Firebase Firestore + React SPA.

---

## 🚀 Быстрый запуск

### 💻 Стандартный запуск (только локальный сервер)
```powershell
# Из корневой папки проекта (C:\Users\pankr\PycharmProjects\Warehouse)

# Запустить сервер (автоматически активирует .venv)



python run_warehouse.py
```

После запуска в консоли появится:
```
============================================================
🚀 СЕРВЕР ЗАПУЩЕН
📱 Мобильный доступ: http://192.168.x.x:8080/mobile/dashboard
💻 Десктоп доступ:   http://localhost:8080/desktop/dashboard
------------------------------------------------------------
```

### 📱 Удобный мобильный запуск (с туннелем и автоподключением)
Если тестируешь с мобильного телефона и включен VPN — запусти специальный скрипт:
```powershell
python run_mobile_dev.py
```
Он сам запустит uvicorn, поднимет SSH-туннель `localhost.run`, выдаст прямую ссылку и будет следить за стабильностью, автоматически переподключаясь при обрыве.

### 🌐 Туннель вручную (в отдельном окне терминала)
```powershell
ssh -R 80:localhost:8080 nokey@localhost.run
```
Через пару секунд появится ссылка вида `https://a4502deb0b2f26.lhr.life`.  
Открой на телефоне, добавив `/mobile/login`.

---

## 🐙 Работа с репозиторием (GitHub)

Проект опубликован в приватном репозитории GitHub: [https://github.com/Sixnyder6/Warehouse.git](https://github.com/Sixnyder6/Warehouse.git).

### Как правильно отправлять изменения (Push) на GitHub:

Когда вы вносите любые изменения в код на своем компьютере и хотите сохранить их в облаке GitHub:

1. **Откройте терминал** в корневой папке проекта (`C:\Users\pankr\PycharmProjects\Warehouse`).
2. **Добавьте новые/измененные файлы** в подготовку:
   ```powershell
   git add .
   ```
3. **Зафиксируйте изменения локально**, написав понятное описание (что именно изменилось):
   ```powershell
   git commit -m "Название вашего обновления (например: Обновил экраны дашборда)"
   ```
4. **Отправьте изменения** в репозиторий:
   ```powershell
   git push
   ```

> [!WARNING]
> Файлы секретных ключей доступа (`firebase/firebase_credentials.json`), пароли в `.env` и тяжелые папки зависимостей (`.venv`, `node_modules`) автоматически исключаются через `.gitignore` и **никогда не попадут в интернет**. Не удаляйте эти строки из файла `.gitignore`!

---

## 🖥️ Фронтенд (React SPA)

React-приложение собрано в `frontend/dist/` и раздаётся FastAPI автоматически.

### Пересборка фронтенда после изменений
```powershell
# Из папки frontend/
cd frontend
npm run build
```
После сборки — перезапусти сервер (`run_warehouse.py`), изменения вступят в силу.

### Запуск фронтенда в dev-режиме (Vite HMR)
```powershell
cd frontend
npm run dev
```
Dev-сервер поднимется на `http://localhost:5173`. API-запросы проксируются на `http://localhost:8080`.

---

## 🔥 Открытие порта в брандмауэре Windows

Если сайт недоступен с телефона по IP, порт заблокирован фаерволом.

### Открыть порт 8080 (от Администратора)

```cmd
netsh advfirewall firewall add rule name="Warehouse_8080" protocol=TCP localport=8080 action=allow dir=IN
```

### Проверить правило

```cmd
netsh advfirewall firewall show rule name="Warehouse_8080"
```

### Удалить правило (если нужно)

```cmd
netsh advfirewall firewall delete rule name="Warehouse_8080"
```

### Всё равно не работает?

- Убедись, что профиль сети **Частный**, а не Публичный (`Параметры` → `Сеть и Интернет` → `Свойства`)
- Проверь, что телефон и ПК в одной сети (одна Wi-Fi точка)
- Проверь IP командой: `ipconfig | findstr "IPv4"` — адрес из `run_warehouse.py` должен совпадать

---

## 🔍 Полезные проверки

```powershell
# Кто слушает порт 8080
netstat -ano | findstr ":8080"

# Убить процесс по PID
taskkill /PID <номер> /F

# Проверить сервер локально (статус должен быть 200)
python -c "import requests; print(requests.get('http://localhost:8080/api/auth/me', timeout=5).status_code)"

# Проверить авторизацию
python -c "import requests; r = requests.get('http://localhost:8080/api/auth/me'); print(r.json())"
```

---

## 📁 Структура проекта

| Папка / Файл | Что делает |
|---|---|
| `app/main.py` | Все FastAPI роуты: login, mobile, API |
| `app/api/auth.py` | Роуты аутентификации (`/api/auth/...`) |
| `app/services/auth_service.py` | Firebase Auth + сессия пользователя |
| `app/services/warehouse_service.py` | Бизнес-логика, работа с Firestore |
| `app/models.py` | Pydantic модели |
| `app/templates/` | HTML шаблоны (мобильная версия) |
| `app/static/` | CSS, JS, иконки |
| `frontend/src/` | Исходный код React SPA |
| `frontend/dist/` | Скомпилированный React (раздаётся FastAPI) |
| `firebase/firebase_credentials.json` | 🔑 Сервисный аккаунт Firebase |
| `run_warehouse.py` | Точка входа — запуск uvicorn на порту **8080** |
| `run_mobile_dev.py` | Запуск с SSH-туннелем для мобильных |

---

## 📱 URL приложения

| Страница | URL |
|---|---|
| Вход (логин) | `http://localhost:8080/login` |
| React SPA (десктоп) | `http://localhost:8080/desktop/dashboard` |
| Мобильный дашборд | `http://localhost:8080/mobile/dashboard` |
| Мобильный логин | `http://localhost:8080/mobile/login` |
| Swagger API docs | `http://localhost:8080/docs` |
| Firebase статус | `http://localhost:8080/api/firebase/status` |
| История операций | `http://localhost:8080/api/history` |

---

## 🔐 Сессия и авторизация

Аутентификация работает через **Firebase Auth REST API**.  
После входа сервер сохраняет `user_id` в **HTTP-only cookie** (`wms_user_id`, живёт 7 дней).  
При перезапуске сервера сессия **автоматически восстанавливается** из cookie — выбрасывания на экран логина не будет.

Учётные записи — в Firestore коллекция `internal_users`.

---

## 🐛 Частые проблемы

| Проблема | Решение |
|---|---|
| Выбрасывает на логин при переключении вкладок | Устранено: сессия восстанавливается из cookie |
| 401 при входе | Неверный логин/пароль или превышена квота Firebase — подождать 5-10 мин |
| 429 Too Many Requests | Слишком много запросов к Firestore за минуту, подождать 60 сек |
| Сайт не открывается с телефона | Проверить порт в фаерволе (см. выше) |
| Фронтенд не обновился | Запустить `cd frontend && npm run build`, перезапустить сервер |
| `ModuleNotFoundError` при запуске | Активировать venv: `.\.venv\Scripts\Activate.ps1` |

## ✅ Готово. Вот итог

### Что подготовлено для деплоя:

| Файл | Что делает |
|------|-----------|
| `app/Dockerfile` | Контейнер Python 3.11 + FastAPI, порт 8080 |
| `app/docker-compose.yml` | Сервис с автоперезапуском |
| `requirements.txt` | Добавлены `requests` и `google-auth` |
| `scripts/deploy.sh` | Скрипт: билд → стоп → старт → проверка |

---

### 📋 План для деплоя (когда будешь готов)

| # | Шаг |
|---|-----|
| 1 | Купить VPS: **RuVDS (~300 ₽/мес)** или **Timeweb (~400-600 ₽/мес)** |
| 2 | Купить домен `.ru` (~250 ₽/год) |
| 3 | На VPS установить Docker: `curl -fsSL https://get.docker.com \| sh` |
| 4 | Загрузить проект на VPS (`git clone` или `scp`) |
| 5 | Положить `firebase_credentials.json` в `firebase/` |
| 6 | Запустить: `bash scripts/deploy.sh` |
| 7 | Настроить Nginx + SSL (Let's Encrypt бесплатно) |

### 💰 Цены
| Статья | ₽/мес |
|--------|------|
| VPS (RuVDS/Timeweb) | 300-600 |
| Домен `.ru` | ~21 |
| Firebase | 0 |
| SSL | 0 |
| **Итого** | **~330-630** |

Пока деплоить не надо — просто файлы готовы. Когда решишь, запускай `bash scripts/deploy.sh`.