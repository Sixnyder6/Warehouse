# Stage 1: Build the React Frontend
FROM node:20-slim AS frontend-builder
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Build the FastAPI Backend
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies (needed for compiling cryptography if wheels aren't used)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application code and config folders
COPY app/ ./app
COPY firebase/ ./firebase

# Copy compiled frontend assets from Stage 1 builder
COPY --from=frontend-builder /build/dist ./frontend/dist

# Expose port (FastAPI runs on 8080 inside the container)
EXPOSE 8080

# Environment variables
ENV TZ=Europe/Moscow
ENV PYTHONUNBUFFERED=1

# Command to run uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]