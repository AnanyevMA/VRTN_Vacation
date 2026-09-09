#!/usr/bin/env bash
# ==============================================================================
# Скрипт автоматического развертывания сервиса Графика Отпусков на VPS
# Швейное производство (FastAPI + MAX Messenger Webhook + Uvicorn)
# ==============================================================================

set -e

echo "=== 🚀 Начало установки Планировщика отпусков на VPS ==="

# 1. Обновление пакетов и установка зависимостей
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git nginx certbot python3-certbot-nginx

# 2. Создание директории приложения
APP_DIR="/opt/vacation_planner"
echo "Создание рабочей директории $APP_DIR..."
sudo mkdir -p $APP_DIR
sudo chown -R $USER:$USER $APP_DIR

# 3. Настройка виртуального окружения Python
cd $APP_DIR
if [ ! -d ".venv" ]; then
    echo "Создание виртуального окружения .venv..."
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip
pip install fastapi "uvicorn[standard]" sqlalchemy pulp pandas openpyxl pydantic httpx pytest

# 4. Создание файла конфигурации окружения .env
if [ ! -f ".env" ]; then
    cat <<EOF > .env
# Секретный ключ Google Gemini (Бесплатный тариф: https://aistudio.google.com/)
GEMINI_API_KEY=

# Токен бота MAX Messenger (из панели управления MAX)
MAX_BOT_TOKEN=
MAX_API_URL=https://api.max.ru/bot/v1

# Порт приложения
PORT=8000
EOF
    echo "Создан файл .env. Не забудьте вписать GEMINI_API_KEY и MAX_BOT_TOKEN!"
fi

# 5. Настройка Systemd сервиса для автозапуска 24/7
echo "Настройка службы systemd (vacation-planner.service)..."
sudo bash -c "cat <<EOF > /etc/systemd/system/vacation-planner.service
[Unit]
Description=Vacation Planner FastAPI Server (Garment Factory)
After=network.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
EnvironmentFile=$APP_DIR/.env

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload
sudo systemctl enable vacation-planner
sudo systemctl restart vacation-planner

echo "=== ✅ Сервер успешно запущен как системная служба! ==="
echo "Статус службы: sudo systemctl status vacation-planner"
echo "Просмотр логов: journalctl -u vacation-planner -f"
echo "Для настройки HTTPS выполните: sudo certbot --nginx"
