# Правила и архитектурный регламент проекта «Планировщик отпусков (Швейное производство)»

## 🎯 Назначение проекта
Интеллектуальная мультиагентная система планирования отпусков для швейного производства (Республика Хакасия, бренд **VRTN workshop**).
Обеспечивает сбор и согласование заявок сотрудниц через корпоративный мессенджер **MAX** (чат-бот `@id190207495060_bot` + встроенное **MAX Mini App** + веб-симулятор), защиту персональных данных по **152-ФЗ**, детерминированную проверку ТК РФ и производственных квот (CSP-солвер), а также интерактивный дашборд с диаграммой Ганта (Vue 3 CDN + Tailwind CSS).

---

## 🌐 Боевая инфраструктура (GitHub и VPS)
* **GitHub-репозиторий:** `https://github.com/AnanyevMA/VRTN_Vacation.git` (ветка `main`).
* **Боевой сервер (VPS):** `46.149.79.201` (SSH-алиас `vps`, рабочая папка `/opt/vacation_planner`, база данных `/opt/vacation_planner/data/vacations.db`).
* **Служба systemd:** `vacation-planner.service` (Uvicorn на `0.0.0.0:8005` с `--root-path /vacation`).
* **Проксирование Nginx и SSL:**
  * Работает через Docker-контейнер `wbfbs_nginx` (`/PROJECTS/WB_FBS_VRTN/wb-fbs/nginx/conf.d/app.conf`) с Let's Encrypt SSL для домена `46.149.79.201.sslip.io`.
  * Автоматический вотчер `vacation-nginx-sync.path` (`/opt/vacation_planner/deploy/ensure_nginx.py`) восстанавливает блок `/vacation/` и SSL, если соседний проект перезапишет `app.conf`.
* **Боевые URL-адреса:**
  * **Веб-дашборд руководителя (HTTPS):** `https://46.149.79.201.sslip.io/vacation/` (HTTP: `http://46.149.79.201/vacation/`)
  * **Мини-приложение MAX (WebApp):** `https://46.149.79.201.sslip.io/vacation/miniapp`
  * **Вебхук бота MAX (`VRTN отпуск`):** `https://46.149.79.201.sslip.io/vacation/api/chat/webhook?token=<WEBHOOK_SECRET>`

---

## ⚡ Команды быстрого запуска, проверки и деплоя
* **Запуск тестов локально (все тесты должны быть PASS):**
  `.venv\Scripts\python.exe -m pytest -v`
* **Консольный запуск локального сервера (`http://127.0.0.1:8000`):**
  `.venv\Scripts\python.exe run_server.py`
* **Локальный запуск на Windows:** `Запуск_Планировщика.bat`
* **Развертывание на VPS напрямую из GitHub (с автопроверкой логов и healthcheck):**
  `ssh vps "curl -fsSL https://raw.githubusercontent.com/AnanyevMA/VRTN_Vacation/main/deploy/deploy_vps.sh | bash"`
* **Чтение логов на VPS:**
  * Служба FastAPI: `ssh vps "journalctl -u vacation-planner.service -n 50 --no-pager"`
  * Контейнер Nginx: `ssh vps "docker logs wbfbs_nginx --tail 50"` *(НИКОГДА не используйте `docker exec wbfbs_nginx cat/grep /var/log/nginx/access.log`, так как лог слинкован в `/dev/stdout` и команда зависнет).*

---

## 🔒 Железные бизнес-правила и требования безопасности (Strict Constraints)
1. **Защита рабочей БД от демо-данных в продакшене:**
   * При `ENVIRONMENT=production` (или `AUTO_SEED_DEMO=false`) функция `seed_database()` при старте/перезапуске сервера **не вызывается** — запускается только `ensure_minimal_rules_if_empty()`. Запрещено перезаписывать или подтягивать дефолтных демо-сотрудников/смены при обновлении сервера.
2. **Норма отпуска (Хакасия):** По умолчанию **36 календарных дней** (28 основных + 8 дополнительных за климатические условия юга Сибири). Хранится в `Employee.total_vacation_days` (валидация Pydantic: `1..120`).
3. **Статья 125 ТК РФ:** Минимум одна неделимая часть отпуска в году обязана быть **$\ge 14$ календарных дней непрерывно** (`VacationSlot.is_primary_block = True`).
4. **Производственные ограничения (HARD Rules в `ScheduleRule`):**
   * Квоты должностей (`max_concurrent_roles` + `JobRole.default_quota`, `0..50`): например, не более 3 швей и не более 1 закройщика/технолога одновременно.
   * Квоты смен (`max_concurrent_shifts` + `WorkShift.default_quota`, `0..50`): лимит одновременных отпусков внутри одной смены.
   * Группы непересечения сотрудников (`incompatible_employee_groups`): взаимозаменяемые сотрудницы (от 2 и более человек) не могут уходить в отпуск одновременно.
   * Персональные запреты пересечения 1-на-1 (`personal_incompatible_pairs`): индивидуальные пары напарниц/сменщиц («Кто с кем не может пересекаться»), которым запрещено пересекаться по датам отпуска.
   * Блэкаут-периоды (`blackout_periods`): пик пошива школьной формы (15–31 августа), сезонные коллекции, годовая инвентаризация.
5. **Безопасность API, 152-ФЗ, бота MAX и Mini App:**
   * **Административная защита (`require_admin` в `backend/auth.py`):** все эндпоинты дашборда, включая чтение (сотрудники, цеха, роли, смены, слоты, правила, админы, выгрузки, веб-симулятор чата), кроме `/api/miniapp/*`, `/api/chat/webhook*` и `/api/auth/verify_phone`, проверяют заголовок `X-Admin-Token` или `?token=` против `ADMIN_API_KEY` (`secrets.compare_digest`). На фронтенде используется обертка `adminFetch()`.
   * **Мини-приложение MAX (`/vacation/miniapp` и `/api/miniapp/*`):**
     * Отдает упрощенный ролевой интерфейс:
       * `👤 Мой отпуск` (баланс с учетом уже утвержденных `APPROVED` слотов, памятка персональных напарниц `my_restrictions`, согласие 152-ФЗ, выбор дат с мгновенной предпроверкой через CSP-солвер, применение альтернатив в 1 клик `/api/miniapp/draft/select-alternative`, прямое редактирование периодов в черновике `✏️ Изменить` `/api/miniapp/draft/update` и возврат еще не утвержденных заявок обратно в черновик `✏️ Изменить даты` `/api/miniapp/slots/recall`).
       * `📅 Кто когда в отпуске` (общий график предприятия без телефонов по 152-ФЗ с быстрым переключателем `Моя смена` / `Мой цех` / `Вся фабрика`).
       * `👑 Руководитель` (для `BotAdmin` или по `X-Admin-Token`: KPI, показ причины конфликта, согласование/отклонение заявок в 1 клик с push-уведомлением в MAX, пакетное авто-согласование и сворачиваемый блок управления доступом к боту).
     * Маршруты `/miniapp` и `/miniapp/` обязаны поддерживать методы `GET` и `HEAD`, отдавать `Content-Security-Policy: frame-ancestors *` (с `proxy_hide_header Content-Security-Policy` в Nginx) и **не** отдавать `X-Frame-Options` (чтобы открываться внутри Electron/WebView клиентов MAX), тогда как все остальные маршруты отдают `X-Frame-Options: SAMEORIGIN`.
     * **Запрет внешних зарубежных CDN для фронтенда:** библиотеки **Vue 3**, **Tailwind CSS** и **Lucide Icons** обязательно раздаются локально из `frontend/vendor/` (`/vacation/static/vendor/...`), чтобы исключить блокировки `unpkg.com` в браузерах и WebView на территории РФ.
   * **Защита вебхука MAX (`/api/chat/webhook`):**
     * Проверка секрета `WEBHOOK_SECRET` (заголовок `X-Max-Bot-Token` или `?token=`).
     * In-memory Sliding Window Rate Limiter (`check_rate_limit`): не более **10 запросов в минуту** на `user_id` или IP (`X-Forwarded-For` / `X-Real-IP`).
     * **Anti-Spoofing контактов:** привязка `max_user_id` к `Employee` или `BotAdmin` разрешена **только** через нативное вложение контакта (`contact`/`vcard`), где `contact_user_id == sender user_id`. Передача номера простым текстом или чужого контакта блокируется.
     * Доступ разрешен только номерам из таблицы `employees` со статусом `bot_access == "APPROVED"` (`PENDING` — ждет одобрения, `BLOCKED` — заблокирован). Маскирование номеров в логах через `mask_phone()`.
   * **Согласие 152-ФЗ (`Employee.consent_152fz`):** при первом диалоге в боте `IntakeAgent` запрашивает согласие на обработку ПДн (`✅ Согласна` / `❌ Отказаться`). Без `consent_152fz == True` планирование дат недоступно.
   * **Санитизация PII и формул:** перед отправкой текста в Gemini API `sanitize_prompt_pii()` удаляет телефоны и email; при выгрузке CSV/Excel `sanitize_formula_injection()` экранирует ячейки, начинающиеся с `=`, `+`, `-`, `@` (защита от CWE-1236); `FALLBACK_WORKERS` содержит только обезличенные демо-записи формата `<Роль> (<Имя> <И.>)`.
6. **Разделение NLP/LLM и CSP-Солвера:**
   * **КАТЕГОРИЧЕСКИЙ ЗАПРЕТ:** LLM никогда не считает дни, пересечения или квоты в уме.
   * **Парсер и LLM** (`nlp_date_parser.py` -> фоллбэк `llm_service.py` на `gemini-flash-lite-latest` с резервом `gemini-3.5-flash-lite` / `gemini-3.1-flash-lite`): только извлекают интервалы дат `(start, end)` из текста (до 500 символов) или сезонных пожеланий.
   * **CSP-Солвер** (`backend/solver/optimizer.py`): предзагружает справочники в память (`_load_rules`), математически проверяет ТК РФ, баланс дней, квоты, блэкауты и генерирует Топ-3 альтернативы.

---

## 📁 Карта кодовой базы (Codebase Map)
Подробная схема таблиц БД, все 46 REST API эндпоинтов и навигация по номерам строк находятся в [ARCHITECTURE_INDEX.md](file:///d:/PyCharm_Projects/Отпуск/ARCHITECTURE_INDEX.md).

* `backend/`
  * `main.py` (102 стр.) — FastAPI `app`, middleware заголовков безопасности (`frame-ancestors *` для `/miniapp`, `SAMEORIGIN` для остальных), `CORS_ORIGINS`, скрытие `/docs` в `production`, подключение 11 роутеров и статики `frontend/`.
  * `auth.py` (33 стр.) — Зависимость `require_admin` (`X-Admin-Token` / `?token=` против `ADMIN_API_KEY`).
  * `database.py` (73 стр.) — SQLite `vacations.db` (режим `WAL`, `synchronous=NORMAL`), `get_db()`, автомиграции `migrate_db()`.
  * `models.py` (144 стр.) — 9 ORM-моделей: `Department`, `JobRole`, `WorkShift`, `Employee` (вкл. `consent_152fz`), `BotAdmin`, `EmployeeDraft`, `ScheduleRule`, `VacationSlot`, `ChatMessage`.
  * `schemas.py` (362 стр.) — Pydantic v2 схемы с граничными валидаторами (`Field`, `field_validator`), включая `IncompatibleGroup` и `IncompatiblePair`.
  * `seed_data.py` (315 стр.) — `ensure_minimal_rules_if_empty()` (для продакшена), `ensure_default_rules()` и `seed_database()` (для локального демо).
  * `google_sheets_importer.py` (315 стр.) — Импорт из Google Sheets (`GOOGLE_SPREADSHEET_ID`) и обезличенный `FALLBACK_WORKERS`.
  * `solver/optimizer.py` (533 стр.) — `VacationOptimizer`: in-memory предзагрузка, проверка ТК РФ, блэкаутов, квот ролей/смен, групп и персональных пар непересечения (`_check_personal_pairs_violation`), Топ-3 альтернативы, пакетное согласование.
  * `solver/nlp_date_parser.py` (196 стр.) — Детерминированный парсер русских дат, месяцев, длительностей и интентов.
  * `agents/intake_agent.py` (594 стр.) — `IntakeAgent`: диалог 152-ФЗ, верификация телефона, накопительный черновик `EmployeeDraft` с учетом уже утвержденных (`APPROVED`) слотов года, защита от самопересечений.
  * `agents/solver_agent.py` (72 стр.) — `SolverAgent`: обертка над `VacationOptimizer` и запись слотов `commit_approved_slots`.
  * `agents/manager_agent.py` (171 стр.) — `ManagerAgent`: управление правилами, штатом и сводной статистикой `get_dashboard_summary`.
  * `services/llm_service.py` (182 стр.) — `GeminiFlashService` (`gemini-flash-lite-latest` + fallback), `sanitize_prompt_pii`, передача ключа в `x-goog-api-key`.
  * `services/max_bot_client.py` (270 стр.) — `MaxBotClient`: отправка сообщений, inline-кнопок (`callback` и `link`) и запроса контакта в MAX.
  * `api/` — Роутеры FastAPI:
    * `auth_routes.py` (19 стр.), `employee_routes.py` (152 стр.), `department_routes.py` (95 стр.), `role_routes.py` (152 стр.), `shift_routes.py` (66 стр.), `vacation_routes.py` (122 стр.), `rule_routes.py` (273 стр.), `admin_routes.py` (72 стр.), `chat_routes.py` (792 стр.), `miniapp_routes.py` (816 стр.), `export_routes.py` (150 стр.).
* `frontend/` (SPA без сборщика: локальные библиотеки в `frontend/vendor/` — Vue 3 + Tailwind CSS + Lucide Icons)
  * `index.html` (429 стр.) и `app.js` (604 стр.) — Основной веб-дашборд руководителя.
  * `miniapp.html` (581 стр.) и `miniapp.js` (652 стр.) — Ролевое мини-приложение MAX (`Мой отпуск`, `Кто когда в отпуске`, `Руководитель`) с редактированием черновика и возвратом заявок на правку.
  * `vendor/` — Локальные копии `vue.global.prod.js`, `tailwind.js`, `lucide.min.js` (защита от блокировок внешних CDN в РФ).
  * `components/` — Модули вкладок дашборда: `gantt-view.js` (259 стр.), `roster-view.js` (142 стр.), `dept-roles-view.js` (448 стр.), `rules-view.js` (479 стр.), `chat-view.js` (244 стр.).
* `deploy/` — `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `nginx_max.conf`, `deploy_vps.sh`.
* `tests/` — **150+ тестов** pytest в 13 файлах.

---

## 🪙 Протокол экономии токенов и поддержания актуальности документации
1. **Точечное чтение (`read_file` с `StartLine` и `EndLine`):**
   * Перед чтением крупных файлов (`chat_routes.py`, `miniapp_routes.py`, `intake_agent.py`, `app.js`, `miniapp.js`, `optimizer.py`, `schemas.py`) загляните в [ARCHITECTURE_INDEX.md](file:///d:/PyCharm_Projects/Отпуск/ARCHITECTURE_INDEX.md) и читайте только нужный диапазон строк.
2. **Запрет на сканирование `.venv` в терминале:**
   * При вызове PowerShell-команд **никогда** не запускайте `Get-ChildItem -Recurse` без фильтрации пути: используйте `Get-ChildItem -Directory` или исключайте `.venv` через `Where-Object { $_.FullName -notmatch '\\\.venv\\' }`.
3. **Использование навыка разработки фич (Progressive Disclosure):**
   * Если задача связана с **добавлением новой функции**, прочитайте пошаговый чек-лист в навыке [.agents/skills/add-feature-playbook/SKILL.md](file:///d:/PyCharm_Projects/Отпуск/.agents/skills/add-feature-playbook/SKILL.md).
4. **Единый источник истины и чистота Git:**
   * Новые колонки SQLite обязательно добавляются как в `backend/models.py`, так и в `migrate_db()` в `backend/database.py`.
   * Не оставляйте в рабочей директории неотслеживаемые `.exe`, `.db`, `.db-wal`, `.db-shm` или `.env` файлы (проверяется автотестом `test_ac62_workspace_cleanliness_git_status`).
   * В скрипте `deploy/deploy_vps.sh` всегда сохраняйте окончания строк `LF` (`\n`).
5. **Обязательное обновление правил при важных изменениях (Self-Updating Documentation Rule):**
   * **При любых важных изменениях архитектуры, бизнес-правил, схемы БД, списка эндпоинтов API, структуры Mini App или крупных файлов** ИИ-агент **обязан** в рамках той же задачи синхронно актуализировать:
     1. `AGENTS.md` (бизнес-правила, ограничения безопасности и карту кодовой базы).
     2. `ARCHITECTURE_INDEX.md` (индекс строк `StartLine`–`EndLine` по крупным файлам, схему таблиц БД и таблицу всех REST API маршрутов).
     3. `.agents/skills/add-feature-playbook/SKILL.md` (если изменились рецепты добавления правил, полей или UI-компонентов).
