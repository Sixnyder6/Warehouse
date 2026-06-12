import socket
import subprocess
import sys
import os
import ipaddress

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

def get_all_ips():
    """Определяет все IPv4 адреса устройства, исключая loopback, Docker и некоторые виртуальные интерфейсы."""
    ips = []
    try:
        hostname = socket.gethostname()
        all_ips = socket.gethostbyname_ex(hostname)[2]
        for ip in all_ips:
            if ip not in ips:
                ips.append(ip)
    except Exception:
        pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        detected_ip = s.getsockname()[0]
        s.close()
        if detected_ip not in ips:
            ips.append(detected_ip)
    except Exception:
        pass

    valid_ips = []
    for ip in ips:
        if ip.startswith('127.'):
            continue
        if ip.startswith('169.254.'):
            continue
        if ip.startswith('172.17.') or ip.startswith('172.18.') or ip.startswith('172.19.'):
            continue
        if ip.startswith('192.168.56.') or ip.startswith('192.168.99.'):
            continue
        valid_ips.append(ip)

    def ip_priority(ip):
        if ip.startswith('192.168.'):
            return 0
        if ip.startswith('10.'):
            return 1
        if ip.startswith('172.'):
            return 2
        if ip.startswith('100.'):
            return 3
        return 4

    valid_ips.sort(key=ip_priority)

    if not valid_ips:
        valid_ips.append('127.0.0.1')

    return valid_ips


def generate_ssl_cert(cert_path: str, key_path: str, ips: list) -> bool:
    """
    Генерирует самоподписанный SSL-сертификат с SAN для всех локальных IP.
    Возвращает True если сертификат создан/уже существует, False при ошибке.
    """
    # Если уже есть — не перегенерируем
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return True

    try:
        import datetime
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        print("🔐 Генерация SSL-сертификата для HTTPS...")

        # Генерируем RSA ключ
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        # Строим список SAN (Subject Alternative Names)
        san_list = [x509.DNSName("localhost")]
        san_list.append(x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")))
        for ip in ips:
            try:
                san_list.append(x509.IPAddress(ipaddress.IPv4Address(ip)))
            except Exception:
                pass

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "Warehouse Local"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Warehouse App"),
        ])

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )

        # Сохраняем ключ
        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ))

        # Сохраняем сертификат
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        print(f"✅ SSL-сертификат создан: {cert_path}")
        return True

    except Exception as e:
        print(f"⚠️  Не удалось создать SSL-сертификат: {e}")
        return False


def run_app():
    ips = get_all_ips()
    primary_ip = ips[0]

    # ── SSL ──────────────────────────────────────────────────────────────────
    # В Docker/production с nginx — SSL_MODE=off (nginx сам делает HTTPS)
    ssl_mode = os.environ.get("SSL_MODE", "auto").lower()
    ssl_enabled = False
    cert_path = os.path.join(os.path.dirname(__file__), "ssl", "cert.pem")
    key_path  = os.path.join(os.path.dirname(__file__), "ssl", "key.pem")
    https_port = 8443

    if ssl_mode != "off":
        os.makedirs(os.path.dirname(cert_path), exist_ok=True)
        ssl_enabled = generate_ssl_cert(cert_path, key_path, ips)

    # ── Сообщение при старте ─────────────────────────────────────────────────
    print("=" * 60)
    print("🚀 СЕРВЕР ЗАПУЩЕН")
    if ssl_enabled:
        print("📱 Мобильный доступ (HTTPS — камера работает!):")
        for idx, ip in enumerate(ips):
            label = "Wi-Fi/LAN" if idx == 0 else "VPN/Alt"
            print(f"   🔒 {label}: https://{ip}:{https_port}/mobile/dashboard")
        print(f"💻 Десктоп HTTPS:  https://localhost:{https_port}/desktop/dashboard")
        print(f"💻 Десктоп HTTP:   http://localhost:8080/desktop/dashboard")
        print("-" * 60)
        print("📲 Первый раз на iPhone/Android:")
        print(f"   1. Открыть https://{primary_ip}:{https_port}/mobile/dashboard")
        print("   2. Нажать «Дополнительно» → «Всё равно перейти» (один раз)")
        print("   3. Камера-сканер заработает!")
    else:
        if len(ips) > 1:
            print("📱 Доступ с мобильного устройства:")
            for idx, ip in enumerate(ips):
                label = "Локальная сеть (Wi-Fi/LAN)" if idx == 0 else "Альтернативный / VPN"
                print(f"   🔗 {label}: http://{ip}:8080/mobile/dashboard")
        else:
            print(f"📱 Мобильный доступ: http://{ips[0]}:8080/mobile/dashboard")
        print(f"💻 Десктоп доступ:   http://localhost:8080/desktop/dashboard")
        print("-" * 60)
        print("⚠️  HTTPS отключён — камера-сканер работает только на Android.")

    print("-" * 60)
    print("💡 Если включен VPN и телефон не подключается:")
    print("   1. Разрешите доступ к локальной сети в настройках VPN (Allow LAN).")
    print("   2. Или запустите временный туннель в новом окне терминала:")
    print("      ssh -R 80:localhost:8080 nokey@localhost.run")
    print("=" * 60)

    # ── Запуск uvicorn ───────────────────────────────────────────────────────
    try:
        import uvicorn
        import threading

        if ssl_enabled:
            # Запускаем HTTPS на 8443 в фоновом потоке
            def run_https():
                uvicorn.run(
                    "app.main:app",
                    host="0.0.0.0",
                    port=https_port,
                    ssl_certfile=cert_path,
                    ssl_keyfile=key_path,
                    reload=False,  # reload не работает с SSL в потоке
                    log_level="warning",
                )

            https_thread = threading.Thread(target=run_https, daemon=True)
            https_thread.start()

        # Основной процесс — HTTP на 8080 (с reload для разработки)
        uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=True)

    except ImportError:
        cmd = [sys.executable, "-m", "uvicorn", "app.main:app",
               "--host", "0.0.0.0", "--port", "8080", "--reload"]
        subprocess.run(cmd)


if __name__ == "__main__":
    run_app()
