window.ChatView = {
    props: [
        'employees', 'selectedEmployeeId', 'currentEmployee', 'chatMessages',
        'userInput', 'isTyping', 'selectedYear'
    ],
    emits: [
        'update:selectedEmployeeId', 'update:userInput', 'send-message',
        'choose-alternative', 'clear-chat', 'set-input-text', 'confirm-submission'
    ],
    computed: {
        draftSlots() {
            // Find the latest message carrying draft state
            for (let i = this.chatMessages.length - 1; i >= 0; i--) {
                const p = this.chatMessages[i].payload;
                if (!p) continue;
                if (p.action === 'DRAFT_RESET' || p.action === 'SUBMISSION_CONFIRMED') {
                    return [];
                }
                if (Array.isArray(p.draft_slots)) {
                    return p.draft_slots;
                }
            }
            return [];
        },
        draftTotalDays() {
            return this.draftSlots.reduce((acc, s) => acc + (s.days || 0), 0);
        },
        expectedDays() {
            return this.currentEmployee?.total_vacation_days || 36;
        },
        draftProgressPct() {
            return Math.min(100, (this.draftTotalDays / this.expectedDays) * 100);
        }
    },
    methods: {
        formatTime(ts) {
            if (!ts) return '';
            const d = new Date(ts);
            return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
        },
        formatDateShort(dStr) {
            if (!dStr) return '';
            const d = new Date(dStr);
            return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()}`;
        },
        formatAltDates(slots) {
            if (!slots || !slots.length) return '';
            return slots.map(s => {
                const st = new Date(s.start);
                const en = new Date(s.end);
                return `${String(st.getDate()).padStart(2, '0')}.${String(st.getMonth() + 1).padStart(2, '0')} – ${String(en.getDate()).padStart(2, '0')}.${String(en.getMonth() + 1).padStart(2, '0')}`;
            }).join(', ');
        },
        formatMessageText(txt) {
            if (!txt) return '';
            let escaped = txt
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;");
            escaped = escaped.replace(/\*\*([^\n*]+?)\*\*/g, '<strong>$1</strong>');
            escaped = escaped.replace(/\*([^\n*]+?)\*/g, '<em>$1</em>');
            return escaped;
        }
    },
    template: `
    <div class="flex justify-center items-start py-2">
        <div class="w-full max-w-2xl bg-slate-950 rounded-3xl border-4 border-slate-800 shadow-2xl overflow-hidden flex flex-col h-[760px]">
            <!-- Phone Messenger Header -->
            <div class="bg-gradient-to-r from-blue-700 to-indigo-800 p-4 text-white flex items-center justify-between border-b border-indigo-600/50 shadow-md">
                <div class="flex items-center space-x-3">
                    <div class="relative">
                        <div class="w-11 h-11 rounded-full bg-white/20 flex items-center justify-center font-bold text-base shadow">
                            MAX
                        </div>
                        <span class="w-3.5 h-3.5 rounded-full bg-emerald-400 border-2 border-indigo-800 absolute bottom-0 right-0"></span>
                    </div>
                    <div>
                        <h3 class="font-bold text-sm leading-tight flex items-center gap-1.5">
                            Бот Графика Отпусков
                            <i data-lucide="badge-check" class="w-4 h-4 text-sky-300 inline"></i>
                        </h3>
                        <div class="text-[11px] text-blue-200">Швейная фабрика • в сети</div>
                    </div>
                </div>

                <!-- Switch Employee Inside Phone -->
                <div class="text-right">
                    <div class="text-[10px] text-blue-200 mb-0.5">Сотрудник:</div>
                    <select 
                        :value="selectedEmployeeId" 
                        @change="$emit('update:selectedEmployeeId', Number($event.target.value))" 
                        class="bg-indigo-900/90 text-white text-xs rounded-lg px-2.5 py-1 border border-indigo-400/50 focus:outline-none">
                        <option v-for="e in employees" :key="e.id" :value="e.id">
                            {{ e.full_name.split(' ')[0] }} {{ e.full_name.split(' ')[1] }} ({{ e.role }})
                        </option>
                    </select>
                </div>
            </div>

            <!-- Employee Context Info Banner -->
            <div class="bg-slate-900/95 px-4 py-2.5 border-b border-slate-800 flex items-center justify-between text-xs text-slate-300">
                <div class="space-y-0.5">
                    <div class="flex items-center gap-2">
                        <span class="font-bold text-slate-100">{{ currentEmployee?.full_name }}</span>
                        <span class="text-slate-500">•</span>
                        <span class="text-slate-400">{{ currentEmployee?.department_name }}</span>
                    </div>
                    <div class="text-[11px] text-amber-400/90">
                        {{ currentEmployee?.role }} • {{ currentEmployee?.shift }}
                    </div>
                </div>
                <div class="flex items-center gap-2">
                    <span class="bg-indigo-900/40 text-indigo-300 px-2 py-0.5 rounded border border-indigo-700/50 text-[11px] font-mono">
                        Норма: {{ expectedDays }} дн.
                    </span>
                    <button @click="$emit('clear-chat')" title="Сбросить диалог и черновик" class="text-slate-400 hover:text-rose-400 p-1">
                        <i data-lucide="rotate-ccw" class="w-4 h-4"></i>
                    </button>
                </div>
            </div>

            <!-- Accumulative Draft Meter Bar -->
            <div v-if="draftSlots.length > 0" class="bg-slate-900/80 px-4 py-2 border-b border-slate-800 text-xs">
                <div class="flex items-center justify-between text-[11px] mb-1">
                    <span class="text-slate-300 font-semibold flex items-center gap-1">
                        <i data-lucide="edit" class="w-3.5 h-3.5 text-amber-400"></i>
                        Накопительный черновик: {{ draftTotalDays }} из {{ expectedDays }} дней
                    </span>
                    <span :class="draftTotalDays === expectedDays ? 'text-emerald-400 font-bold' : 'text-amber-400 font-bold'">
                        {{ draftTotalDays === expectedDays ? 'Готов к подтверждению ✅' : 'Осталось: ' + (expectedDays - draftTotalDays) + ' дн.' }}
                    </span>
                </div>
                <!-- Progress Bar -->
                <div class="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                    <div 
                        class="h-full rounded-full transition-all duration-500"
                        :class="draftTotalDays === expectedDays ? 'bg-emerald-500' : (draftTotalDays > expectedDays ? 'bg-rose-500' : 'bg-amber-500')"
                        :style="{ width: draftProgressPct + '%' }">
                    </div>
                </div>
            </div>

            <!-- Messages Scroll Area -->
            <div ref="chatBox" class="flex-1 p-4 overflow-y-auto space-y-3.5 bg-slate-950/70">
                <div v-for="msg in chatMessages" :key="msg.id" class="flex flex-col" :class="msg.sender === 'USER' ? 'items-end' : 'items-start'">
                    <!-- Message Bubble -->
                    <div 
                        :class="msg.sender === 'USER' ? 'bg-indigo-600 text-white rounded-2xl rounded-tr-none' : 'bg-slate-900 text-slate-100 border border-slate-800 rounded-2xl rounded-tl-none'"
                        class="max-w-[88%] p-3.5 shadow-md text-xs leading-relaxed">
                        <div class="whitespace-pre-wrap" v-html="formatMessageText(msg.text)"></div>

                        <!-- Confirmation Action Card (When 36 days accumulated) -->
                        <div v-if="msg.payload && msg.payload.show_confirm_buttons" class="mt-3.5 space-y-2 border-t border-slate-800 pt-3">
                            <button 
                                @click="$emit('confirm-submission')"
                                class="w-full bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white p-2.5 rounded-xl font-bold text-xs flex items-center justify-center gap-2 shadow-lg transition">
                                <i data-lucide="check-circle" class="w-4 h-4"></i>
                                ✅ Подтвердить и отправить руководителю
                            </button>
                            <button 
                                @click="$emit('send-message', 'Сброс')"
                                class="w-full bg-slate-800 hover:bg-slate-700 text-slate-300 p-2 rounded-xl text-xs flex items-center justify-center gap-1 transition border border-slate-700/60">
                                <i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i>
                                🔄 Сбросить и ввести заново
                            </button>
                        </div>

                        <!-- Action Buttons (Alternatives on Conflict) -->
                        <div v-if="msg.payload && msg.payload.suggested_alternatives" class="mt-3 space-y-2 border-t border-slate-800 pt-2.5">
                            <div class="text-[11px] font-bold text-indigo-300">⚡ Доступные альтернативные окна цеха:</div>
                            <button 
                                v-for="alt in msg.payload.suggested_alternatives" 
                                :key="alt.option"
                                @click="$emit('choose-alternative', alt.option)"
                                class="w-full text-left bg-slate-800/90 hover:bg-indigo-600/50 p-2.5 rounded-xl border border-slate-700/60 hover:border-indigo-500 transition text-[11px] text-slate-200">
                                <div class="font-bold text-white flex items-center justify-between">
                                    <span>Вариант {{ alt.option }}: {{ formatAltDates(alt.slots) }}</span>
                                    <span class="text-emerald-400 text-[10px]">{{ alt.total_days }} дн.</span>
                                </div>
                                <div class="text-slate-400 text-[10px]">{{ alt.reason }}</div>
                            </button>
                        </div>
                    </div>
                    <span class="text-[10px] text-slate-600 mt-1 px-1">
                        {{ formatTime(msg.timestamp) }}
                    </span>
                </div>

                <!-- Typing Indicator -->
                <div v-if="isTyping" class="flex items-center space-x-2 bg-slate-900 border border-slate-800 rounded-2xl rounded-tl-none p-3 max-w-[120px]">
                    <div class="w-2 h-2 rounded-full bg-indigo-400 animate-bounce"></div>
                    <div class="w-2 h-2 rounded-full bg-indigo-400 animate-bounce" style="animation-delay: 0.2s"></div>
                    <div class="w-2 h-2 rounded-full bg-indigo-400 animate-bounce" style="animation-delay: 0.4s"></div>
                </div>
            </div>

            <!-- Quick Suggestions Prompt Bar -->
            <div class="bg-slate-900/70 px-3 py-2 border-t border-slate-800/60 flex items-center space-x-2 overflow-x-auto text-[11px]">
                <span class="text-slate-500 whitespace-nowrap text-[10px]">Накопительно:</span>
                <button @click="$emit('set-input-text', 'с 1 по 14 июля 2027')" class="whitespace-nowrap bg-slate-800 hover:bg-slate-700 text-slate-300 px-2.5 py-1 rounded-full border border-slate-700 transition">
                    1. «1-14 июля 2027» (14д)
                </button>
                <button @click="$emit('set-input-text', 'и с 1 по 22 сентября 2027')" class="whitespace-nowrap bg-slate-800 hover:bg-slate-700 text-slate-300 px-2.5 py-1 rounded-full border border-slate-700 transition">
                    2. «1-22 сентября 2027» (22д)
                </button>
                <button @click="$emit('set-input-text', 'Хочу с 1 по 14 июля 2027 и с 1 по 22 сентября 2027')" class="whitespace-nowrap bg-slate-800 hover:bg-slate-700 text-slate-300 px-2.5 py-1 rounded-full border border-slate-700 transition">
                    Сразу целиком (36д)
                </button>
                <button @click="$emit('set-input-text', 'Сброс')" class="whitespace-nowrap bg-slate-800 hover:bg-slate-700 text-rose-300 px-2 py-1 rounded-full border border-rose-800/50 transition">
                    Сброс
                </button>
            </div>

            <!-- Message Input Box -->
            <form @submit.prevent="$emit('send-message')" class="p-3 bg-slate-900 border-t border-slate-800 flex items-center space-x-2">
                <input 
                    :value="userInput" 
                    @input="$emit('update:userInput', $event.target.value)"
                    placeholder="Напишите период отпуска (напр., с 1 по 14 июля 2027)..." 
                    class="flex-1 bg-slate-950 border border-slate-700/80 rounded-2xl px-4 py-2.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                />
                <button 
                    type="submit" 
                    :disabled="!userInput.trim()" 
                    class="w-10 h-10 rounded-2xl bg-indigo-600 hover:bg-indigo-500 text-white flex items-center justify-center shadow-md disabled:opacity-40 transition">
                    <i data-lucide="send" class="w-4 h-4"></i>
                </button>
            </form>
        </div>
    </div>
    `
};
