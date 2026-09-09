window.GanttView = {
    props: [
        'employees', 'departments', 'shifts', 'vacationSlots', 'blackoutsList',
        'selectedYear', 'isBatchProcessing'
    ],
    emits: ['update:selectedYear', 'open-chat', 'select-slot', 'run-batch-approve', 'open-rules'],
    data() {
        return {
            filterDept: '',
            filterShift: '',
            filterStatus: '',
            monthNames: ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек'],
        };
    },
    computed: {
        filteredEmployees() {
            return this.employees.filter(emp => {
                const matchDept = !this.filterDept || emp.department_id === Number(this.filterDept);
                const matchShift = !this.filterShift || emp.shift === this.filterShift;
                const matchStatus = !this.filterStatus || emp.status_summary === this.filterStatus;
                return matchDept && matchShift && matchStatus;
            });
        },
        yearOptions() {
            const current = new Date().getFullYear();
            return [2025, 2026, 2027, 2028, 2029, 2030];
        }
    },
    methods: {
        changeYear(delta) {
            const nextYear = Number(this.selectedYear) + delta;
            this.$emit('update:selectedYear', nextYear);
        },
        onYearSelect(e) {
            this.$emit('update:selectedYear', Number(e.target.value));
        },
        getEmployeeSlots(empId) {
            const targetYear = Number(this.selectedYear);
            return this.vacationSlots.filter(s => {
                if (s.employee_id !== empId) return false;
                const st = new Date(s.start_date);
                const en = new Date(s.end_date);
                return st.getFullYear() === targetYear || en.getFullYear() === targetYear;
            });
        },
        getSlotStyle(slot) {
            const st = new Date(slot.start_date);
            const en = new Date(slot.end_date);
            const targetYear = Number(this.selectedYear);
            const startOfYear = new Date(targetYear, 0, 1);
            const isLeap = (targetYear % 4 === 0 && targetYear % 100 !== 0) || (targetYear % 400 === 0);
            const totalYearDays = isLeap ? 366 : 365;

            // Clamping to current selected year
            const effStart = st < startOfYear ? startOfYear : st;
            const endOfYear = new Date(targetYear, 11, 31);
            const effEnd = en > endOfYear ? endOfYear : en;

            const dayStart = Math.max(0, Math.floor((effStart - startOfYear) / (1000 * 60 * 60 * 24)));
            const dayEnd = Math.min(totalYearDays, Math.floor((effEnd - startOfYear) / (1000 * 60 * 60 * 24)) + 1);

            const leftPct = (dayStart / totalYearDays) * 100;
            const widthPct = Math.max(1.8, ((dayEnd - dayStart) / totalYearDays) * 100);

            return {
                left: `${leftPct}%`,
                width: `${widthPct}%`,
            };
        },
        getSlotClass(slot) {
            if (slot.status === 'APPROVED') return 'slot-approved';
            if (slot.status === 'CONFLICT') return 'slot-conflict';
            if (slot.status === 'REVISED') return 'slot-revised';
            return 'slot-requested';
        },
        formatDateShort(dStr) {
            if (!dStr) return '';
            const d = new Date(dStr);
            return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}`;
        },
        formatDateRu(dStr) {
            if (!dStr) return '';
            return new Date(dStr).toLocaleDateString('ru-RU');
        }
    },
    template: `
    <div class="space-y-6">
        <!-- Gantt Toolbar with Multi-Year Navigation -->
        <div class="flex flex-wrap items-center justify-between gap-4 bg-slate-800/90 p-4 rounded-2xl border border-slate-700/70 shadow-sm">
            <!-- Year Selector Control -->
            <div class="flex items-center space-x-2 bg-slate-900/90 px-3 py-1.5 rounded-xl border border-slate-700">
                <button @click="changeYear(-1)" class="p-1 rounded hover:bg-slate-800 text-slate-300 hover:text-white" title="Предыдущий год">
                    <i data-lucide="chevron-left" class="w-4 h-4"></i>
                </button>
                <div class="flex items-center gap-1.5 font-bold text-base text-indigo-400">
                    <i data-lucide="calendar" class="w-4 h-4"></i>
                    <select :value="selectedYear" @change="onYearSelect" class="bg-transparent text-white font-bold text-base focus:outline-none cursor-pointer">
                        <option v-for="y in yearOptions" :key="y" :value="y" class="bg-slate-900 text-white">{{ y }} год</option>
                    </select>
                </div>
                <button @click="changeYear(1)" class="p-1 rounded hover:bg-slate-800 text-slate-300 hover:text-white" title="Следующий год">
                    <i data-lucide="chevron-right" class="w-4 h-4"></i>
                </button>
            </div>

            <!-- Filters -->
            <div class="flex items-center space-x-3 flex-wrap gap-2">
                <div class="flex items-center space-x-2">
                    <span class="text-xs font-semibold text-slate-300">Цех / Отдел:</span>
                    <select v-model="filterDept" class="bg-slate-900 text-slate-200 text-xs border border-slate-700 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-indigo-500">
                        <option value="">Все цехи и службы</option>
                        <option v-for="d in departments" :key="d.id" :value="d.id">{{ d.name }}</option>
                    </select>
                </div>

                <div class="flex items-center space-x-2">
                    <span class="text-xs font-semibold text-slate-300">Смена:</span>
                    <select v-model="filterShift" class="bg-slate-900 text-slate-200 text-xs border border-slate-700 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-indigo-500">
                        <option value="">Все смены</option>
                        <option v-for="s in shifts" :key="s.id" :value="s.name">{{ s.name }}</option>
                    </select>
                </div>

                <div class="flex items-center space-x-2">
                    <span class="text-xs font-semibold text-slate-300">Статус:</span>
                    <select v-model="filterStatus" class="bg-slate-900 text-slate-200 text-xs border border-slate-700 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-indigo-500">
                        <option value="">Все статусы</option>
                        <option value="APPROVED">Согласовано</option>
                        <option value="REQUESTED">На рассмотрении</option>
                        <option value="CONFLICT">Конфликт дат</option>
                    </select>
                </div>
            </div>

            <!-- Batch Optimization Action -->
            <div class="flex items-center space-x-3">
                <button 
                    @click="$emit('run-batch-approve')" 
                    :disabled="isBatchProcessing"
                    class="bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white text-xs font-semibold px-4 py-2 rounded-xl shadow flex items-center gap-1.5 transition disabled:opacity-50">
                    <i data-lucide="zap" class="w-4 h-4 text-amber-300"></i>
                    {{ isBatchProcessing ? 'Оптимизация...' : '⚡ Утвердить все валидные (' + selectedYear + ')' }}
                </button>
            </div>
        </div>

        <!-- Blackout Info Banner -->
        <div v-if="blackoutsList.length" class="bg-amber-950/30 border border-amber-800/40 rounded-xl p-3 flex items-center justify-between text-xs text-amber-300">
            <div class="flex items-center gap-2 overflow-x-auto">
                <i data-lucide="lock" class="w-4 h-4 text-amber-400 flex-shrink-0"></i>
                <span><strong>Пиковые сезоны фабрики (Blackout):</strong> 
                    <span v-for="(b, idx) in blackoutsList" :key="idx" class="ml-2 inline-block bg-amber-900/50 px-2 py-0.5 rounded border border-amber-700/50">
                        {{ b.name }} ({{ formatDateRu(b.start) }} – {{ formatDateRu(b.end) }})
                    </span>
                </span>
            </div>
            <button @click="$emit('open-rules')" class="text-amber-400 underline hover:text-amber-200 ml-2 whitespace-nowrap">Настроить</button>
        </div>

        <!-- Custom Interactive Gantt Matrix -->
        <div class="bg-slate-800/90 rounded-2xl border border-slate-700/70 shadow-xl overflow-x-auto">
            <div class="min-w-[1200px] p-4">
                <!-- Month Header -->
                <div class="grid grid-cols-12 gap-1 border-b border-slate-700 pb-3 mb-2 text-center text-xs font-bold text-slate-300">
                    <div class="col-span-3 text-left pl-2 flex items-center justify-between">
                        <span>Сотрудник / Цех / Должность</span>
                        <span class="text-indigo-400 mr-3">{{ selectedYear }} г.</span>
                    </div>
                    <div class="col-span-9 grid grid-cols-12 gap-1">
                        <div v-for="m in monthNames" :key="m" class="bg-slate-900/80 py-1.5 rounded text-slate-300 border border-slate-800">
                            {{ m }}
                        </div>
                    </div>
                </div>

                <!-- Employee Rows -->
                <div class="space-y-3 pt-1">
                    <div 
                        v-for="emp in filteredEmployees" 
                        :key="emp.id"
                        class="grid grid-cols-12 gap-1 items-center bg-slate-900/50 hover:bg-slate-900/80 p-2.5 rounded-xl border border-slate-800/80 transition">
                        <!-- Left Profile Column -->
                        <div class="col-span-3 pr-3 flex items-center justify-between">
                            <div>
                                <div class="font-semibold text-sm text-slate-100 flex items-center gap-1.5">
                                    {{ emp.full_name }}
                                    <span v-if="emp.social_priority !== 'NONE'" class="text-[10px] bg-purple-500/20 text-purple-300 px-1.5 py-0.2 rounded border border-purple-500/30">
                                        Льготник
                                    </span>
                                </div>
                                <div class="text-[11px] text-slate-400 flex items-center gap-1.5 flex-wrap">
                                    <span class="text-slate-300 font-medium">{{ emp.role }}</span>
                                    <span class="text-slate-600">•</span>
                                    <span class="text-slate-400">{{ emp.department_name }}</span>
                                </div>
                                <div class="text-[10px] text-amber-400/90 font-mono mt-0.5">
                                    {{ emp.shift }} • {{ emp.total_vacation_days }} дн.
                                </div>
                            </div>
                            <button 
                                @click="$emit('open-chat', emp)" 
                                title="Диалог с сотрудником в MAX"
                                class="p-1.5 rounded-lg bg-slate-800 hover:bg-indigo-600 text-slate-400 hover:text-white transition">
                                <i data-lucide="message-square" class="w-4 h-4"></i>
                            </button>
                        </div>

                        <!-- Gantt Timeline Bars -->
                        <div class="col-span-9 relative h-10 bg-slate-950/60 rounded-lg border border-slate-800/80 flex items-center px-1 overflow-hidden">
                            <!-- 12 Month grid dividers -->
                            <div class="absolute inset-0 grid grid-cols-12 pointer-events-none">
                                <div v-for="i in 12" :key="i" class="border-r border-slate-800/50 h-full"></div>
                            </div>

                            <!-- Vacation Slot Bars -->
                            <div 
                                v-for="slot in getEmployeeSlots(emp.id)" 
                                :key="slot.id"
                                @click="$emit('select-slot', slot)"
                                :style="getSlotStyle(slot)"
                                :class="getSlotClass(slot)"
                                class="absolute h-7 rounded-md text-[11px] font-semibold px-2 flex items-center justify-between cursor-pointer shadow-md transition-transform hover:scale-[1.02] hover:z-20">
                                <span class="truncate">{{ formatDateShort(slot.start_date) }} - {{ formatDateShort(slot.end_date) }}</span>
                                <span class="ml-1 text-[10px] opacity-90">{{ slot.days_count }}д</span>
                            </div>

                            <!-- Empty hint -->
                            <div v-if="!getEmployeeSlots(emp.id).length" class="text-xs text-slate-600 pl-3 italic">
                                Нет запланированных отпусков на {{ selectedYear }} год
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Legend -->
                <div class="mt-6 pt-4 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
                    <div class="flex items-center space-x-6">
                        <div class="flex items-center gap-2">
                            <div class="w-4 h-4 rounded bg-emerald-600 border border-emerald-400"></div>
                            <span>Утверждено (Approved)</span>
                        </div>
                        <div class="flex items-center gap-2">
                            <div class="w-4 h-4 rounded bg-amber-500 border border-amber-300"></div>
                            <span>На рассмотрении (Requested)</span>
                        </div>
                        <div class="flex items-center gap-2">
                            <div class="w-4 h-4 rounded bg-rose-600 border border-rose-400"></div>
                            <span>Конфликт по смене/цеху (Conflict)</span>
                        </div>
                    </div>
                    <div class="text-slate-500">
                        Клик по блоку отпуска открывает окно согласования
                    </div>
                </div>
            </div>
        </div>
    </div>
    `
};
