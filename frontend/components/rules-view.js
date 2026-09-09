window.RulesView = {
    props: ['roles', 'roleQuotas', 'blackoutsList', 'shifts', 'shiftQuotas', 'employees', 'incompatibleGroups'],
    emits: ['save-role-quotas', 'add-blackout', 'remove-blackout', 'save-shift-quotas', 'add-incompatible-group', 'delete-incompatible-group'],
    data() {
        return {
            newBlackout: { name: '', start: '', end: '' },
            newGroup: {
                name: '',
                employee_ids: [],
                max_concurrent: 1,
                reason: '',
            },
            empSearch: '',
        };
    },
    computed: {
        filteredEmployees() {
            if (!this.employees) return [];
            if (!this.empSearch.trim()) return this.employees;
            const q = this.empSearch.toLowerCase();
            return this.employees.filter(e => 
                (e.full_name && e.full_name.toLowerCase().includes(q)) ||
                (e.role && e.role.toLowerCase().includes(q)) ||
                (e.shift && e.shift.toLowerCase().includes(q))
            );
        }
    },
    methods: {
        adjustQuota(roleName, delta) {
            const current = this.roleQuotas[roleName] !== undefined ? this.roleQuotas[roleName] : 1;
            this.roleQuotas[roleName] = Math.max(1, current + delta);
        },
        adjustShiftQuota(shiftName, delta) {
            const current = this.shiftQuotas[shiftName] !== undefined ? this.shiftQuotas[shiftName] : 2;
            this.shiftQuotas[shiftName] = Math.max(1, current + delta);
        },
        toggleEmployeeInGroup(empId) {
            const idx = this.newGroup.employee_ids.indexOf(empId);
            if (idx > -1) {
                this.newGroup.employee_ids.splice(idx, 1);
            } else {
                this.newGroup.employee_ids.push(empId);
            }
        },
        handleAddIncompatibleGroup() {
            if (!this.newGroup.name.trim()) {
                return alert('Укажите название группы непересечения (напр., «Ведущие портные блузочного потока»)');
            }
            if (this.newGroup.employee_ids.length < 2) {
                return alert('Выберите минимум 2 сотрудников для установки запрета одновременного отпуска');
            }
            this.$emit('add-incompatible-group', { ...this.newGroup });
            this.newGroup = {
                name: '',
                employee_ids: [],
                max_concurrent: 1,
                reason: '',
            };
            this.empSearch = '';
        },
        handleAddBlackout() {
            if (!this.newBlackout.name || !this.newBlackout.start || !this.newBlackout.end) {
                return alert('Заполните все поля блэкаут-периода');
            }
            this.$emit('add-blackout', { ...this.newBlackout });
            this.newBlackout = { name: '', start: '', end: '' };
        },
        formatDateRu(dStr) {
            if (!dStr) return '';
            return new Date(dStr).toLocaleDateString('ru-RU');
        }
    },
    template: `
    <div class="space-y-6">
        <!-- ROW 1: Quotas by Job Role & Quotas by Shift -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- 1. Role Concurrency Quotas -->
            <div class="bg-slate-800/90 p-5 rounded-2xl border border-slate-700/70 shadow space-y-4">
                <div class="flex items-center justify-between border-b border-slate-700 pb-3">
                    <div>
                        <h3 class="font-bold text-white text-base flex items-center gap-2">
                            <i data-lucide="users-2" class="w-5 h-5 text-indigo-400"></i>
                            Квоты по должностям (Anti-Overlap)
                        </h3>
                        <p class="text-xs text-slate-400">Максимум одновременных отсутствий швей, закройщиков и технологов</p>
                    </div>
                </div>

                <div class="space-y-2.5 max-h-72 overflow-y-auto pr-1">
                    <div v-for="r in roles" :key="r.id" class="flex items-center justify-between bg-slate-900/60 p-2.5 rounded-xl border border-slate-800">
                        <div>
                            <div class="font-semibold text-xs text-slate-200">{{ r.name }}</div>
                            <div class="text-[11px] text-slate-500">{{ r.department_name || 'Швейное производство' }}</div>
                        </div>
                        <div class="flex items-center space-x-2">
                            <button @click="adjustQuota(r.name, -1)" class="w-7 h-7 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold flex items-center justify-center text-xs">-</button>
                            <span class="w-7 text-center font-bold text-indigo-400 font-mono text-sm">
                                {{ roleQuotas[r.name] !== undefined ? roleQuotas[r.name] : r.default_quota }}
                            </span>
                            <button @click="adjustQuota(r.name, 1)" class="w-7 h-7 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold flex items-center justify-center text-xs">+</button>
                        </div>
                    </div>

                    <div v-if="!roles || !roles.length" class="text-xs text-slate-500 italic p-3">
                        Нет созданных должностей.
                    </div>
                </div>

                <button @click="$emit('save-role-quotas')" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-medium py-2 rounded-xl text-xs transition">
                    Сохранить квоты должностей
                </button>
            </div>

            <!-- 2. Shift Concurrency Quotas -->
            <div class="bg-slate-800/90 p-5 rounded-2xl border border-slate-700/70 shadow space-y-4">
                <div class="flex items-center justify-between border-b border-slate-700 pb-3">
                    <div>
                        <h3 class="font-bold text-white text-base flex items-center gap-2">
                            <i data-lucide="layers" class="w-5 h-5 text-cyan-400"></i>
                            Квоты по сменам (Anti-Overlap)
                        </h3>
                        <p class="text-xs text-slate-400">Ограничение на количество одновременно отсутствующих швей одной бригады/смены</p>
                    </div>
                </div>

                <div class="space-y-2.5 max-h-72 overflow-y-auto pr-1">
                    <div v-for="s in shifts" :key="s.id" class="flex items-center justify-between bg-slate-900/60 p-2.5 rounded-xl border border-slate-800">
                        <div>
                            <div class="font-semibold text-xs text-slate-200">{{ s.name }}</div>
                            <div class="text-[11px] text-slate-500">{{ s.description || 'График работы бригады' }}</div>
                        </div>
                        <div class="flex items-center space-x-2">
                            <button @click="adjustShiftQuota(s.name, -1)" class="w-7 h-7 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold flex items-center justify-center text-xs">-</button>
                            <span class="w-7 text-center font-bold text-cyan-400 font-mono text-sm">
                                {{ shiftQuotas[s.name] !== undefined ? shiftQuotas[s.name] : (s.default_quota || 2) }}
                            </span>
                            <button @click="adjustShiftQuota(s.name, 1)" class="w-7 h-7 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold flex items-center justify-center text-xs">+</button>
                        </div>
                    </div>

                    <div v-if="!shifts || !shifts.length" class="text-xs text-slate-500 italic p-3">
                        Нет созданных смен.
                    </div>
                </div>

                <button @click="$emit('save-shift-quotas')" class="w-full bg-cyan-600 hover:bg-cyan-500 text-white font-medium py-2 rounded-xl text-xs transition">
                    Сохранить квоты смен
                </button>
            </div>
        </div>

        <!-- ROW 2: Incompatible Employee Groups (Multi-person Anti-Overlap) -->
        <div class="bg-slate-800/90 p-5 rounded-2xl border border-slate-700/70 shadow space-y-4">
            <div class="flex items-center justify-between border-b border-slate-700 pb-3">
                <div>
                    <h3 class="font-bold text-white text-base flex items-center gap-2">
                        <i data-lucide="user-x" class="w-5 h-5 text-rose-400"></i>
                        Группы непересекающихся сотрудников (Запрет одновременного отпуска)
                    </h3>
                    <p class="text-xs text-slate-400">Выбор нескольких сотрудниц (от 2 и более человек), чьи отпуска не могут пересекаться во времени</p>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <!-- List of Active Exclusion Groups -->
                <div class="space-y-3">
                    <div class="text-xs font-semibold text-slate-300 flex items-center justify-between">
                        <span>Действующие правила непересечения:</span>
                        <span class="text-slate-400 text-[11px]">Всего групп: {{ incompatibleGroups ? incompatibleGroups.length : 0 }}</span>
                    </div>

                    <div class="space-y-2.5 max-h-80 overflow-y-auto pr-1">
                        <div v-for="g in incompatibleGroups" :key="g.id" class="bg-slate-900/70 p-3 rounded-xl border border-slate-800 text-xs space-y-2">
                            <div class="flex items-start justify-between">
                                <div>
                                    <div class="font-bold text-rose-300 text-sm">{{ g.name }}</div>
                                    <div class="text-slate-400 text-[11px] italic">{{ g.reason || 'Запрет одновременного отпуска' }}</div>
                                </div>
                                <div class="flex items-center gap-2">
                                    <span class="text-[10px] bg-rose-950/60 text-rose-300 px-2 py-0.5 rounded border border-rose-800/50">
                                        Макс. одновременно: {{ g.max_concurrent }} чел.
                                    </span>
                                    <button @click="$emit('delete-incompatible-group', g.id)" class="text-rose-400 hover:text-rose-300 p-1">
                                        <i data-lucide="trash" class="w-4 h-4"></i>
                                    </button>
                                </div>
                            </div>
                            <!-- Badges of group members -->
                            <div class="flex flex-wrap gap-1.5 pt-1">
                                <span v-for="(name, nIdx) in g.employee_names" :key="nIdx" class="bg-slate-800 text-slate-200 px-2 py-0.5 rounded-md text-[11px] border border-slate-700">
                                    👤 {{ name }}
                                </span>
                            </div>
                        </div>

                        <div v-if="!incompatibleGroups || !incompatibleGroups.length" class="text-xs text-slate-500 italic p-6 text-center bg-slate-900/40 rounded-xl border border-dashed border-slate-800">
                            Правила непересечения еще не заданы. Выберите сотрудниц справа и создайте первую группу.
                        </div>
                    </div>
                </div>

                <!-- Form to Create Multi-person Exclusion Group -->
                <div class="bg-slate-900/90 p-4 rounded-xl border border-slate-700/60 space-y-3 text-xs">
                    <div class="font-bold text-slate-200 text-sm flex items-center justify-between">
                        <span>Новая группа непересечения:</span>
                        <span class="text-rose-400 font-mono">Выбрано: {{ newGroup.employee_ids.length }} чел.</span>
                    </div>

                    <div class="space-y-1">
                        <label class="text-[11px] text-slate-400">Название правила / группы:</label>
                        <input v-model="newGroup.name" placeholder="Напр., Ведущие портные потока блуз" class="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-slate-200 text-xs"/>
                    </div>

                    <div class="space-y-1">
                        <div class="flex items-center justify-between">
                            <label class="text-[11px] text-slate-400">Выберите сотрудниц (отметьте нужных):</label>
                            <input v-model="empSearch" placeholder="Поиск швеи..." class="bg-slate-800 border border-slate-700 rounded px-2 py-0.5 text-[11px] text-slate-200 w-36"/>
                        </div>

                        <!-- Clickable employee checklist -->
                        <div class="max-h-40 overflow-y-auto bg-slate-950/60 p-2 rounded-lg border border-slate-800 grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                            <button 
                                v-for="emp in filteredEmployees" 
                                :key="emp.id"
                                type="button"
                                @click="toggleEmployeeInGroup(emp.id)"
                                :class="newGroup.employee_ids.includes(emp.id) ? 'bg-rose-950/80 border-rose-600 text-rose-200 font-semibold' : 'bg-slate-900/60 border-slate-800 text-slate-300 hover:bg-slate-800'"
                                class="flex items-center justify-between p-1.5 rounded text-[11px] border text-left transition">
                                <span class="truncate">{{ emp.full_name }}</span>
                                <span v-if="newGroup.employee_ids.includes(emp.id)" class="text-rose-400 font-bold ml-1">✓</span>
                            </button>
                        </div>
                    </div>

                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                            <label class="text-[11px] text-slate-400">Лимит одновременных отпусков:</label>
                            <input v-model.number="newGroup.max_concurrent" type="number" min="1" max="5" class="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-slate-200 text-xs"/>
                            <span class="text-[10px] text-slate-500">1 = абсолютный запрет любого пересечения</span>
                        </div>
                        <div>
                            <label class="text-[11px] text-slate-400">Причина запрета:</label>
                            <input v-model="newGroup.reason" placeholder="Напр., Взаимозаменяемые на ключевом участке" class="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-slate-200 text-xs"/>
                        </div>
                    </div>

                    <button @click="handleAddIncompatibleGroup" class="w-full bg-rose-600 hover:bg-rose-500 text-white font-medium py-2 rounded-xl text-xs transition mt-2">
                        Создать группу непересечения
                    </button>
                </div>
            </div>
        </div>

        <!-- ROW 3: Blackout Dates Configuration -->
        <div class="bg-slate-800/90 p-5 rounded-2xl border border-slate-700/70 shadow space-y-4">
            <div class="flex items-center justify-between border-b border-slate-700 pb-3">
                <div>
                    <h3 class="font-bold text-white text-base flex items-center gap-2">
                        <i data-lucide="calendar-x-2" class="w-5 h-5 text-amber-400"></i>
                        Блэкаут-периоды (Пиковые сезоны производства)
                    </h3>
                    <p class="text-xs text-slate-400">Запрет отпусков в периоды сдачи сезонных коллекций, годового переучета и школьного госзаказа</p>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div class="space-y-2.5 max-h-56 overflow-y-auto pr-1">
                    <div v-for="(b, idx) in blackoutsList" :key="idx" class="flex items-center justify-between bg-slate-900/60 p-3 rounded-xl border border-slate-800 text-xs">
                        <div>
                            <div class="font-bold text-amber-300">{{ b.name }}</div>
                            <div class="text-slate-400 font-mono">{{ formatDateRu(b.start) }} — {{ formatDateRu(b.end) }}</div>
                        </div>
                        <button @click="$emit('remove-blackout', idx)" class="text-rose-400 hover:text-rose-300 p-1">
                            <i data-lucide="trash" class="w-4 h-4"></i>
                        </button>
                    </div>
                    <div v-if="!blackoutsList || !blackoutsList.length" class="text-xs text-slate-500 italic p-3">
                        Нет активных блэкаут-периодов.
                    </div>
                </div>

                <!-- Add Blackout Form -->
                <div class="bg-slate-900/90 p-3.5 rounded-xl border border-slate-700/60 space-y-2.5 text-xs">
                    <div class="font-semibold text-slate-300">Добавить запретный период:</div>
                    <input v-model="newBlackout.name" placeholder="Название (напр., Пик пошива школьной формы)" class="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-slate-200"/>
                    <div class="grid grid-cols-2 gap-2">
                        <input v-model="newBlackout.start" type="date" class="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-slate-200"/>
                        <input v-model="newBlackout.end" type="date" class="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-slate-200"/>
                    </div>
                    <button @click="handleAddBlackout" class="w-full bg-amber-600 hover:bg-amber-500 text-white font-medium py-1.5 rounded transition">
                        Добавить период
                    </button>
                </div>
            </div>
        </div>

        <!-- ROW 4: Labor Law (TK RF) and Optimization Rules -->
        <div class="bg-slate-800/90 p-5 rounded-2xl border border-slate-700/70 shadow space-y-4">
            <h3 class="font-bold text-white text-base flex items-center gap-2 border-b border-slate-700 pb-3">
                <i data-lucide="scale" class="w-5 h-5 text-emerald-400"></i>
                Нормативы ТК РФ и параметры оптимизатора швейного производства
            </h3>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
                <div class="bg-slate-900/60 p-3.5 rounded-xl border border-slate-800 space-y-1">
                    <div class="font-bold text-slate-200 flex items-center justify-between">
                        <span>Неделимый блок &ge; 14 дней</span>
                        <span class="text-emerald-400 font-semibold">HARD</span>
                    </div>
                    <p class="text-slate-400">Статья 125 ТК РФ. Минимум одна непрерывная часть отпуска за рабочий год должна быть от 14 календарных дней.</p>
                </div>

                <div class="bg-slate-900/60 p-3.5 rounded-xl border border-slate-800 space-y-1">
                    <div class="font-bold text-slate-200 flex items-center justify-between">
                        <span>Региональная норма (36 дней)</span>
                        <span class="text-emerald-400 font-semibold">HARD</span>
                    </div>
                    <p class="text-slate-400">28 основных + 8 дополнительных календарных дней для предприятий Республики Хакасия.</p>
                </div>

                <div class="bg-slate-900/60 p-3.5 rounded-xl border border-slate-800 space-y-1">
                    <div class="font-bold text-slate-200 flex items-center justify-between">
                        <span>Мягкие веса (Soft Criteria)</span>
                        <span class="text-indigo-400 font-semibold">SOFT</span>
                    </div>
                    <p class="text-slate-400">Приоритет по трудовому стажу (швеи и мастера с большим опытом) и штраф за дробление отпуска на отрезки менее 7 дней.</p>
                </div>
            </div>
        </div>
    </div>
    `
};
