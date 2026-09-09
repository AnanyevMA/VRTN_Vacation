# Архитектурный справочник и индекс API (ARCHITECTURE_INDEX.md)

Этот документ предназначен для быстрого контекстного доступа агентов и разработчиков без необходимости сканирования исходных файлов.

---

## 1. Схема базы данных (SQLite: vacations.db)

### Таблица departments (Цехи)
- id: Integer, PK
- 
ame: String(100), Unique
- code: String(20), Unique (e.g. SEW_1, SEW_2, CUT, VTO, TECH, WH, ADM)
- manager_name: String(100)
- description: Text
- is_active: Boolean (default True)

### Таблица job_roles (Должности)
- id: Integer, PK
- 
ame: String(100), Unique
- department_id: Integer, FK -> departments.id
- default_quota: Integer (лимит одновременного отсутствия, default 1)
- description: Text
- is_critical: Boolean (default False)

### Таблица work_shifts (Смены)
- id: Integer, PK
- 
ame: String(100)
- code: String(20), Unique (SHIFT_1, SHIFT_2, SHIFT_2_2, SHIFT_5_2)
- description: Text

### Таблица employees (Сотрудники)
- id: Integer, PK
- phone: String(20), Unique
- max_user_id: String(100), Unique, Nullable
- ull_name: String(100)
- 
ole: String(50)
- department_id: Integer, FK -> departments.id
- shift: String(50) (Смена 1, Смена 2, 2/2, 5/2)
- 
egion: String(50) (default 'Республика Хакасия')
- 	otal_vacation_days: Integer (default 36)
- seniority_years: Integer (default 1)
- social_priority: Boolean (default False)
- ot_access: String(30) (enum: 'APPROVED', 'PENDING', 'BLOCKED', default 'APPROVED')
- is_active: Boolean (default True)

### Таблица acation_slots (Слоты отпуска)
- id: Integer, PK
- employee_id: Integer, FK -> employees.id
- start_date: Date
- end_date: Date
- days_count: Integer
- is_primary_block: Boolean (блок >= 14 дней)
- status: String(20) ('REQUESTED', 'APPROVED', 'REJECTED', 'CONFLICT')
- conflict_reason: Text, Nullable

### Таблица employee_drafts (Черновики заявок)
- id: Integer, PK
- employee_id: Integer, FK -> employees.id, Unique
- 	arget_year: Integer (default 2026)
- slots: JSON list (временные части отпуска)
- status: String(20) ('DRAFTING', 'SUBMITTED')

### Таблица schedule_rules (Матрица правил)
- id: Integer, PK
- 
ule_key: String(50), Unique ('max_concurrent_roles', 'blackout_periods', 'min_continuous_block', 'total_days_norm')
- description: Text
- parameters: JSON
- is_active: Boolean

### Таблица ot_admins (Администраторы бота MAX)
- id: Integer, PK
- phone: String(30), Unique
- ull_name: String(100)
- 
ole_title: String(100)
- max_user_id: String(100), Nullable
- is_active: Boolean (default True)
- 
otify_on_new_request: Boolean (default True)

---

## 2. Карта REST API эндпоинтов

| Метод | Путь | Описание |
|---|---|---|
| GET | /api/employees | Список всех сотрудников (включая цех, смену, баланс дней и ot_access) |
| POST | /api/employees | Создание сотрудника |
| PUT | /api/employees/{id} | Обновление данных сотрудника |
| DELETE | /api/employees/{id} | Удаление сотрудника |
| PUT | /api/employees/{id}/bot-access?status=... | Изменение доступа к боту MAX (APPROVED, PENDING, BLOCKED) |
| POST | /api/employees/sync-google-sheets | Синхронизация 15 реальных швей из Google Таблиц |
| GET | /api/departments | Список цехов |
| POST | /api/departments | Создание цеха |
| PUT | /api/departments/{id} | Обновление цеха |
| DELETE | /api/departments/{id} | Удаление цеха |
| GET | /api/roles | Список должностей |
| POST | /api/roles | Создание должности (авто-синхронизируется в ScheduleRule) |
| PUT | /api/roles/{id} | Обновление должности |
| DELETE | /api/roles/{id} | Удаление должности (авто-удаляется из ScheduleRule) |
| GET | /api/shifts | Список рабочих смен |
| GET | /api/vacations?year=2026 | Слоты отпусков с фильтрацией по году |
| POST | /api/vacations | Создание слота отпуска |
| PUT | /api/vacations/{id} | Изменение статуса слота |
| DELETE | /api/vacations/{id} | Удаление слота |
| POST | /api/vacations/batch-approve | Групповое пакетное утверждение заявок солвером |
| GET | /api/rules | Получение всех правил планирования |
| PUT | /api/rules/role-quotas | Обновление матрицы квот отсутствия по должностям |
| PUT | /api/rules/shift-quotas | Обновление матрицы квот одновременных отпусков по сменам |
| GET | /api/rules/incompatible-groups | Список групп непересекающихся сотрудников |
| POST | /api/rules/incompatible-groups | Создание группы взаимного исключения отпусков |
| DELETE | /api/rules/incompatible-groups/{id} | Удаление группы непересечения сотрудников |
| PUT | /api/rules/blackouts | Обновление запретных периодов |
| GET | /api/bot-admins | Список администраторов бота MAX |
| POST | /api/bot-admins | Добавление администратора бота |
| PUT | /api/bot-admins/{id} | Редактирование администратора |
| DELETE | /api/bot-admins/{id} | Удаление администратора |
| POST | /api/chat/message | Отправка сообщения в симулятор MAX |
| GET | /api/chat/history/{emp_id} | История сообщений сотрудника |
| POST | /api/chat/reset/{emp_id} | Очистка истории сообщений |
| POST | /api/chat/webhook | Webhook входящих сообщений и кнопок мессенджера MAX |
| GET | /api/export/t7.csv | Экспорт унифицированной формы Т-7 |
| GET | /api/export/stats | Сводная статистика (заявки, конфликты, балансы) |

---

## 3. Архитектура обработки заявок мессенджера MAX

`
[Швея в мессенджере MAX]
       │
       ▼ (Webhook HTTPS)
[POST /api/chat/webhook]
       │
       ├─► Проверка: Телефон в базе Employee?
       │     Нет ──► Отказ: 'Номер не найден в базе фабрики'
       │
       ├─► Проверка: bot_access == 'APPROVED'?
       │     PENDING ─► 'Номер ожидает подтверждения администратором'
       │     BLOCKED ─► 'Доступ заблокирован'
       │
       ├─► Проверка: Отправитель — BotAdmin?
       │     Команда /admin ─► Сводка по базе и ожидающим номерам
       │
       ▼
[IntakeAgent (Hybrid NLP)]
       │
       ├─► Извлечение дат:
       │     1. Регулярный парсер (1 мс)
       │     2. При сложном тексте ──► Gemini Flash Free Tier
       │
       ▼
[SolverAgent (Детерминированный CSP)]
       │
       ├─► Проверка: 14 дней непрерывно (ст. 125 ТК РФ)
       ├─► Проверка: Сумма дней <= 36 (Хакасия)
       ├─► Проверка: Квота смены и цеха не превышена
       ├─► Проверка: Нет пересечения с Blackout-периодами
       │
       ▼
[Ответ швее в MAX] (Превью, баланс оставшихся дней, интерактивные кнопки)
`
