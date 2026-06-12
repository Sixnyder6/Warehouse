# -*- coding: utf-8 -*-
"""
🪐 Утилита автоматической настройки мобильного доступа для Warehouse OS.
Запускает локальный сервер uvicorn (если не запущен) и SSH-туннель до localhost.run,
парсит публичный адрес и выводит готовую ссылку для телефона.
При обрыве связи туннель автоматически перезапускается.
"""

import os
import sys
import time
import socket
import subprocess
import re
import threading

PORT = 8080

# Принудительно устанавливаем UTF-8 кодировку для консоли на Windows, чтобы не было UnicodeEncodeError
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Автоматический перезапуск через .venv, если скрипт запущен глобально
venv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv")
if os.path.exists(venv_path):
    venv_python = os.path.abspath(os.path.join(venv_path, "Scripts", "python.exe") if sys.platform == 'win32' else os.path.join(venv_path, "bin", "python"))
    if os.path.abspath(sys.executable) != venv_python and os.path.exists(venv_python):
        print(f"🔄 Перезапуск через виртуальное окружение: {venv_python}")
        try:
            os.execv(venv_python, [venv_python] + sys.argv)
        except Exception:
            sys.exit(subprocess.call([venv_python] + sys.argv))

def is_port_in_use(port):
    """Проверяет, занят ли порт."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def run_uvicorn():
    """Запускает локальный сервер uvicorn в фоновом режиме."""
    print("🚀 Запуск локального сервера uvicorn...")
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(PORT), "--reload"]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def run_tunnel():
    """Запускает SSH-туннель до localhost.run."""
    # StrictHostKeyChecking=no — предотвращает интерактивный запрос доверия к ключу
    # ServerAliveInterval=15 — поддерживает соединение активным
    # ExitOnForwardFailure=yes — падает быстро, если порт занят
    cmd = [
        "ssh", 
        "-o", "StrictHostKeyChecking=no", 
        "-o", "ServerAliveInterval=15", 
        "-o", "ExitOnForwardFailure=yes", 
        "-R", f"80:localhost:{PORT}", 
        "nokey@localhost.run"
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', bufsize=1)

def monitor_tunnel(proc, stop_event):
    """Считывает вывод SSH-туннеля и парсит URL."""
    url_found = False
    try:
        for line in iter(proc.stdout.readline, ''):
            if stop_event.is_set():
                break
            
            match = re.search(r'https://[a-zA-Z0-9.-]+', line)
            if match:
                url = match.group(0)
                if url != "https://localhost.run" and ('lhr' in url or 'run' in url or 'link' in url):
                    print("\n" + "=" * 70)
                    print("🎉 ТУННЕЛЬ УСПЕШНО СОЗДАН И СТАБИЛИЗИРОВАН!")
                    print(f"💻 Доступ с ПК (Десктоп): http://localhost:{PORT}/desktop/dashboard")
                    print(f"📱 Доступ с телефона (Мобильный): {url}/mobile/dashboard")
                    print(f"🔑 Страница входа на телефоне:   {url}/mobile/login")
                    print("=" * 70)
                    print("👉 Откройте последнюю ссылку на вашем телефоне для тестирования.")
                    url_found = True
            elif not url_found:
                stripped = line.strip()
                if stripped:
                    print(f"[SSH Туннель]: {stripped}")
    except Exception as e:
        pass

def main():
    print("=" * 60)
    print("🪐 WAREHOUSE OS — МОБИЛЬНЫЙ РЕЖИМ РАЗРАБОТКИ")
    print("=" * 60)

    uvicorn_proc = None
    if is_port_in_use(PORT):
        print(f"ℹ️ Порт {PORT} уже занят. Предполагаем, что uvicorn уже запущен в соседнем терминале.")
    else:
        uvicorn_proc = run_uvicorn()
        # Дадим серверу 2 секунды на запуск
        time.sleep(2)

    stop_event = threading.Event()
    
    try:
        while True:
            print("🔗 Подключение к localhost.run...")
            tunnel_proc = run_tunnel()
            
            # Запускаем отслеживание вывода туннеля в отдельном потоке
            monitor_thread = threading.Thread(target=monitor_tunnel, args=(tunnel_proc, stop_event))
            monitor_thread.daemon = True
            monitor_thread.start()
            
            # Ждем пока туннель работает
            while tunnel_proc.poll() is None:
                time.sleep(1)
            
            # Если туннель упал
            print("⚠️ Соединение с туннелем закрыто. Перезапуск через 3 секунды...")
            tunnel_proc.terminate()
            time.sleep(3)
            
    except KeyboardInterrupt:
        print("\n👋 Завершение работы мобильной среды разработки...")
        stop_event.set()
        if uvicorn_proc:
            print("🛑 Остановка uvicorn...")
            uvicorn_proc.terminate()
            try:
                uvicorn_proc.wait(timeout=3)
            except:
                uvicorn_proc.kill()
        print("Готово. Вы вышли.")

if __name__ == "__main__":
    main()
