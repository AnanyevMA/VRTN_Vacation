const { createApp, ref, computed, onMounted, nextTick, watch } = Vue;

const API_BASE = (window.__APP_BASE__ || '') + '/api/miniapp';

function detectMaxUserId() {
    // 1. Check URL query parameters (?user_id=... or ?max_user_id=...)
    const params = new URLSearchParams(window.location.search);
    const qUid = params.get('max_user_id') || params.get('user_id');
    if (qUid && qUid.trim()) {
        localStorage.setItem('vacation_miniapp_uid', qUid.trim());
        return qUid.trim();
    }

    // 2. Check MAX WebApp SDK (window.WebApp.initDataUnsafe.user)
    try {
        if (window.WebApp) {
            if (typeof window.WebApp.ready === 'function') {
                window.WebApp.ready();
            }
            const u = window.WebApp.initDataUnsafe && window.WebApp.initDataUnsafe.user;
            if (u && (u.id || u.user_id)) {
                const uid = String(u.id || u.user_id).trim();
                localStorage.setItem('vacation_miniapp_uid', uid);
                return uid;
            }
        }
    } catch (_) {}

    // 3. Check Telegram-compatible WebApp bridge
    try {
        if (window.Telegram && window.Telegram.WebApp) {
            const u = window.Telegram.WebApp.initDataUnsafe && window.Telegram.WebApp.initDataUnsafe.user;
            if (u && (u.id || u.user_id)) {
                const uid = String(u.id || u.user_id).trim();
                localStorage.setItem('vacation_miniapp_uid', uid);
                return uid;
            }
        }
    } catch (_) {}

    // 4. Check URL hash (#WebAppData=...)
    try {
        if (window.location.hash && window.location.hash.includes('user')) {
            const hashParams = new URLSearchParams(window.location.hash.slice(1));
            const rawData = hashParams.get('WebAppData') || hashParams.get('tgWebAppData');
            if (rawData) {
                const innerParams = new URLSearchParams(rawData);
                const userJson = innerParams.get('user');
                if (userJson) {
                    const uObj = JSON.parse(userJson);
                    if (uObj && (uObj.id || uObj.user_id)) {
                        const uid = String(uObj.id || uObj.user_id).trim();
                        localStorage.setItem('vacation_miniapp_uid', uid);
                        return uid;
                    }
                }
            }
        }
    } catch (_) {}

    // 5. Fallback to localStorage
    return localStorage.getItem('vacation_miniapp_uid') || '';
}

createApp({
    setup() {
        const activeTab = ref('my');
        const selectedYear = ref(2026);
        const maxUserId = ref(detectMaxUserId());
        const adminToken = ref(localStorage.getItem('vacation_admin_token') || '');

        const loading = ref(false);
        const submitting = ref(false);
        const statusBanner = ref({ text: '', type: 'info' });

        const isAdmin = ref(false);
        const employee = ref(null);
        const mySlots = ref([]);
        const draftSlots = ref([]);
        const blackouts = ref([]);
        const departments = ref([]);
        const shifts = ref([]);
        const companySchedule = ref([]);
        const adminData = ref(null);

        // Date form state
        const formStart = ref(`${selectedYear.value}-07-01`);
        const formEnd = ref(`${selectedYear.value}-07-14`);
        const alternatives = ref([]);

        // All vacations tab filters
        const scheduleSearch = ref('');
        const scheduleShiftFilter = ref('');
        const scheduleMonthFilter = ref(0);
        const monthNames = [
            'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
            'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'
        ];

        const refreshIcons = () => {
            nextTick(() => {
                if (window.lucide) window.lucide.createIcons();
            });
        };

        const showBanner = (text, type = 'info') => {
            statusBanner.value = { text, type };
            refreshIcons();
        };

        const getHeaders = () => {
            const h = { 'Content-Type': 'application/json' };
            if (adminToken.value) {
                h['X-Admin-Token'] = adminToken.value;
            }
            return h;
        };

        const loadContext = async (empId = null) => {
            loading.value = true;
            try {
                // Re-check MAX WebApp bridge in case SDK finished initializing after script load
                if (!maxUserId.value) {
                    const detected = detectMaxUserId();
                    if (detected) maxUserId.value = detected;
                }
                const q = new URLSearchParams({
                    year: String(selectedYear.value),
                });
                if (maxUserId.value) {
                    q.set('max_user_id', maxUserId.value);
                }
                if (empId) {
                    q.set('employee_id', String(empId));
                }
                const res = await fetch(`${API_BASE}/context?${q.toString()}`, {
                    headers: getHeaders(),
                });
                if (!res.ok) return;
                const data = await res.json();

                if (data.resolved_max_user_id) {
                    maxUserId.value = data.resolved_max_user_id;
                    localStorage.setItem('vacation_miniapp_uid', data.resolved_max_user_id);
                }

                isAdmin.value = Boolean(data.is_admin);
                employee.value = data.employee || null;
                mySlots.value = data.my_slots || [];
                draftSlots.value = data.draft_slots || [];
                blackouts.value = data.blackouts || [];
                departments.value = data.departments || [];
                shifts.value = data.shifts || [];
                companySchedule.value = data.company_schedule || [];
                adminData.value = data.admin || null;

                if (!employee.value && isAdmin.value && activeTab.value === 'my') {
                    activeTab.value = 'admin';
                }
            } catch (err) {
                console.error('MiniApp loadContext error:', err);
            } finally {
                loading.value = false;
                refreshIcons();
            }
        };

        const selectEmployeeFallback = async (empId) => {
            await loadContext(empId);
            if (!employee.value) {
                showBanner('Отправьте ваш контакт кнопкой в чате бота MAX, чтобы привязать аккаунт.', 'error');
            }
        };

        const changeYear = async (yr) => {
            selectedYear.value = yr;
            formStart.value = `${yr}-07-01`;
            formEnd.value = `${yr}-07-14`;
            alternatives.value = [];
            await loadContext();
        };

        const computedSelectedDays = computed(() => {
            if (!formStart.value || !formEnd.value) return 0;
            const d1 = new Date(formStart.value);
            const d2 = new Date(formEnd.value);
            const diff = Math.round((d2 - d1) / (1000 * 60 * 60 * 24)) + 1;
            return diff > 0 ? diff : 0;
        });

        const applyDurationPreset = (days) => {
            if (!formStart.value) {
                formStart.value = `${selectedYear.value}-07-01`;
            }
            const d = new Date(formStart.value);
            d.setDate(d.getDate() + days - 1);
            formEnd.value = d.toISOString().split('T')[0];
        };

        const onStartDateChange = () => {
            if (formStart.value && (!formEnd.value || formEnd.value < formStart.value)) {
                applyDurationPreset(14);
            }
        };

        const acceptConsent = async () => {
            if (!maxUserId.value) return;
            submitting.value = true;
            try {
                const res = await fetch(`${API_BASE}/consent`, {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({ max_user_id: maxUserId.value, accepted: true }),
                });
                if (res.ok) {
                    showBanner('Согласие 152-ФЗ подтверждено! Теперь вы можете выбирать даты отпуска.', 'info');
                    await loadContext();
                }
            } finally {
                submitting.value = false;
            }
        };

        const addPeriodToDraft = async () => {
            if (!maxUserId.value || !formStart.value || !formEnd.value) return;
            submitting.value = true;
            alternatives.value = [];
            statusBanner.value.text = '';
            try {
                const res = await fetch(`${API_BASE}/draft/add`, {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({
                        max_user_id: maxUserId.value,
                        start_date: formStart.value,
                        end_date: formEnd.value,
                    }),
                });
                const data = await res.json();
                if (!res.ok) {
                    showBanner(data.detail || 'Ошибка при добавлении периода', 'error');
                    return;
                }
                const p = data.payload || {};
                if (p.action === 'OFFER_ALTERNATIVES' || (p.violations && p.violations.length > 0)) {
                    showBanner((p.violations || [data.text]).join('\n'), 'error');
                    alternatives.value = p.suggested_alternatives || [];
                } else {
                    showBanner('Период проверен и добавлен в черновик!', 'info');
                }
                await loadContext();
            } finally {
                submitting.value = false;
            }
        };

        const selectAlternative = async (alt) => {
            formStart.value = alt.start;
            formEnd.value = alt.end;
            alternatives.value = [];
            await addPeriodToDraft();
        };

        const removeDraftSlot = async (idx) => {
            if (!maxUserId.value) return;
            await fetch(`${API_BASE}/draft/remove`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({ max_user_id: maxUserId.value, index: idx }),
            });
            await loadContext();
        };

        const clearDraft = async () => {
            if (!maxUserId.value) return;
            await fetch(`${API_BASE}/draft/remove`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({ max_user_id: maxUserId.value, reset_all: true }),
            });
            alternatives.value = [];
            await loadContext();
        };

        const submitDraft = async () => {
            if (!maxUserId.value) return;
            submitting.value = true;
            try {
                const res = await fetch(`${API_BASE}/draft/submit`, {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({ max_user_id: maxUserId.value }),
                });
                const data = await res.json();
                const p = data.payload || {};
                if (p.action === 'COMMITTED') {
                    showBanner('✅ Заявка успешно отправлена руководителю и добавлена в график!', 'info');
                } else {
                    showBanner(data.text || 'Проверьте требования ТК РФ перед отправкой.', 'error');
                }
                await loadContext();
            } finally {
                submitting.value = false;
            }
        };

        const handleSlotAction = async (slotId, action) => {
            submitting.value = true;
            try {
                const res = await fetch(`${API_BASE}/admin/slot-action`, {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({
                        max_user_id: maxUserId.value,
                        slot_id: slotId,
                        action,
                    }),
                });
                if (res.ok) {
                    showBanner(
                        action === 'APPROVE'
                            ? '✅ Заявка утверждена! Сотруднику отправлено уведомление в MAX.'
                            : '❌ Заявка отклонена. Сотруднику отправлено уведомление в MAX.',
                        'info'
                    );
                    await loadContext();
                }
            } finally {
                submitting.value = false;
            }
        };

        const runBatchApprove = async () => {
            submitting.value = true;
            try {
                const res = await fetch(`${API_BASE}/admin/batch-approve`, {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({
                        max_user_id: maxUserId.value,
                        year: selectedYear.value,
                    }),
                });
                if (res.ok) {
                    const data = await res.json();
                    showBanner(`⚡ Пакетное согласование завершено! Утверждено: ${data.approved_count || 0}, Конфликтов: ${data.conflict_count || 0}`, 'info');
                    await loadContext();
                }
            } finally {
                submitting.value = false;
            }
        };

        const updateBotAccess = async (employeeId, botAccess) => {
            await fetch(`${API_BASE}/admin/bot-access`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({
                    max_user_id: maxUserId.value,
                    employee_id: employeeId,
                    bot_access: botAccess,
                }),
            });
            await loadContext();
        };

        const filteredCompanySchedule = computed(() => {
            const q = scheduleSearch.value.toLowerCase().trim();
            const shiftF = scheduleShiftFilter.value;
            const monthF = Number(scheduleMonthFilter.value || 0);

            return companySchedule.value.filter(emp => {
                if (q) {
                    const matchText =
                        emp.full_name.toLowerCase().includes(q) ||
                        emp.role.toLowerCase().includes(q) ||
                        emp.department_name.toLowerCase().includes(q);
                    if (!matchText) return false;
                }
                if (shiftF && emp.shift !== shiftF) {
                    return false;
                }
                if (monthF > 0) {
                    const hasSlotInMonth = (emp.slots || []).some(sl => {
                        const mStart = new Date(sl.start_date).getMonth() + 1;
                        const mEnd = new Date(sl.end_date).getMonth() + 1;
                        return monthF >= mStart && monthF <= mEnd;
                    });
                    if (!hasSlotInMonth) return false;
                }
                return true;
            });
        });

        const formatDateRu = (isoStr) => {
            if (!isoStr) return '';
            const parts = String(isoStr).split('-');
            if (parts.length !== 3) return isoStr;
            return `${parts[2]}.${parts[1]}.${parts[0]}`;
        };

        const statusLabelRu = (st) => {
            if (st === 'APPROVED') return '🟢 Утвержден';
            if (st === 'CONFLICT') return '🔴 Конфликт';
            return '🟡 На согласовании';
        };

        const statusBadgeClass = (st) => {
            if (st === 'APPROVED') return 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
            if (st === 'CONFLICT') return 'bg-rose-500/20 text-rose-300 border border-rose-500/30';
            return 'bg-amber-500/20 text-amber-300 border border-amber-500/30';
        };

        watch(activeTab, () => refreshIcons());

        onMounted(() => {
            loadContext();
        });

        return {
            activeTab,
            selectedYear,
            maxUserId,
            loading,
            submitting,
            statusBanner,
            isAdmin,
            employee,
            mySlots,
            draftSlots,
            blackouts,
            departments,
            shifts,
            companySchedule,
            adminData,
            formStart,
            formEnd,
            alternatives,
            scheduleSearch,
            scheduleShiftFilter,
            scheduleMonthFilter,
            monthNames,
            computedSelectedDays,
            filteredCompanySchedule,
            loadContext,
            selectEmployeeFallback,
            changeYear,
            applyDurationPreset,
            onStartDateChange,
            acceptConsent,
            addPeriodToDraft,
            selectAlternative,
            removeDraftSlot,
            clearDraft,
            submitDraft,
            handleSlotAction,
            runBatchApprove,
            updateBotAccess,
            formatDateRu,
            statusLabelRu,
            statusBadgeClass,
        };
    }
}).mount('#miniapp');
