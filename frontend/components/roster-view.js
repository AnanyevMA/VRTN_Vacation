window.RosterView = {
    props: ['employees', 'departments', 'shifts', 'searchQuery', 'isSyncing'],
    emits: ['update:searchQuery', 'open-chat', 'edit-employee', 'delete-employee', 'add-employee', 'sync-google-sheets', 'toggle-bot-access'],
    methods: {
        formatEmployeeStatus(status) {
            const map = {
                'APPROVED': 'Согласован',
                'PENDING': 'На согласовании',
                'CONFLICT': 'Конфликт дат',
                'NOT_SUBMITTED': 'Не подан',
            };
            return map[status] || status;
        },
        getStatusBadgeClass(status) {
            if (status === 'APPROVED') return 'badge-approved';
            if (status === 'PENDING') return 'badge-pending';
            if (status === 'CONFLICT') return 'badge-conflict';
            return 'badge-not-submitted';
        }
    },
    template: `
    <div class="space-y-6">
        <div class="flex items-center justify-between bg-slate-800/90 p-4 rounded-2xl border border-slate-700/70 flex-wrap gap-3">
            <div class="flex items-center space-x-3 flex-1 min-w-[280px] max-w-md">
                <div class="relative w-full">
                    <i data-lucide="search" class="w-4 h-4 absolute left-3 top-3 text-slate-400"></i>
                    <input 
                        :value="searchQuery" 
                        @input="$emit('update:searchQuery', $event.target.value)"
                        placeholder="Поиск по ФИО, должности, цеху, смене..." 
                        class="w-full bg-slate-900 border border-slate-700 rounded-xl pl-9 pr-4 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                    />
                </div>
            </div>

            <div class="flex items-center space-x-3">
                <button 
                    @click="$emit('sync-google-sheets')" 
                    :disabled="isSyncing"
                    class="bg-emerald-600/80 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-xl flex items-center gap-2 transition shadow border border-emerald-500/40">
                    <i data-lucide="cloud-download" class="w-4 h-4 text-emerald-200"></i>
                    {{ isSyncing ? 'Синхронизация...' : 'Импорт из Google Таблицы' }}
                </button>
                <button 
                    @click="$emit('add-employee')" 
                    class="bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium px-4 py-2 rounded-xl flex items-center gap-2 transition shadow">
                    <i data-lucide="user-plus" class="w-4 h-4"></i>
                    Добавить сотрудника
                </button>
            </div>
        </div>

        <!-- Employees Table -->
        <div class="bg-slate-800/90 rounded-2xl border border-slate-700/70 overflow-hidden shadow">
            <table class="w-full text-left text-sm text-slate-300">
                <thead class="bg-slate-900/80 text-xs font-semibold uppercase text-slate-400 border-b border-slate-700">
                    <tr>
                        <th class="p-3.5 pl-5">Сотрудник</th>
                        <th class="p-3.5">Должность / Цех</th>
                        <th class="p-3.5">Смена</th>
                        <th class="p-3.5">Телефон / MAX ID</th>
                        <th class="p-3.5">Доступ к боту MAX</th>
                        <th class="p-3.5">Норма</th>
                        <th class="p-3.5">Статус графика</th>
                        <th class="p-3.5 pr-5 text-right">Действия</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-700/60">
                    <tr v-for="emp in employees" :key="emp.id" class="hover:bg-slate-700/30 transition">
                        <td class="p-3.5 pl-5 font-semibold text-white">
                            {{ emp.full_name }}
                            <span v-if="emp.social_priority !== 'NONE'" class="ml-1 text-[10px] bg-purple-500/20 text-purple-300 px-1.5 py-0.2 rounded border border-purple-500/30">
                                Льготник
                            </span>
                        </td>
                        <td class="p-3.5">
                            <div class="text-slate-200 font-medium">{{ emp.role }}</div>
                            <div class="text-xs text-slate-400">{{ emp.department_name }}</div>
                        </td>
                        <td class="p-3.5">
                            <span class="text-xs text-amber-300 bg-amber-950/40 px-2 py-0.5 rounded border border-amber-800/50">
                                {{ emp.shift || 'Смена 1 (дневная)' }}
                            </span>
                        </td>
                        <td class="p-3.5 font-mono text-xs">
                            <div>{{ emp.phone }}</div>
                            <div class="text-slate-500 text-[11px]">{{ emp.max_user_id || 'не привязан' }}</div>
                        </td>
                        <td class="p-3.5">
                            <div class="flex items-center space-x-1.5">
                                <span v-if="emp.bot_access === 'APPROVED'" class="text-[11px] font-semibold text-emerald-400 bg-emerald-950/40 px-2 py-0.5 rounded border border-emerald-800/50 flex items-center gap-1">
                                    <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> Одобрен
                                </span>
                                <span v-else-if="emp.bot_access === 'PENDING'" class="text-[11px] font-semibold text-amber-300 bg-amber-950/40 px-2 py-0.5 rounded border border-amber-800/50 flex items-center gap-1">
                                    <span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span> Ожидает
                                </span>
                                <span v-else class="text-[11px] font-semibold text-rose-400 bg-rose-950/40 px-2 py-0.5 rounded border border-rose-800/50 flex items-center gap-1">
                                    <span class="w-1.5 h-1.5 rounded-full bg-rose-400"></span> Блок
                                </span>

                                <button 
                                    v-if="emp.bot_access !== 'APPROVED'" 
                                    @click="$emit('toggle-bot-access', emp, 'APPROVED')" 
                                    class="text-[10px] bg-emerald-600 hover:bg-emerald-500 text-white px-2 py-0.5 rounded transition"
                                    title="Одобрить доступ к боту">
                                    Одобрить
                                </button>
                                <button 
                                    v-else 
                                    @click="$emit('toggle-bot-access', emp, 'BLOCKED')" 
                                    class="text-[10px] bg-slate-800 hover:bg-rose-900 text-slate-400 hover:text-rose-200 px-2 py-0.5 rounded border border-slate-700 transition"
                                    title="Заблокировать доступ к боту">
                                    Блок
                                </button>
                            </div>
                        </td>
                        <td class="p-3.5">
                            <span class="text-xs font-bold text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20">{{ emp.total_vacation_days }} дн.</span>
                        </td>
                        <td class="p-3.5">
                            <span :class="getStatusBadgeClass(emp.status_summary)" class="px-2.5 py-1 rounded-full text-xs font-medium border inline-block">
                                {{ formatEmployeeStatus(emp.status_summary) }}
                            </span>
                        </td>
                        <td class="p-3.5 pr-5 text-right space-x-2">
                            <button @click="$emit('open-chat', emp)" class="text-indigo-400 hover:text-indigo-300 p-1 rounded hover:bg-slate-700" title="Тест в MAX">
                                <i data-lucide="message-circle" class="w-4 h-4 inline"></i>
                            </button>
                            <button @click="$emit('edit-employee', emp)" class="text-slate-400 hover:text-slate-200 p-1 rounded hover:bg-slate-700" title="Редактировать">
                                <i data-lucide="edit" class="w-4 h-4 inline"></i>
                            </button>
                            <button @click="$emit('delete-employee', emp.id)" class="text-rose-400 hover:text-rose-300 p-1 rounded hover:bg-slate-700" title="Удалить">
                                <i data-lucide="trash-2" class="w-4 h-4 inline"></i>
                            </button>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
    `
};
