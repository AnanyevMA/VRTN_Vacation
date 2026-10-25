#!/usr/bin/env bash
# ==============================================================================
# Скрипт развертывания сервиса Графика Отпусков на VPS 46.149.79.201
# Прямая синхронизация с GitHub: https://github.com/AnanyevMA/VRTN_Vacation
# Безопасное соседство с WB FBS (порт 8005, подпуть /vacation/, SSL Let's Encrypt)
# Ультра-низкое потребление ресурсов (~40 МБ ОЗУ, лимит MemoryMax=192M)
# Автоматическая регистрация HTTPS-вебхука MAX и проверка логов systemd/Nginx
# ==============================================================================

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/AnanyevMA/VRTN_Vacation.git}"
BRANCH="${BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/vacation_planner}"
SERVICE_NAME="vacation-planner"
APP_PORT=8005
SSL_DOMAIN="46.149.79.201.sslip.io"
RUN_USER="${SUDO_USER:-$USER}"

echo "=== 🚀 Развертывание Планировщика отпусков из GitHub ($REPO_URL [$BRANCH]) ==="

# 1. Установка базовых пакетов Python, Git и curl
echo "[1/7] Проверка системных пакетов (python3, venv, git, curl)..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv git curl

# 2. Подготовка рабочей директории и синхронизация кода напрямую с GitHub
echo "[2/7] Подготовка рабочей директории $APP_DIR и загрузка кода с GitHub..."
sudo mkdir -p "$APP_DIR"
mkdir -p "$APP_DIR/data"
sudo chown -R "$RUN_USER:$RUN_USER" "$APP_DIR"

cd "$APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
    echo "Инициализация Git-репозитория и клонирование ветки $BRANCH..."
    git init -q
    git remote add origin "$REPO_URL" 2>/dev/null || git remote set-url origin "$REPO_URL"
    git fetch --depth 1 origin "$BRANCH"
    git checkout -f -B "$BRANCH" "origin/$BRANCH"
else
    echo "Обновление существующего репозитория до последнего коммита origin/$BRANCH..."
    git remote set-url origin "$REPO_URL"
    git fetch --depth 1 origin "$BRANCH"
    git reset --hard "origin/$BRANCH"
fi

echo "Текущий коммит: $(git log -1 --oneline)"

# 3. Виртуальное окружение и установка зависимостей
echo "[3/7] Настройка Python .venv и установка зависимостей..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q --no-cache-dir -r requirements.txt

# 4. Создание файла конфигурации окружения .env (если отсутствует)
echo "[4/7] Проверка конфигурации .env..."
if [ ! -f ".env" ]; then
    GENERATED_ADMIN_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
    GENERATED_WEBHOOK_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
    cat <<EOF > .env
# Простая модель Google Gemini (Бесплатный тариф: https://aistudio.google.com/)
GEMINI_API_KEY=
GEMINI_MODEL=gemini-flash-lite-latest

# Токен бота MAX Messenger
MAX_BOT_TOKEN=
MAX_API_URL=https://platform-api.max.ru
WEBHOOK_SECRET=${GENERATED_WEBHOOK_SECRET}

# Защита административных API (X-Admin-Token)
ADMIN_API_KEY=${GENERATED_ADMIN_KEY}

# ID Google Таблицы для синхронизации (опционально)
GOOGLE_SPREADSHEET_ID=

# Окружение и CORS
ENVIRONMENT=production
CORS_ORIGINS=http://46.149.79.201,https://46.149.79.201,https://${SSL_DOMAIN},http://${SSL_DOMAIN}

# Внутренний порт и префикс для совместной работы с WB FBS на 46.149.79.201
HOST=127.0.0.1
PORT=${APP_PORT}
ROOT_PATH=/vacation
DATABASE_URL=sqlite:///$APP_DIR/data/vacations.db
EOF
    echo "Создан новый файл .env со сгенерированными ключами ADMIN_API_KEY и WEBHOOK_SECRET."
fi
chmod 600 "$APP_DIR/.env"

# Разрешаем доступ к порту 8005 из внутренних сетей Docker (для reverse-proxy контейнера wbfbs_nginx)
if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q "Status: active"; then
    sudo ufw allow from 172.16.0.0/12 to any port ${APP_PORT} proto tcp comment 'Vacation Planner from Docker Nginx' >/dev/null 2>&1 || true
fi

# 5. Настройка Systemd сервиса с жесткими ограничениями памяти, CPU и песочницей (Linux Namespaces)
echo "[5/7] Настройка службы systemd (${SERVICE_NAME}.service)..."
sudo bash -c "cat <<EOF > /etc/systemd/system/${SERVICE_NAME}.service
[Unit]
Description=Vacation Planner FastAPI Server (Garment Factory - Low Resource)
After=network.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
Environment=DATABASE_URL=sqlite:///$APP_DIR/data/vacations.db
ExecStart=$APP_DIR/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port ${APP_PORT} --root-path /vacation --workers 1 --limit-concurrency 50 --timeout-keep-alive 5 --no-access-log
Restart=always
RestartSec=5
MemoryAccounting=true
MemoryHigh=160M
MemoryMax=192M
CPUAccounting=true
CPUQuota=50%

# Linux Namespaces & Process Sandboxing Hardening
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true
ReadWritePaths=$APP_DIR/data $APP_DIR

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

# 6. Автоматическая интеграция с Nginx (SSL Let's Encrypt + контейнер wbfbs_nginx + авторегистрация вебхука MAX)
echo "[6/7] Проверка маршрутизации Nginx (/vacation/) и SSL (${SSL_DOMAIN})..."
WBFBS_NGINX_CONF="/PROJECTS/WB_FBS_VRTN/wb-fbs/nginx/conf.d/app.conf"
SSL_CERT_FILE="/PROJECTS/WB_FBS_VRTN/wb-fbs/certbot/conf/live/${SSL_DOMAIN}/fullchain.pem"

if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -q '^wbfbs_nginx$' && [ -f "$WBFBS_NGINX_CONF" ]; then
    if [ ! -f "$SSL_CERT_FILE" ] && docker ps --format '{{.Names}}' | grep -q '^wbfbs_certbot$'; then
        echo "Выпуск бесплатного SSL-сертификата Let's Encrypt для ${SSL_DOMAIN}..."
        docker exec wbfbs_certbot certbot certonly --webroot -w /var/www/certbot -d "${SSL_DOMAIN}" --register-unsafely-without-email --agree-tos --non-interactive || true
    fi

    cat << 'PYEOF' > "$APP_DIR/deploy/ensure_nginx.py"
import sys, pathlib, subprocess

conf_path = pathlib.Path("/PROJECTS/WB_FBS_VRTN/wb-fbs/nginx/conf.d/app.conf")
if not conf_path.exists():
    sys.exit(0)

content = conf_path.read_text(encoding="utf-8")
changed = False

cert_file = pathlib.Path("/PROJECTS/WB_FBS_VRTN/wb-fbs/certbot/conf/live/46.149.79.201.sslip.io/fullchain.pem")
if cert_file.exists() and "listen 443 ssl;" not in content:
    ssl_block = """    listen 80;
    listen 443 ssl;
    http2 on;
    ssl_certificate /etc/letsencrypt/live/46.149.79.201.sslip.io/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/46.149.79.201.sslip.io/privkey.pem;"""
    content = content.replace("    listen 80;", ssl_block, 1)
    changed = True

try:
    gw_ip = subprocess.check_output(
        ["docker", "inspect", "wbfbs_nginx", "--format", "{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}"],
        text=True
    ).strip().splitlines()[0] or "172.20.0.1"
except Exception:
    gw_ip = "172.20.0.1"
port = "8005"

miniapp_block = f"""    location /vacation/miniapp {{
        proxy_pass http://{gw_ip}:{port}/miniapp;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_hide_header X-Frame-Options;
        add_header Content-Security-Policy "frame-ancestors 'self' https://*.max.ru https://max.ru https://*.oneme.ru" always;
        add_header X-Content-Type-Options "nosniff" always;
    }}

"""

if "location /vacation/" not in content:
    vacation_block = f"""
    # ==========================================================
    # СЕРВИС ПЛАНИРОВАНИЯ ОТПУСКОВ (Изолированный подпуть /vacation/)
    # ==========================================================
    location = /vacation {{
        return 301 /vacation/;
    }}

    location ~ ^/vacation/(docs|redoc|openapi\\.json) {{
        return 403;
    }}

    location /vacation/api/chat/webhook {{
        proxy_pass http://{gw_ip}:{port}/api/chat/webhook;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
        proxy_connect_timeout 10s;
    }}

{miniapp_block}    location /vacation/ {{
        proxy_pass http://{gw_ip}:{port}/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 60s;
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
        add_header X-XSS-Protection "1; mode=block" always;
    }}
"""
    idx = content.rfind("}")
    if idx != -1:
        content = content[:idx] + vacation_block + "\n}\n"
        changed = True
elif "location /vacation/miniapp" not in content:
    content = content.replace("    location /vacation/ {", miniapp_block + "    location /vacation/ {", 1)
    changed = True

if changed:
    conf_path.write_text(content, encoding="utf-8")
    subprocess.run(["docker", "exec", "wbfbs_nginx", "nginx", "-t"], check=True)
    subprocess.run(["docker", "exec", "wbfbs_nginx", "nginx", "-s", "reload"], check=True)
PYEOF

    python3 "$APP_DIR/deploy/ensure_nginx.py"
    docker exec wbfbs_nginx nginx -t
    docker exec wbfbs_nginx nginx -s reload

    # Авто-восстановление блока /vacation/ + SSL, если соседний деплой WB FBS перезапишет app.conf
    sudo bash -c "cat <<EOF > /etc/systemd/system/vacation-nginx-sync.service
[Unit]
Description=Restore Vacation Planner Nginx block if app.conf is overwritten

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 $APP_DIR/deploy/ensure_nginx.py
EOF"

    sudo bash -c "cat <<EOF > /etc/systemd/system/vacation-nginx-sync.path
[Unit]
Description=Watch WB FBS Nginx app.conf for overwrites

[Path]
PathChanged=$WBFBS_NGINX_CONF

[Install]
WantedBy=multi-user.target
EOF"

    sudo systemctl daemon-reload
    sudo systemctl enable --now vacation-nginx-sync.path

    if [ -f "$SSL_CERT_FILE" ]; then
        "$APP_DIR/.venv/bin/python3" - "$APP_DIR" "$SSL_DOMAIN" <<'PYWH'
import sys, pathlib
app_dir = sys.argv[1]
ssl_domain = sys.argv[2]
sys.path.insert(0, app_dir)
env = dict(l.split("=", 1) for l in pathlib.Path(f"{app_dir}/.env").read_text().splitlines() if "=" in l and not l.startswith("#"))
bot_token = env.get("MAX_BOT_TOKEN", "").strip()
wh_secret = env.get("WEBHOOK_SECRET", "").strip()
api_url = env.get("MAX_API_URL", "https://platform-api.max.ru").strip() or "https://platform-api.max.ru"
if bot_token and wh_secret:
    from backend.services.max_bot_client import MaxBotClient
    client = MaxBotClient(token=bot_token, base_url=api_url)
    wh_url = f"https://{ssl_domain}/vacation/api/chat/webhook?token={wh_secret}"
    ok = client.register_webhook(wh_url)
    print(f"MAX Webhook registered (https://{ssl_domain}/vacation/api/chat/webhook?token=<REDACTED>): {ok}")
PYWH
    fi
    echo "Конфигурация контейнера wbfbs_nginx и HTTPS вебхука успешно проверена."
fi

# 7. Проверка здоровья сервиса (Healthcheck) и анализ логов
echo "[7/7] Проверка работоспособности сервиса и анализ логов..."
HTTP_OK=0
for i in $(seq 1 15); do
    if curl -fsS "http://127.0.0.1:${APP_PORT}/api/export/stats" >/dev/null 2>&1; then
        HTTP_OK=1
        break
    fi
    sleep 1
done

echo "--- Статус службы systemd ---"
sudo systemctl status "${SERVICE_NAME}" --no-pager -l | head -n 20

echo "--- Последние 30 строк логов systemd (journalctl) ---"
LOGS=$(sudo journalctl -u "${SERVICE_NAME}" -n 30 --no-pager)
echo "$LOGS"

if [ "$HTTP_OK" -ne 1 ]; then
    echo "❌ ОШИБКА: Сервис не ответил на http://127.0.0.1:${APP_PORT}/api/export/stats за 15 секунд!"
    exit 1
fi

if echo "$LOGS" | grep -Eqi "Traceback|CRITICAL|SyntaxError|ImportError"; then
    echo "⚠️ ВНИМАНИЕ: В логах обнаружены ошибки выполнения!"
    exit 1
fi

STATS_JSON=$(curl -fsS "http://127.0.0.1:${APP_PORT}/api/export/stats")
echo "--- Ответ внутреннего API (/api/export/stats) ---"
echo "$STATS_JSON"

if curl -fsS "https://${SSL_DOMAIN}/vacation/api/export/stats" >/dev/null 2>&1; then
    echo "--- Ответ внешнего HTTPS Nginx (https://${SSL_DOMAIN}/vacation/api/export/stats) ---"
    curl -fsS "https://${SSL_DOMAIN}/vacation/api/export/stats"
    echo ""
fi

echo "=== ✅ Развертывание успешно завершено! ==="
echo "HTTP Дашборд:  http://46.149.79.201/vacation/"
echo "HTTPS Дашборд: https://${SSL_DOMAIN}/vacation/"
