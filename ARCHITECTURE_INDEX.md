# Архитектурный справочник, индекс API и карта строк (`ARCHITECTURE_INDEX.md`)

Этот документ служит быстрым справочником для ИИ-агентов и разработчиков. Используйте его, чтобы сразу находить нужные таблицы, эндпоинты и точные номера строк (`StartLine`–`EndLine`) без чтения файлов целиком.

---

## 1. Навигационный индекс строк по крупным файлам (Line Map)

Чтобы экономить токены, используйте `read_file` с указанными диапазонами `StartLine` и `EndLine`:

### [backend/api/chat_routes.py](file:///d:/PyCharm_Projects/Отпуск/backend/api/chat_routes.py) (734 строки)
* `L20–L68` — In-Memory Sliding Window Rate Limiter (`check_rate_limit`, `clear_rate_limits`, `extract_client_ip` с поддержкой `X-Forwarded-For` / `X-Real-IP`).
* `L70–L116` — `mask_phone` (маскирование ПДн в логах), `normalize_phone_number`, `extract_phone_and_name_from_vcard`.
* `L118–L219` — `extract_contact_from_webhook`, `extract_phone_from_webhook`: извлечение `(phone, contact_user_id)` из нативных контактов и вложений MAX / TamTam.
* `L224–L283` — Веб-симулятор: `POST /api/chat/message`, `GET /api/chat/history/{employee_id}` (с авто-приветствием), `POST /api/chat/reset/{employee_id}` (сброс истории и черновика).
* `L286–L428` — `extract_chat_id_from_webhook`, `extract_user_id_from_webhook` (защита от эхо-петель бота).
* `L430–L513` — `max_messenger_webhook` (часть 1): проверка `WEBHOOK_SECRET` (`X-Max-Bot-Token` / `?token=`), rate-limiting (`429`), извлечение `callback_data`, `text`, `phone`, `contact_user_id`.
* `L514–L608` — `max_messenger_webhook` (часть 2): **Anti-Spoofing проверка контакта** (`contact_user_id == payload.user_id`), привязка `Employee` / `BotAdmin` только при верифицированном контакте.
* `L609–L734` — `max_messenger_webhook` (часть 3): команда `/admin`, запрос контакта у неавторизованных пользователей, проверка `bot_access`, вызов `agent.process_message` в `run_in_threadpool`, формирование кнопок (152-ФЗ, альтернативы, подтверждение).

### [backend/agents/intake_agent.py](file:///d:/PyCharm_Projects/Отпуск/backend/agents/intake_agent.py) (568 строк)
* `L29–L42` — `_get_or_create_draft`: управление накопительным черновиком `EmployeeDraft`.
* `L43–L155` — `verify_employee_by_phone` и `_extract_first_name`: авторизация по номеру телефона, проверка `bot_access` (`APPROVED`, `PENDING`, `BLOCKED`), привязка `max_user_id`.
* `L156–L240` — `process_message` (часть 1): запись сообщения пользователя и **диалог согласия 152-ФЗ** (`consent_152fz`, кнопки `✅ Согласна` / `❌ Отказаться`).
* `L241–L357` — `process_message` (часть 2): сброс черновика (`check_reset_intent`), подтверждение заявки (`AWAITING_CONFIRMATION` -> `commit_approved_slots`), выбор альтернативы (`1`, `2`, `3`), приветствие `/start`.
* `L358–L466` — `process_message` (часть 3): гибридный парсинг дат (`llm_service.extract_dates_with_context`), дедупликация, замена неполного черновика при отправке сразу 36 дней, проверка самопересечений слотов, накопление и проверка перебора лимита.
* `L467–L568` — `process_message` (часть 4): вызов CSP-солвера при наборе ровно 36 дней, формирование превью (`VALID`), ошибок ТК РФ (`INVALID_TK`) или Топ-3 альтернатив (`CONFLICT`), метод `_reply`.

### [backend/solver/optimizer.py](file:///d:/PyCharm_Projects/Отпуск/backend/solver/optimizer.py) (478 строк)
* `L10–L32` — `VacationOptimizer.__init__` и `_load_rules()`: предзагрузка правил, квот ролей, квот смен, активных сотрудников и слотов в память (защита от N+1 запросов).
* `L33–L151` — `validate_and_check_slots`: проверка ТК РФ ($\ge 14$ дн.), нормы дней (36 дн.), блэкаутов, квот ролей, квот смен и групп непересечения.
* `L153–L304` — Методы проверок: `_check_blackout_intersection`, `_get_role_quota`, `_check_role_quota_violation`, `_get_shift_quota`, `_check_shift_quota_violation`, `_get_incompatible_groups`, `_check_incompatible_groups_violation`.
* `L306–L339` — `_get_first_conflict_reason`, `is_slot_valid`, `_find_candidate_slot`.
* `L341–L423` — `_generate_top3_alternatives`: 3 детерминированные стратегии подбора свободных дат.
* `L425–L478` — `batch_optimize_all_pending`: пакетное согласование заявок с приоритетом по стажу (`seniority_years`).

### [frontend/app.js](file:///d:/PyCharm_Projects/Отпуск/frontend/app.js) (563 строки)
* `L11–L61` — Реактивные состояния данных, фильтров, чата и модальных окон.
* `L62–L144` — Авторизация администратора (`adminToken`, `saveAdminToken`, `clearAdminToken`, `openAdminModal`, `adminFetch`) и скачивание отчетов `downloadExport(format)`.
* `L146–L219` — `computed`-свойства и `fetchAllData()` (параллельная загрузка 9 эндпоинтов).
* `L221–L295` — Методы чата (`loadChatHistory`, `openChatFor`, `sendMessage`, `chooseAlternative`, `confirmDraftSubmission`, `clearChat`).
* `L297–L401` — Управление слотами, пакетное согласование (`runBatchApprove`), CRUD сотрудников, синхронизация Google Таблицы (`syncGoogleSheets`), переключение `toggleBotAccess`.
* `L403–L563` — Сохранение правил (`saveRoleQuotas`, `saveShiftQuotas`, `addBlackout`, `addIncompatibleGroup`), наблюдатели `watch`, `onMounted` (опрос статистики каждые 30 сек при активной вкладке) и экспорт в шаблон.

### [backend/schemas.py](file:///d:/PyCharm_Projects/Отпуск/backend/schemas.py) (344 строки)
* `L6–L100` — Схемы `Department`, `JobRole` (`default_quota: 0..50`), `WorkShift` (`default_quota: 0..50`), `IncompatibleGroup`.
* `L102–L177` — Схемы `Employee` (`total_vacation_days: 1..120`, `consent_152fz: bool`) и `BotAdmin`.
* `L179–L258` — Схемы `DateSlot`, `VacationSlot`, `ScheduleRule` (валидатор `window_search_days: 1..90`).
* `L260–L344` — Схемы инструментов агентов (`VerifyPhone`, `OptimizeVacation`, `UpdateRulesAndRoster`) и чата (`ChatMessageIn` с `max_length=500`, `ChatMessageOut`, `MaxWebhookPayload`).

---

## 2. Схема базы данных (`SQLite: vacations.db`, [backend/models.py](file:///d:/PyCharm_Projects/Отпуск/backend/models.py))

БД работает в режиме `WAL` (`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;`), автомиграции выполняются в `migrate_db()` ([backend/database.py](file:///d:/PyCharm_Projects/Отпуск/backend/database.py#L35-L72)).

### Таблица `departments` (Цехи и подразделения — `L13–L24`)
* `id`: Integer, PK
* `name`: String(255), Unique, Not Null
* `code`: String(50), Nullable (`SEW_1`, `SEW_2`, `CUT`, `VTO`, `TECH`, `WH`, `ADM`)
* `manager_name`: String(255), Nullable
* `description`: Text, Nullable

### Таблица `job_roles` (Должности — `L26–L36`)
* `id`: Integer, PK
* `name`: String(100), Unique, Not Null
* `department_id`: Integer, FK -> `departments.id`, Nullable
* `description`: Text, Nullable
* `default_quota`: Integer (default `1`) — макс. одновременных отпусков по должности
* `is_critical`: Boolean (default `True`)

### Таблица `work_shifts` (Рабочие смены — `L39–L47`)
* `id`: Integer, PK
* `name`: String(100), Unique, Not Null
* `code`: String(50), Nullable (`SHIFT_1`, `SHIFT_2`, `SHIFT_2_2`, `SHIFT_5_2`)
* `description`: Text, Nullable
* `default_quota`: Integer (default `2`) — макс. одновременных отпусков в одной смене
* `is_active`: Boolean (default `True`)

### Таблица `employees` (Сотрудники — `L50–L73`)
* `id`: Integer, PK
* `phone`: String(20), Unique, Not Null, Index (формат `+7XXXXXXXXXX`)
* `max_user_id`: String(64), Unique, Nullable, Index
* `max_chat_id`: String(64), Nullable, Index
* `full_name`: String(255), Not Null
* `role`: String(100), Not Null
* `department_id`: Integer, FK -> `departments.id`, Not Null
* `shift`: String(50), default `"Смена 1 (дневная)"`
* `region`: String(100), default `"Республика Хакасия"`
* `total_vacation_days`: Integer, default `36`
* `seniority_years`: Integer, default `1`
* `social_priority`: String(50), default `"NONE"` (`NONE`, `LARGE_FAMILY`, `VETERAN`, `SOLO_PARENT`)
* `bot_access`: String(30), default `"APPROVED"` (`APPROVED`, `PENDING`, `BLOCKED`)
* `consent_152fz`: Boolean, default `False` (согласие на обработку ПДн по 152-ФЗ)
* `is_active`: Boolean, default `True`
* `created_at`: DateTime

### Таблица `bot_admins` (Администраторы бота MAX — `L76–L88`)
* `id`: Integer, PK
* `phone`: String(20), Unique, Not Null, Index
* `full_name`: String(255), Not Null
* `role_title`: String(100), default `"Администратор"`
* `max_user_id`: String(64), Unique, Nullable
* `max_chat_id`: String(64), Nullable, Index
* `is_active`: Boolean, default `True`
* `notify_on_new_request`: Boolean, default `True`
* `created_at`: DateTime

### Таблица `employee_drafts` (Накопительные черновики отпусков — `L91–L102`)
* `id`: Integer, PK
* `employee_id`: Integer, FK -> `employees.id`, Unique, Not Null
* `target_year`: Integer, default `2026`
* `slots`: JSON list (`[{"start": "2026-07-01", "end": "2026-07-14", "days": 14}]`)
* `status`: String(50), default `"DRAFTING"` (`DRAFTING`, `AWAITING_CONFIRMATION`, `COMMITTED`)
* `updated_at`: DateTime

### Таблица `schedule_rules` (Матрица правил планирования — `L105–L114`)
* `id`: Integer, PK
* `rule_key`: String(50), Unique, Not Null (`tk_rf_min_block`, `max_concurrent_roles`, `max_concurrent_shifts`, `incompatible_employee_groups`, `blackout_periods`)
* `rule_type`: String(20), Not Null (`HARD` | `SOFT`)
* `parameters`: JSON, Not Null
* `description`: Text, Nullable
* `is_active`: Boolean, default `True`
* `updated_at`: DateTime

### Таблица `vacation_slots` (Слоты отпусков — `L117–L131`)
* `id`: Integer, PK
* `employee_id`: Integer, FK -> `employees.id`, Not Null, Index
* `start_date`: Date, Not Null
* `end_date`: Date, Not Null
* `days_count`: Integer, Not Null
* `is_primary_block`: Boolean, default `False` (`True` если `days_count >= 14`)
* `status`: String(30), default `"REQUESTED"` (`REQUESTED`, `APPROVED`, `CONFLICT`, `REVISED`, `REJECTED`)
* `conflict_reason`: Text, Nullable
* `created_at`, `updated_at`: DateTime

### Таблица `chat_messages` (История сообщений — `L134–L144`)
* `id`: Integer, PK
* `employee_id`: Integer, FK -> `employees.id`, Not Null, Index
* `sender`: String(20), Not Null (`USER`, `AGENT`, `SYSTEM`)
* `text`: Text, Not Null
* `payload`: JSON, Nullable
* `timestamp`: DateTime

---

## 3. Полная карта REST API эндпоинтов (32 маршрута)

Эндпоинты с пометкой 🔒 требуют `Depends(require_admin)` (заголовок `X-Admin-Token` или `?token=` при установленном `ADMIN_API_KEY`).

| Метод | Эндпоинт | Защита | Роутер (`backend/api/`) | Описание |
| :--- | :--- | :---: | :--- | :--- |
| `POST` | `/api/auth/verify_phone` | Публ. | `auth_routes.py` | Верификация сотрудника по номеру телефона и привязка `max_user_id` |
| `GET` | `/api/employees` | Публ. | `employee_routes.py` | Список сотрудников (фильтры: `department_id`, `role`, `shift`, `search`) |
| `POST` | `/api/employees` | 🔒 Admin | `employee_routes.py` | Создание сотрудника через `ManagerAgent` |
| `PUT` | `/api/employees/{employee_id}` | 🔒 Admin | `employee_routes.py` | Обновление данных сотрудника |
| `DELETE` | `/api/employees/{employee_id}` | 🔒 Admin | `employee_routes.py` | Удаление сотрудника |
| `POST` | `/api/employees/sync-google-sheets` | 🔒 Admin | `employee_routes.py` | Синхронизация из Google Таблицы (или `FALLBACK_WORKERS`) |
| `PUT` | `/api/employees/{employee_id}/bot-access` | 🔒 Admin | `employee_routes.py` | Смена статуса доступа к боту (`?status=APPROVED\|PENDING\|BLOCKED`) |
| `GET` | `/api/departments` | Публ. | `department_routes.py` | Список цехов с количеством активных сотрудников |
| `POST` | `/api/departments` | 🔒 Admin | `department_routes.py` | Создание нового цеха |
| `PUT` | `/api/departments/{dept_id}` | 🔒 Admin | `department_routes.py` | Обновление цеха |
| `DELETE` | `/api/departments/{dept_id}` | 🔒 Admin | `department_routes.py` | Удаление пустого цеха |
| `GET` | `/api/roles` | Публ. | `role_routes.py` | Список должностей с квотами |
| `POST` | `/api/roles` | 🔒 Admin | `role_routes.py` | Создание должности (авто-синхронизация с `max_concurrent_roles`) |
| `PUT` | `/api/roles/{role_id}` | 🔒 Admin | `role_routes.py` | Обновление должности (каскадное переименование + синхронизация) |
| `DELETE` | `/api/roles/{role_id}` | 🔒 Admin | `role_routes.py` | Удаление должности (авто-синхронизация правил) |
| `GET` | `/api/shifts` | Публ. | `shift_routes.py` | Список рабочих смен |
| `POST` | `/api/shifts` | 🔒 Admin | `shift_routes.py` | Создание рабочей смены |
| `PUT` | `/api/shifts/{shift_id}` | 🔒 Admin | `shift_routes.py` | Обновление смены и её квоты |
| `DELETE` | `/api/shifts/{shift_id}` | 🔒 Admin | `shift_routes.py` | Удаление смены |
| `GET` | `/api/vacations` | Публ. | `vacation_routes.py` | Список слотов отпусков (фильтры: `year`, `department_id`, `role`, `shift`, `status`, `employee_id`) |
| `POST` | `/api/vacations/optimize` | Публ. | `vacation_routes.py` | Запуск CSP-солвера для проверки слотов и генерации альтернатив |
| `POST` | `/api/vacations/batch-approve` | 🔒 Admin | `vacation_routes.py` | Групповое утверждение всех валидных заявок (`?year=2026`) |
| `PUT` | `/api/vacations/{slot_id}/status` | 🔒 Admin | `vacation_routes.py` | Изменение статуса слота (`?status=APPROVED\|REJECTED\|CONFLICT\|REQUESTED`) |
| `DELETE` | `/api/vacations/{slot_id}` | 🔒 Admin | `vacation_routes.py` | Удаление слота отпуска |
| `GET` | `/api/rules` | Публ. | `rule_routes.py` | Список всех правил планирования |
| `POST` | `/api/rules/action` | 🔒 Admin | `rule_routes.py` | Универсальный вызов `ManagerAgent.update_rules_and_roster` |
| `PUT` | `/api/rules/role-quotas` | 🔒 Admin | `rule_routes.py` | Сохранение квот одновременного отсутствия по должностям |
| `PUT` | `/api/rules/shift-quotas` | 🔒 Admin | `rule_routes.py` | Сохранение квот одновременного отсутствия по сменам |
| `PUT` | `/api/rules/blackouts` | 🔒 Admin | `rule_routes.py` | Обновление списка блэкаут-периодов |
| `PUT` | `/api/rules/{rule_id}/toggle` | 🔒 Admin | `rule_routes.py` | Включение/выключение правила |
| `GET` | `/api/rules/incompatible-groups` | Публ. | `rule_routes.py` | Список групп непересекающихся сотрудников |
| `POST` | `/api/rules/incompatible-groups` | 🔒 Admin | `rule_routes.py` | Создание группы взаимного исключения сотрудников |
| `DELETE` | `/api/rules/incompatible-groups/{group_id}` | 🔒 Admin | `rule_routes.py` | Удаление группы взаимного исключения |
| `GET` | `/api/bot-admins` | Публ. | `admin_routes.py` | Список администраторов бота MAX |
| `POST` | `/api/bot-admins` | 🔒 Admin | `admin_routes.py` | Добавление администратора бота |
| `PUT` | `/api/bot-admins/{admin_id}` | 🔒 Admin | `admin_routes.py` | Обновление администратора бота |
| `DELETE` | `/api/bot-admins/{admin_id}` | 🔒 Admin | `admin_routes.py` | Удаление администратора бота |
| `POST` | `/api/chat/message` | Публ. | `chat_routes.py` | Отправка сообщения в веб-симулятор чата |
| `GET` | `/api/chat/history/{employee_id}` | Публ. | `chat_routes.py` | Получение истории чата сотрудника |
| `POST` | `/api/chat/reset/{employee_id}` | Публ. | `chat_routes.py` | Очистка истории чата и черновика сотрудника |
| `POST/GET` | `/api/chat/webhook` (`/webhook/max`) | 🔑 Secret + RL | `chat_routes.py` | Вебхук MAX (`WEBHOOK_SECRET` + Rate Limit 10 req/min + Anti-Spoofing) |
| `GET` | `/api/export/stats` | Публ. | `export_routes.py` | Сводная KPI-статистика для шапки дашборда |
| `GET` | `/api/export/csv` | 🔒 Admin | `export_routes.py` | Выгрузка графика в CSV (`utf-8-sig`, санитизация формул) |
| `GET` | `/api/export/excel` | 🔒 Admin | `export_routes.py` | Выгрузка формы Т-7 в Excel (`.xlsx` через `openpyxl`, санитизация формул) |
