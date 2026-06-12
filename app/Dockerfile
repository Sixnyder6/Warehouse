FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Сервисный аккаунт Firebase
COPY firebase/firebase_credentials.json /app/firebase_credentials.json

# Порт
EXPOSE 8080

# Запуск
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]