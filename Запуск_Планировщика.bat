@echo off
chcp 65001 >nul
title График Отпусков — Швейное Производство

echo =====================================================================
echo  🧵 Планировщик отпусков швейного производства (MAX + Дашборд)
echo =====================================================================
echo.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] Виртуальное окружение .venv не найдено!
    echo Создание .venv и установка библиотек...
    python -m venv .venv
    call .venv\Scripts\pip install -r requirements.txt
)

echo [*] Запуск сервера на http://127.0.0.1:8000 ...
start /b "" ".venv\Scripts\python.exe" run_server.py

timeout /t 2 /nobreak >nul

echo [*] Открытие дашборда в браузере...
start http://127.0.0.1:8000

echo.
echo =====================================================================
echo  ✅ Сервер успешно работает!
echo  🌐 Веб-интерфейс: http://127.0.0.1:8000
echo  📚 Документация API: http://127.0.0.1:8000/docs
echo.
echo  Для завершения работы сервиса нажмите любую клавишу в этом окне...
echo =====================================================================
pause >nul

echo [*] Остановка сервера...
taskkill /f /im python.exe /fi "WINDOWTITLE eq run_server.py*" >nul 2>&1
echo [OK] Работа завершена.
