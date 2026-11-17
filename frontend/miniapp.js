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
        const yearPickedByUser = ref(false);
        const maxUserId = ref(detectMaxUserId());
        const adminToken = ref(localStorage.getItem('vacation_admin_token') || '');

        const loading = ref(false);
        const submitting = ref(false);
        const statusBanner = ref({ text: '', type: 'info' });

        const isAdmin = ref(false);
        const employee = ref(null);
        const mySlots = ref([]);
        const draftSlots = ref([]);
        const myRestrictions = ref([]);
        const blackouts = ref([]);
        const departments = ref([]);
        const shifts = ref([]);
        const companySchedule = ref([]);
        const adminData = ref(null);

        // Date form & editing state
        const formStart = ref(`${selectedYear.value}-07-01`);
        const formEnd = ref(`${selectedYear.value}-07-14`);
        const lastPresetDays = ref(14);
        const editingDraftIndex = ref(null);
        const alternatives = ref([]);

        // All vacations tab filters: 'my_shift' | 'my_dept' | 'all'
        const scheduleScope = ref('my_shift');
        const scheduleSearch = ref('');
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
                if (!maxUserId.value) {
                    const detected = detectMaxUserId();
                    if (detected) maxUserId.value = detected;
                }
                const q = new URLSearchParams();
                if (yearPickedByUser.value) {
                    q.set('year', String(selectedYear.value));
                }
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

                if (data.year && !yearPickedByUser.value && data.year !== selectedYear.value) {
                    selectedYear.value = data.year;
                    formStart.value = `${data.year}-07-01`;
                    formEnd.value = `${data.year}-07-14`;
                }

                if (data.resolved_max_user_id) {
                    maxUserId.value = data.resolved_max_user_id;
                    localStorage.setItem('vacation_miniapp_uid', data.resolved_max_user_id);
                }

                isAdmin.value = Boolean(data.is_admin);
                employee.value = data.employee || null;
                mySlots.value = data.my_slots || [];
                draftSlots.value = data.draft_slots || [];
                myRestrictions.value = data.my_restrictions || [];
                blackouts.value = data.blackouts || [];
                departments.value = data.departments || [];
                shifts.value = data.shifts || [];
                companySchedule.value = data.company_schedule || [];
                adminData.value = data.admin || null;

                if (!employee.value) {
                    scheduleScope.value = 'all';
                }

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
            yearPickedByUser.value = true;
            selectedYear.value = yr;
            formStart.value = `${yr}-07-01`;
            formEnd.value = `${yr}-07-14`;
            editingDraftIndex.value = null;
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

        const availableDaysForCurrentEdit = computed(() => {
            if (!employee.value) return 0;
            if (editingDraftIndex.value !== null && draftSlots.value[editingDraftIndex.value]) {
                return employee.value.remaining_days + draftSlots.value[editingDraftIndex.value].days;
            }
            return employee.value.remaining_days;
        });

        const isReadyToSubmitDraft = computed(() => {
            if (!employee.value || draftSlots.value.length === 0) return false;
            return employee.value.remaining_days === 0 && employee.value.has_14_day_block;
        });

        const hasEditableSubmittedSlots = computed(() => {
            return mySlots.value.some(s => s.status !== 'APPROVED');
        });

        const pendingAccessCount = computed(() => {
            if (!adminData.value || !adminData.value.employees_access) return 0;
            return adminData.value.employees_access.filter(e => e.bot_access === 'PENDING').length;
        });

        const applyDurationPreset = (days) => {
            if (!days || days <= 0) return;
            lastPresetDays.value = days;
            if (!formStart.value) {
                formStart.value = `${selectedYear.value}-07-01`;
            }
            const d = new Date(formStart.value);
            d.setDate(d.getDate() + days - 1);
            formEnd.value = d.toISOString().split('T')[0];
        };

        const onStartDateChange = () => {
            if (!formStart.value) return;
            const targetDays = lastPresetDays.value > 0
                ? lastPresetDays.value
                : ((employee.value && employee.value.remaining_days > 0 && employee.value.remaining_days < 14) ? employee.value.remaining_days : 14);
            applyDurationPreset(targetDays);
        };

        const startEditDraftSlot = (idx, slot) => {
            editingDraftIndex.value = idx;
            formStart.value = slot.start;
            formEnd.value = slot.end;
            lastPresetDays.value = slot.days || 14;
            alternatives.value = [];
            statusBanner.value.text = '';
            nextTick(() => {
                const pickerEl = document.getElementById('miniapp-date-picker');
                if (pickerEl && typeof pickerEl.scrollIntoView === 'function') {
                    pickerEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                refreshIcons();
            });
        };

        const cancelEditDraftSlot = () => {
            editingDraftIndex.value = null;
            alternatives.value = [];
            refreshIcons();
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

        const savePeriodToDraft = async () => {
            if (!maxUserId.value || !formStart.value || !formEnd.value) return;
            submitting.value = true;
            alternatives.value = [];
            statusBanner.value.text = '';
            const isEdit = editingDraftIndex.value !== null;
            const endpoint = isEdit ? `${API_BASE}/draft/update` : `${API_BASE}/draft/add`;
            const bodyPayload = isEdit
                ? {
                    max_user_id: maxUserId.value,
                    index: editingDraftIndex.value,
                    start_date: formStart.value,
                    end_date: formEnd.value,
                }
                : {
                    max_user_id: maxUserId.value,
                    start_date: formStart.value,
                    end_date: formEnd.value,
                };

            try {
                const res = await fetch(endpoint, {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify(bodyPayload),
                });
                const data = await res.json();
                if (!res.ok) {
                    showBanner(data.detail || 'Ошибка сохранения периода', 'error');
                    return;
                }
                const p = data.payload || {};
                const conflictList = p.conflicts || p.violations || [];
                if (p.action === 'OFFER_ALTERNATIVES' || p.action === 'INVALID_TK' || p.action === 'OVER_LIMIT' || p.action === 'PARSE_ERROR' || conflictList.length > 0) {
                    showBanner(conflictList.length > 0 ? conflictList.join('\n') : (data.text || 'Проверьте выбранные даты'), 'error');
                    alternatives.value = p.suggested_alternatives || [];
                } else {
                    if (isEdit) {
                        editingDraftIndex.value = null;
                        showBanner('✏️ Даты периода успешно изменены в черновике!', 'info');
                    } else {
                        showBanner('Период проверен и добавлен в черновик!', 'info');
                    }
                }
                await loadContext();
            } finally {
                submitting.value = false;
            }
        };

        const addPeriodToDraft = savePeriodToDraft;

        const selectAlternative = async (alt) => {
            if (!maxUserId.value || !alt) return;
            submitting.value = true;
            try {
                const slotsList = Array.isArray(alt.slots) && alt.slots.length > 0
                    ? alt.slots
                    : (alt.start && alt.end ? [{ start: alt.start, end: alt.end }] : []);
                if (slotsList.length === 0) return;

                const editIdx = alt.edit_index !== undefined && alt.edit_index !== null
                    ? alt.edit_index
                    : editingDraftIndex.value;

                const res = await fetch(`${API_BASE}/draft/select-alternative`, {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({
                        max_user_id: maxUserId.value,
                        slots: slotsList,
                        replace_draft: alt.replace_draft !== false,
                        edit_index: editIdx,
                    }),
                });
                if (res.ok) {
                    alternatives.value = [];
                    editingDraftIndex.value = null;
                    showBanner('Свободный вариант применен в ваш черновик!', 'info');
                    await loadContext();
                } else {
                    const err = await res.json();
                    showBanner(err.detail || 'Не удалось применить выбранный вариант', 'error');
                }
            } finally {
                submitting.value = false;
            }
        };

        const removeDraftSlot = async (idx) => {
            if (!maxUserId.value) return;
            if (editingDraftIndex.value === idx) {
                editingDraftIndex.value = null;
            }
            await fetch(`${API_BASE}/draft/remove`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({ max_user_id: maxUserId.value, index: idx }),
            });
            alternatives.value = [];
            await loadContext();
        };

        const clearDraft = async () => {
            if (!maxUserId.value) return;
            editingDraftIndex.value = null;
            await fetch(`${API_BASE}/draft/remove`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({ max_user_id: maxUserId.value, reset_all: true }),
            });
            alternatives.value = [];
            await loadContext();
        };

        const recallSubmittedSlots = async (slotId = null) => {
            if (!maxUserId.value) return;
            submitting.value = true;
            try {
                const res = await fetch(`${API_BASE}/slots/recall`, {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({
                        max_user_id: maxUserId.value,
                        year: selectedYear.value,
                        slot_id: slotId,
                    }),
                });
                const data = await res.json();
                if (!res.ok) {
                    showBanner(data.detail || 'Не удалось вернуть периоды в черновик', 'error');
                    return;
                }
                showBanner('✏️ Заявка возвращена в черновик! Нажмите «Изменить» у нужного периода, чтобы поправить даты.', 'info');
                await loadContext();
                if (draftSlots.value.length > 0) {
                    startEditDraftSlot(0, draftSlots.value[0]);
                }
            } finally {
                submitting.value = false;
            }
        };

        const submitDraft = async () => {
            if (!maxUserId.value) return;
            submitting.value = true;
            editingDraftIndex.value = null;
            try {
                const res = await fetch(`${API_BASE}/draft/submit`, {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({ max_user_id: maxUserId.value }),
                });
                const data = await res.json();
                const p = data.payload || {};
                if (p.action === 'SUBMISSION_CONFIRMED' || p.action === 'COMMITTED') {
                    showBanner('✅ Заявка успешно отправлена руководителю и добавлена в график!', 'info');
                } else {
                    showBanner(data.text || 'Распределите все 36 дней (с блоком ≥ 14 дн.) перед отправкой.', 'error');
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
                            ? '✅ Заявка утверждена! Сотруднице отправлено уведомление в MAX.'
                            : '❌ Заявка отклонена. Сотруднице отправлено уведомление в MAX.',
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
                    const conflictsCount = data.conflicts_count ?? data.conflict_count ?? 0;
                    showBanner(
                        `⚡ Авто-согласование завершено! Утверждено: ${data.approved_count || 0}, Конфликтов: ${conflictsCount}`,
                        'info'
                    );
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
            const monthF = Number(scheduleMonthFilter.value || 0);
            const scope = scheduleScope.value;

            return companySchedule.value.filter(emp => {
                if (employee.value) {
                    if (scope === 'my_shift' && emp.shift !== employee.value.shift) {
                        return false;
                    }
                    if (scope === 'my_dept' && emp.department_id !== employee.value.department_id) {
                        return false;
                    }
                }
                if (q) {
                    const matchText =
                        emp.full_name.toLowerCase().includes(q) ||
                        emp.role.toLowerCase().includes(q) ||
                        emp.department_name.toLowerCase().includes(q);
                    if (!matchText) return false;
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

        const formatAltSlots = (alt) => {
            if (!alt) return '';
            if (Array.isArray(alt.slots) && alt.slots.length > 0) {
                return alt.slots.map(s => `${formatDateRu(s.start)} – ${formatDateRu(s.end)}`).join(', ');
            }
            if (alt.start && alt.end) {
                return `${formatDateRu(alt.start)} – ${formatDateRu(alt.end)}`;
            }
            return '';
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
            try {
                if (window.WebApp && typeof window.WebApp.ready === 'function') {
                    window.WebApp.ready();
                }
                if (window.Telegram && window.Telegram.WebApp && typeof window.Telegram.WebApp.ready === 'function') {
                    window.Telegram.WebApp.ready();
                }
            } catch (_) {}
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
            myRestrictions,
            blackouts,
            departments,
            shifts,
            companySchedule,
            adminData,
            formStart,
            formEnd,
            editingDraftIndex,
            availableDaysForCurrentEdit,
            hasEditableSubmittedSlots,
            alternatives,
            scheduleScope,
            scheduleSearch,
            scheduleMonthFilter,
            monthNames,
            computedSelectedDays,
            isReadyToSubmitDraft,
            pendingAccessCount,
            filteredCompanySchedule,
            loadContext,
            selectEmployeeFallback,
            changeYear,
            applyDurationPreset,
            onStartDateChange,
            startEditDraftSlot,
            cancelEditDraftSlot,
            savePeriodToDraft,
            acceptConsent,
            addPeriodToDraft,
            selectAlternative,
            removeDraftSlot,
            clearDraft,
            recallSubmittedSlots,
            submitDraft,
            handleSlotAction,
            runBatchApprove,
            updateBotAccess,
            formatDateRu,
            formatAltSlots,
            statusLabelRu,
            statusBadgeClass,
        };
    }
}).mount('#miniapp');
