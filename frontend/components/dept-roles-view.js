window.DeptRolesView = {
    props: ['departments', 'roles', 'shifts', 'botAdmins'],
    emits: ['refresh-data'],
    data() {
        return {
            deptModalOpen: false,
            roleModalOpen: false,
            shiftModalOpen: false,
            adminModalOpen: false,
            isEditing: false,
            deptForm: { id: null, name: '', code: '', manager_name: '', description: '' },
            roleForm: { id: null, name: '', department_id: null, default_quota: 1, description: '', is_critical: true },
            shiftForm: { id: null, name: '', code: '', description: '', is_active: true },
            adminForm: { id: null, full_name: '', phone: '+79', role_title: 'Начальник цеха', notify_on_new_request: true },
        };
    },
    methods: {
        // --- Department Actions ---
        openAddDept() {
            this.isEditing = false;
            this.deptForm = { id: null, name: '', code: '', manager_name: '', description: '' };
            this.deptModalOpen = true;
        },
        editDept(d) {
            this.isEditing = true;
            this.deptForm = { ...d };
            this.deptModalOpen = true;
        },
        async saveDept() {
            if (!this.deptForm.name.trim()) return alert('Укажите название цеха / отдела');
            const url = this.isEditing ? `api/departments/${this.deptForm.id}` : 'api/departments';
            const method = this.isEditing ? 'PUT' : 'POST';
            const res = await window.adminFetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.deptForm)
            });
            if (!res.ok) {
                const err = await res.json();
                return alert(err.detail || 'Ошибка сохранения цеха');
            }
            this.deptModalOpen = false;
            this.$emit('refresh-data');
        },
        async deleteDept(id) {
            if (!confirm('Удалить данный цех / отдел?')) return;
            const res = await window.adminFetch(`api/departments/${id}`, { method: 'DELETE' });
            if (!res.ok) {
                const err = await res.json();
                return alert(err.detail || 'Ошибка удаления');
            }
            this.$emit('refresh-data');
        },

        // --- Role Actions ---
        openAddRole() {
            this.isEditing = false;
            this.roleForm = { id: null, name: '', department_id: this.departments[0]?.id || null, default_quota: 1, description: '', is_critical: true };
            this.roleModalOpen = true;
        },
        editRole(r) {
            this.isEditing = true;
            this.roleForm = { ...r };
            this.roleModalOpen = true;
        },
        async saveRole() {
            if (!this.roleForm.name.trim()) return alert('Укажите наименование должности');
            const url = this.isEditing ? `api/roles/${this.roleForm.id}` : 'api/roles';
            const method = this.isEditing ? 'PUT' : 'POST';
            const res = await window.adminFetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.roleForm)
            });
            if (!res.ok) {
                const err = await res.json();
                return alert(err.detail || 'Ошибка сохранения должности');
            }
            this.roleModalOpen = false;
            this.$emit('refresh-data');
        },
        async deleteRole(id) {
            if (!confirm('Удалить данную должность?')) return;
            const res = await window.adminFetch(`api/roles/${id}`, { method: 'DELETE' });
            if (!res.ok) {
                const err = await res.json();
                return alert(err.detail || 'Ошибка удаления');
            }
            this.$emit('refresh-data');
        },

        // --- Shift Actions ---
        openAddShift() {
            this.isEditing = false;
            this.shiftForm = { id: null, name: '', code: '', description: '', is_active: true };
            this.shiftModalOpen = true;
        },
        editShift(s) {
            this.isEditing = true;
            this.shiftForm = { ...s };
            this.shiftModalOpen = true;
        },
        async saveShift() {
            if (!this.shiftForm.name.trim()) return alert('Укажите наименование смены');
            const url = this.isEditing ? `api/shifts/${this.shiftForm.id}` : 'api/shifts';
            const method = this.isEditing ? 'PUT' : 'POST';
            const res = await window.adminFetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.shiftForm)
            });
            if (!res.ok) {
                const err = await res.json();
                return alert(err.detail || 'Ошибка сохранения смены');
            }
            this.shiftModalOpen = false;
            this.$emit('refresh-data');
        },
        async deleteShift(id) {
            if (!confirm('Удалить смену?')) return;
            const res = await window.adminFetch(`api/shifts/${id}`, { method: 'DELETE' });
            if (!res.ok) {
                const err = await res.json();
                return alert(err.detail || 'Ошибка удаления');
            }
            this.$emit('refresh-data');
        },

        // --- Bot Admin Actions ---
        openAddAdmin() {
            this.adminForm = { id: null, full_name: '', phone: '+79', role_title: 'Начальник цеха', notify_on_new_request: true };
            this.adminModalOpen = true;
        },
        async saveAdmin() {
            if (!this.adminForm.full_name.trim() || !this.adminForm.phone.trim()) {
                return alert('Заполните ФИО и номер телефона администратора');
            }
            const res = await (window.adminFetch || fetch)('api/bot-admins', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.adminForm)
            });
            if (!res.ok) {
                if (res.status === 401) return;
                const err = await res.json();
                return alert(err.detail || 'Ошибка добавления администратора');
            }
            this.adminModalOpen = false;
            this.$emit('refresh-data');
        },
        async deleteAdmin(id) {
            if (!confirm('Удалить администратора бота?')) return;
            const res = await (window.adminFetch || fetch)(`api/bot-admins/${id}`, { method: 'DELETE' });
            if (!res.ok) {
                if (res.status === 401) return;
                const err = await res.json();
                return alert(err.detail || 'Ошибка удаления');
            }
            this.$emit('refresh-data');
        }
    },
    template: `
    <div class="space-y-8">
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- 1. Departments Section -->
            <div class="bg-slate-800/90 rounded-2xl border border-slate-700/70 p-5 shadow space-y-4">
                <div class="flex items-center justify-between border-b border-slate-700 pb-3">
                    <div>
                        <h3 class="font-bold text-white text-base flex items-center gap-2">
                            <i data-lucide="building-2" class="w-5 h-5 text-indigo-400"></i>
                            Цехи и подразделения фабрики
                        </h3>
                        <p class="text-xs text-slate-400">Структура швейного производства</p>
                    </div>
                    <button @click="openAddDept" class="bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold px-3 py-1.5 rounded-xl flex items-center gap-1.5 transition shadow">
                        <i data-lucide="plus" class="w-4 h-4"></i>
                        Добавить цех
                    </button>
                </div>

                <div class="space-y-2.5 max-h-80 overflow-y-auto">
                    <div v-for="d in departments" :key="d.id" class="flex items-center justify-between bg-slate-900/60 p-3 rounded-xl border border-slate-800 text-xs">
                        <div>
                            <div class="font-bold text-white flex items-center gap-2">
                                {{ d.name }}
                                <span v-if="d.code" class="text-[10px] bg-slate-800 text-indigo-300 px-1.5 py-0.5 rounded border border-slate-700 font-mono">{{ d.code }}</span>
                            </div>
                            <div class="text-slate-400 mt-0.5">Начальник: {{ d.manager_name || 'Не назначен' }}</div>
                            <div v-if="d.description" class="text-slate-500 text-[11px] mt-0.5">{{ d.description }}</div>
                        </div>
                        <div class="flex items-center space-x-1.5">
                            <button @click="editDept(d)" class="text-slate-400 hover:text-slate-200 p-1.5 rounded hover:bg-slate-800" title="Редактировать">
                                <i data-lucide="edit" class="w-4 h-4"></i>
                            </button>
                            <button @click="deleteDept(d.id)" class="text-rose-400 hover:text-rose-300 p-1.5 rounded hover:bg-slate-800" title="Удалить">
                                <i data-lucide="trash-2" class="w-4 h-4"></i>
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 2. Job Roles Section -->
            <div class="bg-slate-800/90 rounded-2xl border border-slate-700/70 p-5 shadow space-y-4">
                <div class="flex items-center justify-between border-b border-slate-700 pb-3">
                    <div>
                        <h3 class="font-bold text-white text-base flex items-center gap-2">
                            <i data-lucide="scissors" class="w-5 h-5 text-amber-400"></i>
                            Должности и квоты отсутствий
                        </h3>
                        <p class="text-xs text-slate-400">Профессии и лимиты одновременных отпусков</p>
                    </div>
                    <button @click="openAddRole" class="bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold px-3 py-1.5 rounded-xl flex items-center gap-1.5 transition shadow">
                        <i data-lucide="plus" class="w-4 h-4"></i>
                        Добавить должность
                    </button>
                </div>

                <div class="space-y-2.5 max-h-80 overflow-y-auto">
                    <div v-for="r in roles" :key="r.id" class="flex items-center justify-between bg-slate-900/60 p-3 rounded-xl border border-slate-800 text-xs">
                        <div>
                            <div class="font-bold text-white flex items-center gap-2">
                                {{ r.name }}
                                <span class="text-[10px] bg-amber-950/40 text-amber-300 px-2 py-0.5 rounded border border-amber-800/50">
                                    Квота: {{ r.default_quota }} чел.
                                </span>
                            </div>
                            <div class="text-slate-400 mt-0.5">Цех: {{ r.department_name || 'Все подразделения' }}</div>
                            <div v-if="r.description" class="text-slate-500 text-[11px] mt-0.5">{{ r.description }}</div>
                        </div>
                        <div class="flex items-center space-x-1.5">
                            <button @click="editRole(r)" class="text-slate-400 hover:text-slate-200 p-1.5 rounded hover:bg-slate-800" title="Редактировать">
                                <i data-lucide="edit" class="w-4 h-4"></i>
                            </button>
                            <button @click="deleteRole(r.id)" class="text-rose-400 hover:text-rose-300 p-1.5 rounded hover:bg-slate-800" title="Удалить">
                                <i data-lucide="trash-2" class="w-4 h-4"></i>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- 3. Work Shifts Section -->
            <div class="bg-slate-800/90 rounded-2xl border border-slate-700/70 p-5 shadow space-y-4">
                <div class="flex items-center justify-between border-b border-slate-700 pb-3">
                    <div>
                        <h3 class="font-bold text-white text-base flex items-center gap-2">
                            <i data-lucide="clock" class="w-5 h-5 text-teal-400"></i>
                            Сменные графики (Смены)
                        </h3>
                        <p class="text-xs text-slate-400">Режимы работы швейных потоков и участков</p>
                    </div>
                    <button @click="openAddShift" class="bg-teal-600 hover:bg-teal-500 text-white text-xs font-semibold px-3 py-1.5 rounded-xl flex items-center gap-1.5 transition shadow">
                        <i data-lucide="plus" class="w-4 h-4"></i>
                        Добавить смену
                    </button>
                </div>

                <div class="space-y-2.5 max-h-72 overflow-y-auto">
                    <div v-for="s in shifts" :key="s.id" class="flex items-center justify-between bg-slate-900/60 p-3 rounded-xl border border-slate-800 text-xs">
                        <div>
                            <div class="font-bold text-white flex items-center gap-2">
                                {{ s.name }}
                                <span v-if="s.code" class="text-[10px] bg-slate-800 text-teal-300 px-1.5 py-0.5 rounded border border-slate-700 font-mono">{{ s.code }}</span>
                            </div>
                            <div v-if="s.description" class="text-slate-400 text-[11px] mt-0.5">{{ s.description }}</div>
                        </div>
                        <div class="flex items-center space-x-1.5">
                            <button @click="editShift(s)" class="text-slate-400 hover:text-slate-200 p-1.5 rounded hover:bg-slate-800" title="Редактировать">
                                <i data-lucide="edit" class="w-4 h-4"></i>
                            </button>
                            <button @click="deleteShift(s.id)" class="text-rose-400 hover:text-rose-300 p-1.5 rounded hover:bg-slate-800" title="Удалить">
                                <i data-lucide="trash-2" class="w-4 h-4"></i>
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 4. MAX Bot Administrators Card -->
            <div class="bg-slate-800/90 rounded-2xl border border-slate-700/70 p-5 shadow space-y-4">
                <div class="flex items-center justify-between border-b border-slate-700 pb-3">
                    <div>
                        <h3 class="font-bold text-white text-base flex items-center gap-2">
                            <i data-lucide="shield-alert" class="w-5 h-5 text-purple-400"></i>
                            Администраторы бота MAX
                        </h3>
                        <p class="text-xs text-slate-400">Руководители, подтверждающие номера телефонов для доступа к боту</p>
                    </div>
                    <button @click="openAddAdmin" class="bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold px-3 py-1.5 rounded-xl flex items-center gap-1.5 transition shadow">
                        <i data-lucide="plus" class="w-4 h-4"></i>
                        Добавить админа
                    </button>
                </div>

                <div class="space-y-2.5 max-h-72 overflow-y-auto">
                    <div v-for="adm in botAdmins" :key="adm.id" class="flex items-center justify-between bg-slate-900/60 p-3 rounded-xl border border-slate-800 text-xs">
                        <div>
                            <div class="font-bold text-white flex items-center gap-2">
                                {{ adm.full_name }}
                                <span class="text-[10px] bg-purple-900/40 text-purple-300 px-2 py-0.5 rounded border border-purple-700/50">{{ adm.role_title }}</span>
                            </div>
                            <div class="text-slate-400 font-mono mt-0.5">{{ adm.phone }}</div>
                        </div>
                        <div class="flex items-center space-x-1.5">
                            <button @click="deleteAdmin(adm.id)" class="text-rose-400 hover:text-rose-300 p-1.5 rounded hover:bg-slate-800" title="Удалить">
                                <i data-lucide="trash-2" class="w-4 h-4"></i>
                            </button>
                        </div>
                    </div>
                    <div v-if="!botAdmins || !botAdmins.length" class="text-xs text-slate-500 italic p-3 text-center">
                        Администраторы бота пока не добавлены. Добавьте директора или начальника цеха.
                    </div>
                </div>
            </div>
        </div>

        <!-- Modals for CRUD -->
        <!-- 1. Department Modal -->
        <div v-if="deptModalOpen" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div class="bg-slate-900 rounded-2xl border border-slate-700 p-6 max-w-md w-full shadow-2xl space-y-4 text-xs">
                <div class="flex items-center justify-between border-b border-slate-800 pb-3">
                    <h3 class="font-bold text-white text-base">{{ isEditing ? 'Редактировать цех / отдел' : 'Добавить цех / отдел' }}</h3>
                    <button @click="deptModalOpen = false" class="text-slate-400 hover:text-white text-lg">&times;</button>
                </div>
                <div class="space-y-3">
                    <div>
                        <label class="block text-slate-400 mb-1">Название цеха / отдела:</label>
                        <input v-model="deptForm.name" placeholder="Швейный цех №1" class="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-slate-200"/>
                    </div>
                    <div class="grid grid-cols-2 gap-2">
                        <div>
                            <label class="block text-slate-400 mb-1">Код цеха:</label>
                            <input v-model="deptForm.code" placeholder="SEW_1" class="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-slate-200"/>
                        </div>
                        <div>
                            <label class="block text-slate-400 mb-1">Начальник цеха:</label>
                            <input v-model="deptForm.manager_name" placeholder="Ковалева Т.И." class="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-slate-200"/>
                        </div>
                    </div>
                    <div>
                        <label class="block text-slate-400 mb-1">Описание деятельности:</label>
                        <textarea v-model="deptForm.description" rows="2" placeholder="Пошив базового ассортимента..." class="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-slate-200"></textarea>
                    </div>
                </div>
                <div class="flex items-center justify-end space-x-2 pt-3 border-t border-slate-800">
                    <button @click="deptModalOpen = false" class="px-4 py-2 rounded-xl bg-slate-800 text-slate-300">Отмена</button>
                    <button @click="saveDept" class="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold">Сохранить</button>
                </div>
            </div>
        </div>

        <!-- 2. Role Modal -->
        <div v-if="roleModalOpen" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div class="bg-slate-900 rounded-2xl border border-slate-700 p-6 max-w-md w-full shadow-2xl space-y-4 text-xs">
                <div class="flex items-center justify-between border-b border-slate-800 pb-3">
                    <h3 class="font-bold text-white text-base">{{ isEditing ? 'Редактировать должность' : 'Добавить должность' }}</h3>
                    <button @click="roleModalOpen = false" class="text-slate-400 hover:text-white text-lg">&times;</button>
                </div>
                <div class="space-y-3">
                    <div>
                        <label class="block text-slate-400 mb-1">Наименование должности:</label>
                        <input v-model="roleForm.name" placeholder="Швея (портной)" class="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-slate-200"/>
                    </div>
                    <div class="grid grid-cols-2 gap-2">
                        <div>
                            <label class="block text-slate-400 mb-1">Цех / отдел:</label>
                            <select v-model="roleForm.department_id" class="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-slate-200">
                                <option v-for="d in departments" :key="d.id" :value="d.id">{{ d.name }}</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-slate-400 mb-1">Квота отсутствий (чел.):</label>
                            <input v-model.number="roleForm.default_quota" type="number" min="1" class="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-slate-200"/>
                        </div>
                    </div>
                    <div>
                        <label class="block text-slate-400 mb-1">Описание обязанностей:</label>
                        <textarea v-model="roleForm.description" rows="2" placeholder="Обязанности..." class="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-slate-200"></textarea>
                    </div>
                </div>
                <div class="flex items-center justify-end space-x-2 pt-3 border-t border-slate-800">
                    <button @click="roleModalOpen = false" class="px-4 py-2 rounded-xl bg-slate-800 text-slate-300">Отмена</button>
                    <button @click="saveRole" class="px-4 py-2 rounded-xl bg-amber-600 hover:bg-amber-500 text-white font-semibold">Сохранить</button>
                </div>
            </div>
        </div>

        <!-- 3. WorkShift Modal -->
        <div v-if="shiftModalOpen" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div class="bg-slate-900 rounded-2xl border border-slate-700 p-6 max-w-md w-full shadow-2xl space-y-4 text-xs">
                <div class="flex items-center justify-between border-b border-slate-800 pb-3">
                    <h3 class="font-bold text-white text-base">{{ isEditing ? 'Редактировать смену' : 'Добавить смену' }}</h3>
                    <button @click="shiftModalOpen = false" class="text-slate-400 hover:text-white text-lg">&times;</button>
                </div>
                <div class="space-y-3">
                    <div>
                        <label class="block text-slate-400 mb-1">Наименование смены:</label>
                        <input v-model="shiftForm.name" placeholder="Смена 1 (дневная 07:00-15:30)" class="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-slate-200"/>
                    </div>
                    <div>
                        <label class="block text-slate-400 mb-1">Код:</label>
                        <input v-model="shiftForm.code" placeholder="SHIFT_1" class="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-slate-200"/>
                    </div>
                    <div>
                        <label class="block text-slate-400 mb-1">Описание режима работы:</label>
                        <textarea v-model="shiftForm.description" rows="2" placeholder="Время начала, окончания, перерывы..." class="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-slate-200"></textarea>
                    </div>
                </div>
                <div class="flex items-center justify-end space-x-2 pt-3 border-t border-slate-800">
                    <button @click="shiftModalOpen = false" class="px-4 py-2 rounded-xl bg-slate-800 text-slate-300">Отмена</button>
                    <button @click="saveShift" class="px-4 py-2 rounded-xl bg-teal-600 hover:bg-teal-500 text-white font-semibold">Сохранить</button>
                </div>
            </div>
        </div>

        <!-- 4. Bot Administrator Modal -->
        <div v-if="adminModalOpen" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div class="bg-slate-900 rounded-2xl border border-slate-700 p-6 max-w-md w-full shadow-2xl space-y-4 text-xs">
                <div class="flex items-center justify-between border-b border-slate-800 pb-3">
                    <h3 class="font-bold text-white text-base">Добавить администратора бота MAX</h3>
                    <button @click="adminModalOpen = false" class="text-slate-400 hover:text-white text-lg">&times;</button>
                </div>
                <div class="space-y-3">
                    <div>
                        <label class="block text-slate-400 mb-1">ФИО администратора:</label>
                        <input v-model="adminForm.full_name" placeholder="Соколов Валерий Дмитриевич" class="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-slate-200"/>
                    </div>
                    <div>
                        <label class="block text-slate-400 mb-1">Телефон (для связи и авторизации в MAX):</label>
                        <input v-model="adminForm.phone" placeholder="+79130009999" class="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-slate-200 font-mono"/>
                    </div>
                    <div>
                        <label class="block text-slate-400 mb-1">Должность в руководстве:</label>
                        <input v-model="adminForm.role_title" placeholder="Директор / Начальник цеха / Главный технолог" class="w-full bg-slate-800 border border-slate-700 rounded-lg p-2 text-slate-200"/>
                    </div>
                </div>
                <div class="flex items-center justify-end space-x-2 pt-3 border-t border-slate-800">
                    <button @click="adminModalOpen = false" class="px-4 py-2 rounded-xl bg-slate-800 text-slate-300">Отмена</button>
                    <button @click="saveAdmin" class="px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 text-white font-semibold">Добавить</button>
                </div>
            </div>
        </div>
    </div>
    `
};
