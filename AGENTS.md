# Правила и архитектурный регламент проекта «Планировщик отпусков (Швейное производство)»

## 🎯 Назначение проекта
Интеллектуальная мультиагентная система планирования отпусков для швейного производства (Республика Хакасия).
Обеспечивает сбор и согласование заявок сотрудниц через корпоративный мессенджер **MAX** (и веб-симулятор), защиту персональных данных по **152-ФЗ**, детерминированную проверку ТК РФ и производственных квот (CSP-солвер), а также интерактивный дашборд с диаграммой Ганта (Vue 3 CDN + Tailwind CSS).

---

## ⚡ Команды быстрого запуска и проверки
* **Запуск тестов (144 теста в 12 тестовых модулях, все должны быть PASS):**
  `.venv\Scripts\python.exe -m pytest -v`
* **Консольный запуск сервера (`http://127.0.0.1:8000`):**
  `.venv\Scripts\python.exe run_server.py`
* **Локальный запуск на Windows:** `Запуск_Планировщика.bat`
* **Синхронизация 15 швей из Google Таблицы (или обезличенного демо-набора):** `POST /api/employees/sync-google-sheets`

---

## 🔒 Железные бизнес-правила и требования безопасности (Strict Constraints)
1. **Норма отпуска (Хакасия):** По умолчанию **36 календарных дней** (28 основных + 8 дополнительных за климатические условия юга Сибири). Хранится в `Employee.total_vacation_days` (валидация Pydantic: `1..120`).
2. **Статья 125 ТК РФ:** Минимум одна неделимая часть отпуска в году обязана быть **$\ge 14$ календарных дней непрерывно** (`VacationSlot.is_primary_block = True`).
3. **Производственные ограничения (HARD Rules в `ScheduleRule`):**
   * Квоты должностей (`max_concurrent_roles` + `JobRole.default_quota`, `0..50`): например, не более 3 швей и не более 1 закройщика/технолога одновременно.
   * Квоты смен (`max_concurrent_shifts` + `WorkShift.default_quota`, `0..50`): лимит одновременных отпусков внутри одной смены.
   * Группы непересечения сотрудников (`incompatible_employee_groups`): взаимозаменяемые сотрудницы не могут уходить в отпуск одновременно.
   * Блэкаут-периоды (`blackout_periods`): пик пошива школьной формы (15–31 августа), сезонные коллекции, годовая инвентаризация.
4. **Безопасность API, 152-ФЗ и бота MAX:**
   * **Административная защита (`require_admin` в `backend/auth.py`):** все мутирующие эндпоинты (`POST`/`PUT`/`DELETE` сотрудников, цехов, ролей, смен, слотов, правил, админов) и выгрузки (`/api/export/csv`, `/api/export/excel`) проверяют заголовок `X-Admin-Token` или `?token=` против `ADMIN_API_KEY` (`secrets.compare_digest`). На фронтенде используется обертка `adminFetch()`.
   * **Защита вебхука MAX (`/api/chat/webhook`):**
     * Проверка секрета `WEBHOOK_SECRET` (заголовок `X-Max-Bot-Token` или `?token=`).
     * In-memory Sliding Window Rate Limiter (`check_rate_limit`): не более **10 запросов в минуту** на `user_id` или IP (`X-Forwarded-For` / `X-Real-IP`).
     * **Anti-Spoofing контактов:** привязка `max_user_id` к `Employee` или `BotAdmin` разрешена **только** через нативное вложение контакта (`contact`/`vcard`), где `contact_user_id == sender user_id`. Передача номера простым текстом или чужого контакта блокируется.
     * Доступ разрешен только номерам из таблицы `employees` со статусом `bot_access == "APPROVED"` (`PENDING` — ждет одобрения, `BLOCKED` — заблокирован). Маскирование номеров в логах через `mask_phone()`.
   * **Согласие 152-ФЗ (`Employee.consent_152fz`):** при первом диалоге в боте `IntakeAgent` запрашивает согласие на обработку ПДн (`✅ Согласна` / `❌ Отказаться`). Без `consent_152fz == True` планирование дат недоступно.
   * **Санитизация PII и формул:** перед отправкой текста в Gemini API `sanitize_prompt_pii()` удаляет телефоны и email; при выгрузке CSV/Excel `sanitize_formula_injection()` экранирует ячейки, начинающиеся с `=`, `+`, `-`, `@` (защита от CWE-1236); `FALLBACK_WORKERS` содержит только обезличенные демо-записи формата `<Роль> (<Имя> <И.>)`.
5. **Разделение NLP/LLM и CSP-Солвера:**
   * **КАТЕГОРИЧЕСКИЙ ЗАПРЕТ:** LLM никогда не считает дни, пересечения или квоты в уме.
   * **Парсер и LLM** (`nlp_date_parser.py` -> фоллбэк `llm_service.py` на `gemini-2.5-flash-lite`): только извлекают интервалы дат `(start, end)` из текста (до 500 символов) или сезонных пожеланий.
   * **CSP-Солвер** (`backend/solver/optimizer.py`): предзагружает справочники в память (`_load_rules`), математически проверяет ТК РФ, баланс дней, квоты, блэкауты и генерирует Топ-3 альтернативы.

---

## 📁 Карта кодовой базы (Codebase Map)
Подробная схема таблиц БД, все 32 REST API эндпоинта и навигация по номерам строк находятся в [ARCHITECTURE_INDEX.md](file:///d:/PyCharm_Projects/Отпуск/ARCHITECTURE_INDEX.md).

* `backend/`
  * `main.py` (80 стр.) — FastAPI `app`, middleware заголовков безопасности, `CORS_ORIGINS`, скрытие `/docs` в `production`, подключение 10 роутеров и статики `frontend/`.
  * `auth.py` (33 стр.) — Зависимость `require_admin` (`X-Admin-Token` / `?token=` против `ADMIN_API_KEY`).
  * `database.py` (73 стр.) — SQLite `vacations.db` (режим `WAL`, `synchronous=NORMAL`), `get_db()`, автомиграции `migrate_db()`.
  * `models.py` (144 стр.) — 9 ORM-моделей: `Department`, `JobRole`, `WorkShift`, `Employee` (вкл. `consent_152fz`), `BotAdmin`, `EmployeeDraft`, `ScheduleRule`, `VacationSlot`, `ChatMessage`.
  * `schemas.py` (344 стр.) — Pydantic v2 схемы с граничными валидаторами (`Field`, `field_validator`).
  * `seed_data.py` (210 стр.) — Начальное наполнение цехов, должностей, смен, правил и демо-данных.
  * `google_sheets_importer.py` (324 стр.) — Импорт из Google Sheets (`GOOGLE_SPREADSHEET_ID`) и обезличенный `FALLBACK_WORKERS`.
  * `solver/optimizer.py` (478 стр.) — `VacationOptimizer`: in-memory предзагрузка, проверка ограничений, Топ-3 альтернативы, пакетное согласование.
  * `solver/nlp_date_parser.py` (196 стр.) — Детерминированный парсер русских дат, месяцев, длительностей и интентов.
  * `agents/intake_agent.py` (568 стр.) — `IntakeAgent`: диалог 152-ФЗ, верификация телефона, накопительный черновик `EmployeeDraft`, защита от самопересечений.
  * `agents/solver_agent.py` (72 стр.) — `SolverAgent`: обертка над `VacationOptimizer` и запись слотов `commit_approved_slots`.
  * `agents/manager_agent.py` (171 стр.) — `ManagerAgent`: управление правилами, штатом и сводной статистикой `get_dashboard_summary`.
  * `services/llm_service.py` (172 стр.) — `GeminiFlashService` (`gemini-2.5-flash-lite`), `sanitize_prompt_pii`, передача ключа в `x-goog-api-key`.
  * `services/max_bot_client.py` (260 стр.) — `MaxBotClient` (`verify=True`, connection pool): отправка сообщений, inline-кнопок и запроса контакта в MAX.
  * `api/` — Роутеры FastAPI:
    * `auth_routes.py` (19 стр.), `employee_routes.py` (152 стр.), `department_routes.py` (94 стр.), `role_routes.py` (151 стр.), `shift_routes.py` (65 стр.), `vacation_routes.py` (122 стр.), `rule_routes.py` (177 стр.), `admin_routes.py` (72 стр.), `chat_routes.py` (734 стр.), `export_routes.py` (150 стр., `openpyxl` + защита от formula injection).
* `frontend/` (SPA без сборщика: Vue 3 Global CDN + Tailwind CSS CDN + Lucide Icons)
  * `index.html` (426 стр.) — Каркас приложения, шапка KPI, модальные окна (вкл. ввод ключа администратора), подключение скриптов.
  * `app.js` (563 стр.) — Корневой `createApp`, `adminFetch`, `downloadExport`, `fetchAllData()`, обработчики API.
  * `components/` — Модули вкладок (`window.<ComponentName>`):
    * `gantt-view.js` (259 стр.), `roster-view.js` (142 стр.), `dept-roles-view.js` (448 стр.), `rules-view.js` (332 стр.), `chat-view.js` (232 стр.).
* `deploy/` — `Dockerfile` (non-root `appuser`), `.dockerignore`, `docker-compose.yml` (`127.0.0.1:8000:8000`), `nginx_max.conf`, `deploy_vps.sh`.
* `tests/` — **144 теста** pytest в 12 файлах: `test_solver.py`, `test_nlp_parser.py`, `test_agents.py`, `test_api.py`, `test_auth.py`, `test_auth_stress.py`, `test_security.py`, `test_m3.py`, `test_m4.py`, `test_m5.py`, `test_adversarial_m2m3.py`, `test_adversarial_m4.py`, `test_adversarial_m4_edge.py`.

---

## 🪙 Протокол экономии токенов для ИИ-агентов (Token Optimization Protocol)
1. **Точечное чтение (`read_file` с `StartLine` и `EndLine`):**
   * Перед чтением крупных файлов (`chat_routes.py`, `intake_agent.py`, `app.js`, `optimizer.py`, `schemas.py`, `test_security.py`) загляните в раздел **Навигационный индекс строк (Line Map)** в [ARCHITECTURE_INDEX.md](file:///d:/PyCharm_Projects/Отпуск/ARCHITECTURE_INDEX.md) и читайте только нужный диапазон строк.
2. **Запрет на сканирование `.venv` в терминале:**
   * При вызове PowerShell-команд **никогда** не запускайте `Get-ChildItem -Recurse` без фильтрации пути: используйте `Get-ChildItem -Directory` или исключайте `.venv` через `Where-Object { $_.FullName -notmatch '\\\.venv\\' }`.
3. **Использование навыка разработки фич (Progressive Disclosure):**
   * Если задача связана с **добавлением новой функции** (новое правило солвера, колонка в БД, защищенный эндпоинт API, команда в MAX, вкладка во Vue 3), прочитайте пошаговый чек-лист в навыке [.agents/skills/add-feature-playbook/SKILL.md](file:///d:/PyCharm_Projects/Отпуск/.agents/skills/add-feature-playbook/SKILL.md).
4. **Единый источник истины и чистота Git:**
   * Новые колонки SQLite обязательно добавляются как в `backend/models.py`, так и в `migrate_db()` в `backend/database.py`.
   * Не оставляйте в рабочей директории неотслеживаемые `.exe`, `.db`, `.db-wal`, `.db-shm` или `.env` файлы (проверяется автотестом `test_ac62_workspace_cleanliness_git_status`).
