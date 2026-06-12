#!/bin/bash
# ═══════════════════════════════════════════════
# 🚀 Деплой Warehouse Management System на VPS
# ═══════════════════════════════════════════════

set -e

echo "╔════════════════════════════════════════╗"
echo "║  🚀 ДЕПЛОЙ WAREHOUSE MANAGEMENT SYSTEM ║"
echo "╚════════════════════════════════════════╝"

# ── Цвета ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ── Проверка Docker ──
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker не установлен!${NC}"
    echo "Установи Docker: curl -fsSL https://get.docker.com | sh"
    exit 1
fi

if ! command -v docker compose &> /dev/null; then
    echo -e "${RED}❌ Docker Compose не установлен!${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Docker найден${NC}"

# ── Переход в корень проекта ──
cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)
echo "📁 Корень проекта: $PROJECT_ROOT"

# ── Проверка firebase_credentials.json ──
if [ ! -f "firebase/firebase_credentials.json" ]; then
    echo -e "${RED}❌ Не найден firebase/firebase_credentials.json!${NC}"
    echo "Помести файл сервисного аккаунта Firebase в firebase/firebase_credentials.json"
    exit 1
fi
echo -e "${GREEN}✅ Firebase credentials найдены${NC}"

# ── Сборка образа ──
echo ""
echo "🛠 Сборка Docker образа..."
docker compose -f app/docker-compose.yml build

# ── Остановка старого контейнера ──
echo ""
echo "🛑 Остановка старого контейнера..."
docker compose -f app/docker-compose.yml down || true

# ── Запуск ──
echo ""
echo "🚀 Запуск контейнера..."
docker compose -f app/docker-compose.yml up -d

# ── Проверка ──
echo ""
echo "⏳ Ожидание запуска..."
sleep 3
if docker ps | grep -q warehouse; then
    echo -e "${GREEN}✅ Контейнер запущен!${NC}"
    echo ""
    echo "╔════════════════════════════════════════╗"
    echo "║  📍 СЕРВЕР ЗАПУЩЕН                     ║"
    echo "║  http://localhost:8080                  ║"
    echo "║  http://<IP_СЕРВЕРА>:8080              ║"
    echo "║                                         ║"
    echo "║  📋 Страницы:                           ║"
    echo "║  /login           — Вход                ║"
    echo "║  /desktop/dashboard — Дашборд           ║"
    echo "║  /mobile/login    — Мобильный вход      ║"
    echo "║  /docs            — Swagger API         ║"
    echo "╚════════════════════════════════════════╝"

    # ── Логи ──
    echo ""
    echo "📋 Последние логи:"
    docker logs warehouse --tail 10
else
    echo -e "${RED}❌ Контейнер не запустился!${NC}"
    echo "Логи:"
    docker logs warehouse 2>&1 || true
    exit 1
fi